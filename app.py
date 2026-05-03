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

@app.route("/webhook/whatsapp", methods=["POST"])
def webhook_whatsapp():
    from agente.agente import processar_mensagem
    payload = request.json
    logging.warning(f"WEBHOOK PAYLOAD: {payload}")
    try:
        msg = None
        fone = None

        if payload.get("inputs"):
            inputs = payload["inputs"]
            msg = (inputs.get("query") or inputs.get("message") or inputs.get("text") or
                   payload.get("query") or payload.get("message") or payload.get("text", ""))
            fone = (inputs.get("remoteJid", "").replace("@s.whatsapp.net", "") or
                    inputs.get("user", "").replace("@s.whatsapp.net", "") or
                    payload.get("user", "").replace("@s.whatsapp.net", ""))
        elif payload.get("query"):
            msg = payload.get("query", "")
            fone = payload.get("remoteJid", "").replace("@s.whatsapp.net", "") or \
                   payload.get("user", "").replace("@s.whatsapp.net", "")
        elif payload.get("data"):
            data = payload["data"]
            msg = data.get("message", {}).get("conversation") or data.get("body", "")
            fone = data.get("key", {}).get("remoteJid", "").replace("@s.whatsapp.net", "")
        elif payload.get("body"):
            msg = payload.get("body", "")
            fone = payload.get("from", "").replace("@s.whatsapp.net", "")

        if not msg or not fone:
            logging.warning(f"Payload nao reconhecido: {payload}")
            return jsonify({"output": "", "status": "ignorado"}), 200

        resposta = processar_mensagem(fone, msg)
        return jsonify({"output": resposta, "status": "ok"})
    except Exception as e:
        logging.error(f"Erro webhook: {e}")
        return jsonify({"output": "Desculpe, tente novamente.", "status": "erro"}), 200

@app.route("/admin/debug")
def admin_debug():
    import requests as req
    result = {}
    conn = get_db()
    clientes = conn.execute("SELECT id, nome, whatsapp, status FROM clientes").fetchall()
    conn.close()
    result["clientes"] = [dict(c) for c in clientes]
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    result["anthropic_key_set"] = bool(api_key)
    if api_key:
        try:
            r = req.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-sonnet-4-6", "max_tokens": 10, "messages": [{"role": "user", "content": "oi"}]},
                timeout=10
            )
            result["claude_status"] = r.status_code
            result["claude_response"] = r.json()
        except Exception as e:
            result["claude_error"] = str(e)
    result["evolution_url"] = os.environ.get("EVOLUTION_URL", "NÃO DEFINIDO")
    result["evolution_key_set"] = bool(os.environ.get("EVOLUTION_KEY", ""))
    result["use_postgres"] = USE_PG
    return jsonify(result)

@app.route("/admin/criar-teste")
def admin_criar_teste():
    senha_hash = hashlib.sha256("teste123".encode()).hexdigest()
    conn = get_db()
    try:
        if USE_PG:
            conn.execute(
                "INSERT INTO clientes (nome, email, senha_hash, whatsapp, status) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (email) DO NOTHING",
                ("Eduardo Lorenzi", "eduardo@teste.com", senha_hash, normalizar_whatsapp("556198007328"), "ativo")
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO clientes (nome, email, senha_hash, whatsapp, status) VALUES (%s, %s, %s, %s, %s)",
                ("Eduardo Lorenzi", "eduardo@teste.com", senha_hash, normalizar_whatsapp("556198007328"), "ativo")
            )
        conn.commit()
        cliente = conn.execute("SELECT * FROM clientes WHERE whatsapp=%s", ("556198007328",)).fetchone()
    finally:
        conn.close()
    return jsonify({"status": "ok", "cliente_id": cliente["id"], "nome": cliente["nome"], "whatsapp": cliente["whatsapp"]})

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
