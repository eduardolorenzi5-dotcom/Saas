from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import os, hashlib, secrets, logging
from datetime import datetime, date
from functools import wraps
from db import get_db, USE_PG

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

def init_db():
    conn = get_db()
    if USE_PG:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS planos (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL,
                preco REAL NOT NULL,
                descricao TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clientes (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                senha_hash TEXT NOT NULL,
                whatsapp TEXT,
                plano_id INTEGER,
                status TEXT DEFAULT 'pendente',
                token_acesso TEXT UNIQUE,
                criado_em TIMESTAMP DEFAULT NOW(),
                FOREIGN KEY (plano_id) REFERENCES planos(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gastos (
                id SERIAL PRIMARY KEY,
                cliente_id INTEGER NOT NULL,
                descricao TEXT NOT NULL,
                valor REAL NOT NULL,
                categoria TEXT NOT NULL,
                data TEXT NOT NULL,
                fonte TEXT DEFAULT 'manual',
                criado_em TIMESTAMP DEFAULT NOW(),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pagamentos (
                id SERIAL PRIMARY KEY,
                cliente_id INTEGER NOT NULL,
                valor REAL NOT NULL,
                status TEXT DEFAULT 'pendente',
                referencia TEXT,
                criado_em TIMESTAMP DEFAULT NOW(),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            )
        """)
    else:
        conn._raw.executescript("""
            CREATE TABLE IF NOT EXISTS planos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                preco REAL NOT NULL,
                descricao TEXT
            );
            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                senha_hash TEXT NOT NULL,
                whatsapp TEXT,
                plano_id INTEGER,
                status TEXT DEFAULT 'pendente',
                token_acesso TEXT UNIQUE,
                criado_em TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (plano_id) REFERENCES planos(id)
            );
            CREATE TABLE IF NOT EXISTS gastos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                descricao TEXT NOT NULL,
                valor REAL NOT NULL,
                categoria TEXT NOT NULL,
                data TEXT NOT NULL,
                fonte TEXT DEFAULT 'manual',
                criado_em TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            );
            CREATE TABLE IF NOT EXISTS pagamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                valor REAL NOT NULL,
                status TEXT DEFAULT 'pendente',
                referencia TEXT,
                criado_em TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            );
        """)
    # Adiciona colunas de reset de senha se não existirem
    if USE_PG:
        conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS reset_token TEXT")
        conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS reset_expiry TEXT")
    else:
        for col in ["reset_token TEXT", "reset_expiry TEXT"]:
            try:
                conn.execute(f"ALTER TABLE clientes ADD COLUMN {col}")
            except Exception:
                pass
    conn.commit()

    existe = conn.execute("SELECT COUNT(*) as cnt FROM planos").fetchone()["cnt"]
    if not existe:
        conn.executemany("INSERT INTO planos (nome, preco, descricao) VALUES (%s, %s, %s)", [
            ("Basico",  29.90, "Controle de gastos + relatorio mensal"),
            ("Pro",     59.90, "Tudo do Basico + multiplos usuarios + relatorios semanais"),
            ("Premium", 99.90, "Tudo do Pro + consultoria financeira mensal"),
        ])
    conn.commit()
    conn.close()

def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

def enviar_email_reset(destinatario, link):
    import urllib.request, json as _json
    api_key = os.environ.get("BREVO_API_KEY", "")
    sender_email = os.environ.get("BREVO_FROM_EMAIL", "")
    sender_name = os.environ.get("BREVO_FROM_NAME", "Controla Fácil")
    if not api_key or not sender_email:
        raise Exception("BREVO_API_KEY ou BREVO_FROM_EMAIL nao configurado")
    corpo = (
        f"Olá!\n\n"
        f"Recebemos uma solicitação para redefinir sua senha no Controla Fácil.\n\n"
        f"Clique no link abaixo para criar uma nova senha (válido por 1 hora):\n\n"
        f"{link}\n\n"
        f"Se você não solicitou isso, ignore este e-mail.\n\n"
        f"— Equipe Controla Fácil"
    )
    payload = _json.dumps({
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": destinatario}],
        "subject": "Redefinição de senha — Controla Fácil",
        "textContent": corpo,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status not in (200, 201):
            raise Exception(f"Brevo retornou status {resp.status}")

def normalizar_whatsapp(numero):
    """Remove tudo que não é dígito e garante o formato 55DDDNUMERO."""
    digits = "".join(c for c in numero if c.isdigit())
    if not digits.startswith("55"):
        digits = "55" + digits
    return digits

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "cliente_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/")
def index():
    conn = get_db()
    planos = conn.execute("SELECT * FROM planos ORDER BY preco").fetchall()
    conn.close()
    return render_template("index.html", planos=planos)

@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        nome     = request.form.get("nome", "").strip()
        email    = request.form.get("email", "").strip().lower()
        senha    = request.form.get("senha", "")
        whatsapp = normalizar_whatsapp(request.form.get("whatsapp", "").strip())
        plano_id = request.form.get("plano_id")
        if not all([nome, email, senha, whatsapp, plano_id]):
            return render_template("cadastro.html", erro="Preencha todos os campos.")
        token = secrets.token_urlsafe(32)
        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO clientes (nome, email, senha_hash, whatsapp, plano_id, token_acesso) VALUES (%s, %s, %s, %s, %s, %s)",
                (nome, email, hash_senha(senha), whatsapp, plano_id, token)
            )
            conn.commit()
            cliente_id = conn.execute("SELECT id FROM clientes WHERE email=%s", (email,)).fetchone()["id"]
            conn.close()
            return redirect(url_for("pagamento", cliente_id=cliente_id))
        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                return render_template("cadastro.html", erro="E-mail ja cadastrado.")
            raise
    conn = get_db()
    planos = conn.execute("SELECT * FROM planos ORDER BY preco").fetchall()
    conn.close()
    return render_template("cadastro.html", planos=planos)

@app.route("/pagamento/<int:cliente_id>")
def pagamento(cliente_id):
    conn = get_db()
    cliente = conn.execute(
        "SELECT c.*, p.nome as plano_nome, p.preco FROM clientes c JOIN planos p ON c.plano_id=p.id WHERE c.id=%s",
        (cliente_id,)
    ).fetchone()
    conn.close()
    return render_template("pagamento.html", cliente=cliente)

@app.route("/pagamento/checkout/<int:cliente_id>", methods=["POST"])
def checkout_mercadopago(cliente_id):
    import requests as _req
    mp_token = os.environ.get("MP_ACCESS_TOKEN", "")
    if not mp_token:
        return render_template("pagamento.html",
            cliente=_get_cliente_plano(cliente_id),
            erro="Pagamento indisponível no momento. Contate o suporte.")

    conn = get_db()
    cliente = conn.execute(
        "SELECT c.*, p.nome as plano_nome, p.preco FROM clientes c JOIN planos p ON c.plano_id=p.id WHERE c.id=%s",
        (cliente_id,)
    ).fetchone()
    conn.close()
    if not cliente:
        return redirect(url_for("index"))

    base_url = os.environ.get("BASE_URL", "https://saas-production-2a7a.up.railway.app")
    payload = {
        "items": [{
            "title": f"Controla Fácil — Plano {cliente['plano_nome']}",
            "quantity": 1,
            "currency_id": "BRL",
            "unit_price": float(cliente["preco"]),
        }],
        "payer": {"email": cliente["email"]},
        "back_urls": {
            "success": f"{base_url}/pagamento/sucesso/{cliente_id}",
            "failure": f"{base_url}/pagamento/{cliente_id}",
            "pending": f"{base_url}/pagamento/sucesso/{cliente_id}",
        },
        "auto_return": "approved",
        "notification_url": f"{base_url}/webhook/mercadopago",
        "external_reference": str(cliente_id),
    }
    resp = _req.post(
        "https://api.mercadopago.com/checkout/preferences",
        headers={"Authorization": f"Bearer {mp_token}", "Content-Type": "application/json"},
        json=payload, timeout=15
    )
    if resp.status_code != 201:
        logging.error(f"MP erro: {resp.text}")
        return render_template("pagamento.html", cliente=cliente,
            erro="Erro ao criar pagamento. Tente novamente.")
    init_point = resp.json().get("init_point")
    return redirect(init_point)

def _get_cliente_plano(cliente_id):
    conn = get_db()
    c = conn.execute(
        "SELECT c.*, p.nome as plano_nome, p.preco FROM clientes c JOIN planos p ON c.plano_id=p.id WHERE c.id=%s",
        (cliente_id,)
    ).fetchone()
    conn.close()
    return c

@app.route("/pagamento/sucesso/<int:cliente_id>")
def pagamento_sucesso(cliente_id):
    conn = get_db()
    cliente = conn.execute(
        "SELECT c.*, p.preco FROM clientes c JOIN planos p ON c.plano_id=p.id WHERE c.id=%s",
        (cliente_id,)
    ).fetchone()
    if cliente and cliente["status"] != "ativo":
        conn.execute("UPDATE clientes SET status='ativo' WHERE id=%s", (cliente_id,))
        conn.execute(
            "INSERT INTO pagamentos (cliente_id, valor, status) VALUES (%s, %s, %s)",
            (cliente_id, cliente["preco"], "aprovado")
        )
        conn.commit()
    conn.close()
    return redirect(url_for("sucesso", cliente_id=cliente_id))

@app.route("/webhook/mercadopago", methods=["POST"])
def webhook_mercadopago():
    import requests as _req
    mp_token = os.environ.get("MP_ACCESS_TOKEN", "")
    try:
        data = request.json or {}
        logging.warning(f"MP WEBHOOK: {data}")
        if data.get("type") == "payment":
            payment_id = data.get("data", {}).get("id")
            if payment_id:
                resp = _req.get(
                    f"https://api.mercadopago.com/v1/payments/{payment_id}",
                    headers={"Authorization": f"Bearer {mp_token}"}, timeout=10
                )
                payment = resp.json()
                if payment.get("status") == "approved":
                    cliente_id = int(payment.get("external_reference", 0))
                    if cliente_id:
                        conn = get_db()
                        cliente = conn.execute("SELECT * FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
                        if cliente and cliente["status"] != "ativo":
                            conn.execute("UPDATE clientes SET status='ativo' WHERE id=%s", (cliente_id,))
                            conn.execute(
                                "INSERT INTO pagamentos (cliente_id, valor, status, referencia) VALUES (%s, %s, %s, %s)",
                                (cliente_id, payment.get("transaction_amount", 0), "aprovado", str(payment_id))
                            )
                            conn.commit()
                        conn.close()
    except Exception as e:
        logging.error(f"Erro webhook MP: {e}")
    return jsonify({"ok": True}), 200

@app.route("/pagamento/confirmar/<int:cliente_id>", methods=["POST"])
def confirmar_pagamento(cliente_id):
    conn = get_db()
    cliente = conn.execute(
        "SELECT c.*, p.preco FROM clientes c JOIN planos p ON c.plano_id=p.id WHERE c.id=%s",
        (cliente_id,)
    ).fetchone()
    if cliente:
        conn.execute("UPDATE clientes SET status='ativo' WHERE id=%s", (cliente_id,))
        conn.execute(
            "INSERT INTO pagamentos (cliente_id, valor, status) VALUES (%s, %s, %s)",
            (cliente_id, cliente["preco"], "aprovado")
        )
        conn.commit()
    conn.close()
    return redirect(url_for("sucesso", cliente_id=cliente_id))

@app.route("/sucesso/<int:cliente_id>")
def sucesso(cliente_id):
    conn = get_db()
    cliente = conn.execute("SELECT * FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
    conn.close()
    return render_template("sucesso.html", cliente=cliente)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        conn = get_db()
        cliente = conn.execute(
            "SELECT * FROM clientes WHERE email=%s AND senha_hash=%s",
            (email, hash_senha(senha))
        ).fetchone()
        conn.close()
        if cliente:
            if cliente["status"] != "ativo":
                return render_template("login.html", erro="Sua conta ainda nao foi ativada.")
            session["cliente_id"] = cliente["id"]
            session["cliente_nome"] = cliente["nome"]
            return redirect(url_for("dashboard"))
        return render_template("login.html", erro="E-mail ou senha incorretos.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    cid = session["cliente_id"]
    mes = date.today().strftime("%Y-%m")
    conn = get_db()
    gastos = conn.execute(
        "SELECT * FROM gastos WHERE cliente_id=%s AND data LIKE %s ORDER BY data DESC",
        (cid, f"{mes}%")
    ).fetchall()
    total = conn.execute(
        "SELECT COALESCE(SUM(valor),0) as t FROM gastos WHERE cliente_id=%s AND data LIKE %s",
        (cid, f"{mes}%")
    ).fetchone()["t"]
    por_cat = conn.execute(
        "SELECT categoria, SUM(valor) as total FROM gastos WHERE cliente_id=%s AND data LIKE %s GROUP BY categoria ORDER BY total DESC",
        (cid, f"{mes}%")
    ).fetchall()
    cliente = conn.execute("SELECT * FROM clientes WHERE id=%s", (cid,)).fetchone()
    conn.close()
    return render_template("dashboard.html",
        gastos=gastos, total=total, por_cat=por_cat,
        cliente=cliente, mes=mes
    )

@app.route("/api/gastos", methods=["POST"])
@login_required
def adicionar_gasto():
    data = request.json
    cid  = session["cliente_id"]
    conn = get_db()
    conn.execute(
        "INSERT INTO gastos (cliente_id, descricao, valor, categoria, data, fonte) VALUES (%s, %s, %s, %s, %s, %s)",
        (cid, data["descricao"], float(data["valor"]), data["categoria"],
         data.get("data", date.today().isoformat()), data.get("fonte", "manual"))
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/gastos/<int:gid>", methods=["DELETE"])
@login_required
def deletar_gasto(gid):
    conn = get_db()
    conn.execute("DELETE FROM gastos WHERE id=%s AND cliente_id=%s", (gid, session["cliente_id"]))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/gastos/mes", methods=["DELETE"])
@login_required
def deletar_gastos_mes():
    mes = date.today().strftime("%Y-%m")
    conn = get_db()
    conn.execute("DELETE FROM gastos WHERE cliente_id=%s AND data LIKE %s", (session["cliente_id"], f"{mes}%"))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/esqueci-senha", methods=["GET", "POST"])
def esqueci_senha():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        conn = get_db()
        cliente = conn.execute("SELECT * FROM clientes WHERE email=%s", (email,)).fetchone()
        if cliente:
            token = secrets.token_urlsafe(32)
            expiry = (datetime.utcnow().replace(microsecond=0) + __import__("datetime").timedelta(hours=1)).isoformat()
            conn.execute(
                "UPDATE clientes SET reset_token=%s, reset_expiry=%s WHERE email=%s",
                (token, expiry, email)
            )
            conn.commit()
            base_url = os.environ.get("BASE_URL", request.host_url.rstrip("/"))
            link = f"{base_url}/resetar-senha/{token}"
            import threading
            def _send():
                try:
                    enviar_email_reset(email, link)
                except Exception as e:
                    logging.error(f"Erro ao enviar email: {e}")
            threading.Thread(target=_send, daemon=True).start()
        conn.close()
        return render_template("esqueci_senha.html", enviado=True)
    return render_template("esqueci_senha.html", enviado=False)

@app.route("/resetar-senha/<token>", methods=["GET", "POST"])
def resetar_senha(token):
    conn = get_db()
    cliente = conn.execute(
        "SELECT * FROM clientes WHERE reset_token=%s", (token,)
    ).fetchone()
    if not cliente:
        conn.close()
        return render_template("resetar_senha.html", erro="Link inválido ou expirado.", token=token, valido=False)
    expiry = cliente["reset_expiry"]
    if not expiry or datetime.utcnow().isoformat() > expiry:
        conn.close()
        return render_template("resetar_senha.html", erro="Link expirado. Solicite um novo.", token=token, valido=False)
    if request.method == "POST":
        nova_senha = request.form.get("senha", "")
        confirma = request.form.get("confirma", "")
        if len(nova_senha) < 6:
            conn.close()
            return render_template("resetar_senha.html", erro="A senha deve ter pelo menos 6 caracteres.", token=token, valido=True)
        if nova_senha != confirma:
            conn.close()
            return render_template("resetar_senha.html", erro="As senhas não coincidem.", token=token, valido=True)
        conn.execute(
            "UPDATE clientes SET senha_hash=%s, reset_token=NULL, reset_expiry=NULL WHERE reset_token=%s",
            (hash_senha(nova_senha), token)
        )
        conn.commit()
        conn.close()
        return redirect(url_for("login"))
    conn.close()
    return render_template("resetar_senha.html", erro=None, token=token, valido=True)

def _extrair_imagem_b64(payload, inputs):
    """Tenta extrair imagem em base64 do payload do webhook."""
    import base64 as _b64, requests as _req

    # Formato n8n/typebot: payload.files = [{'type': 'image', 'url': '...'}]
    for f in payload.get("files", []):
        if f.get("type") == "image":
            url = f.get("url", "")
            if url.startswith("http"):
                try:
                    r = _req.get(url, timeout=15)
                    if r.status_code == 200:
                        return _b64.b64encode(r.content).decode()
                except Exception as e:
                    logging.warning(f"Falha ao baixar imagem: {e}")
            elif url:
                # Pode ser message ID — busca via Evolution API
                try:
                    ev_url = os.environ.get("EVOLUTION_URL", "")
                    ev_key = os.environ.get("EVOLUTION_KEY", "")
                    ev_inst = os.environ.get("EVOLUTION_INSTANCE", "gastosai")
                    fone = inputs.get("remoteJid") or payload.get("user", "")
                    r = _req.post(
                        f"{ev_url}/chat/getBase64FromMediaMessage/{ev_inst}",
                        headers={"apikey": ev_key, "Content-Type": "application/json"},
                        json={"message": {"key": {"id": url, "remoteJid": fone}}},
                        timeout=15
                    )
                    if r.status_code == 200:
                        data = r.json()
                        b64 = data.get("base64") or data.get("data")
                        if b64:
                            return b64
                except Exception as e:
                    logging.warning(f"Falha ao buscar imagem via Evolution API: {e}")

    # base64 direto no payload
    for campo in ["base64", "mediaBase64", "imageBase64"]:
        v = inputs.get(campo) or payload.get(campo)
        if v:
            return v

    # URL direta em campos avulsos
    media_url = inputs.get("mediaUrl") or inputs.get("imageUrl") or payload.get("mediaUrl")
    if media_url:
        try:
            r = _req.get(media_url, timeout=10)
            if r.status_code == 200:
                return _b64.b64encode(r.content).decode()
        except Exception as e:
            logging.warning(f"Falha ao baixar imagem de {media_url}: {e}")
    return None

@app.route("/webhook/whatsapp", methods=["POST"])
def webhook_whatsapp():
    from agente.agente import processar_mensagem, processar_imagem
    payload = request.json
    logging.warning(f"WEBHOOK PAYLOAD: {payload}")
    try:
        msg = None
        fone = None
        imagem_b64 = None

        if payload.get("inputs"):
            inputs = payload["inputs"]
            msg = (inputs.get("query") or inputs.get("message") or inputs.get("text") or
                   payload.get("query") or payload.get("message") or payload.get("text", ""))
            fone = (inputs.get("remoteJid", "").replace("@s.whatsapp.net", "") or
                    inputs.get("user", "").replace("@s.whatsapp.net", "") or
                    payload.get("user", "").replace("@s.whatsapp.net", ""))
            imagem_b64 = _extrair_imagem_b64(payload, inputs)
        elif payload.get("query"):
            msg = payload.get("query", "")
            fone = payload.get("remoteJid", "").replace("@s.whatsapp.net", "") or \
                   payload.get("user", "").replace("@s.whatsapp.net", "")
            imagem_b64 = _extrair_imagem_b64(payload, {})
        elif payload.get("data"):
            data = payload["data"]
            img_msg = data.get("message", {}).get("imageMessage", {})
            msg = img_msg.get("caption") or data.get("message", {}).get("conversation") or data.get("body", "")
            fone = data.get("key", {}).get("remoteJid", "").replace("@s.whatsapp.net", "")
            imagem_b64 = _extrair_imagem_b64(payload, img_msg)
        elif payload.get("body"):
            msg = payload.get("body", "")
            fone = payload.get("from", "").replace("@s.whatsapp.net", "")
            imagem_b64 = _extrair_imagem_b64(payload, {})

        if not fone:
            logging.warning(f"Payload nao reconhecido: {payload}")
            return jsonify({"output": "", "status": "ignorado"}), 200

        if imagem_b64:
            resposta = processar_imagem(fone, imagem_b64, msg or "")
        elif msg:
            resposta = processar_mensagem(fone, msg)
        else:
            logging.warning(f"Sem mensagem nem imagem: {payload}")
            return jsonify({"output": "", "status": "ignorado"}), 200

        return jsonify({"output": resposta, "status": "ok"})
    except Exception as e:
        logging.error(f"Erro webhook: {e}")
        return jsonify({"output": "Desculpe, tente novamente.", "status": "erro"}), 200


@app.route("/admin/ativar/<email>")
def admin_ativar(email):
    admin_key = request.args.get("key", "")
    if admin_key != os.environ.get("ADMIN_KEY", ""):
        return jsonify({"erro": "nao autorizado"}), 403
    conn = get_db()
    conn.execute("UPDATE clientes SET status='ativo' WHERE email=%s", (email,))
    conn.commit()
    cliente = conn.execute("SELECT id, nome, email, status FROM clientes WHERE email=%s", (email,)).fetchone()
    conn.close()
    if not cliente:
        return jsonify({"erro": "cliente nao encontrado"})
    return jsonify(dict(cliente))

@app.route("/relatorio/gerar/<int:cliente_id>")
def gerar_relatorio(cliente_id):
    from relatorio.gerador import gerar_pdf
    mes = request.args.get("mes", date.today().strftime("%Y-%m"))
    caminho = gerar_pdf(cliente_id, mes)
    return jsonify({"arquivo": caminho})

with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
