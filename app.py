from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import sqlite3, os, hashlib, secrets
from datetime import datetime, date
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gastos.db")

# ── Banco de dados ─────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
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
    # Inserir planos padrão se não existirem
    existe = conn.execute("SELECT COUNT(*) FROM planos").fetchone()[0]
    if not existe:
        conn.executemany("INSERT INTO planos (nome, preco, descricao) VALUES (?,?,?)", [
            ("Básico",  29.90, "Controle de gastos + relatório mensal"),
            ("Pro",     59.90, "Tudo do Básico + múltiplos usuários + relatórios semanais"),
            ("Premium", 99.90, "Tudo do Pro + consultoria financeira mensal"),
        ])
    conn.commit()
    conn.close()

def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

# ── Decorators ─────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "cliente_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ── Site público ───────────────────────────────────────────────────────────────
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
        whatsapp = request.form.get("whatsapp", "").strip()
        plano_id = request.form.get("plano_id")

        if not all([nome, email, senha, whatsapp, plano_id]):
            return render_template("cadastro.html", erro="Preencha todos os campos.")

        token = secrets.token_urlsafe(32)
        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO clientes (nome, email, senha_hash, whatsapp, plano_id, token_acesso) VALUES (?,?,?,?,?,?)",
                (nome, email, hash_senha(senha), whatsapp, plano_id, token)
            )
            conn.commit()
            cliente_id = conn.execute("SELECT id FROM clientes WHERE email=?", (email,)).fetchone()["id"]
            conn.close()
            # Redireciona para pagamento (simulado)
            return redirect(url_for("pagamento", cliente_id=cliente_id))
        except sqlite3.IntegrityError:
            return render_template("cadastro.html", erro="E-mail já cadastrado.")

    conn = get_db()
    planos = conn.execute("SELECT * FROM planos ORDER BY preco").fetchall()
    conn.close()
    return render_template("cadastro.html", planos=planos)

@app.route("/pagamento/<int:cliente_id>")
def pagamento(cliente_id):
    conn = get_db()
    cliente = conn.execute(
        "SELECT c.*, p.nome as plano_nome, p.preco FROM clientes c JOIN planos p ON c.plano_id=p.id WHERE c.id=?",
        (cliente_id,)
    ).fetchone()
    conn.close()
    return render_template("pagamento.html", cliente=cliente)

@app.route("/pagamento/confirmar/<int:cliente_id>", methods=["POST"])
def confirmar_pagamento(cliente_id):
    """Simula confirmação de pagamento. Em produção, integrar Stripe/Mercado Pago."""
    conn = get_db()
    cliente = conn.execute(
        "SELECT c.*, p.preco FROM clientes c JOIN planos p ON c.plano_id=p.id WHERE c.id=?",
        (cliente_id,)
    ).fetchone()
    if cliente:
        conn.execute("UPDATE clientes SET status='ativo' WHERE id=?", (cliente_id,))
        conn.execute(
            "INSERT INTO pagamentos (cliente_id, valor, status) VALUES (?,?,?)",
            (cliente_id, cliente["preco"], "aprovado")
        )
        conn.commit()
    conn.close()
    return redirect(url_for("sucesso", cliente_id=cliente_id))

@app.route("/sucesso/<int:cliente_id>")
def sucesso(cliente_id):
    conn = get_db()
    cliente = conn.execute("SELECT * FROM clientes WHERE id=?", (cliente_id,)).fetchone()
    conn.close()
    return render_template("sucesso.html", cliente=cliente)

# ── Login / Logout ─────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        conn = get_db()
        cliente = conn.execute(
            "SELECT * FROM clientes WHERE email=? AND senha_hash=?",
            (email, hash_senha(senha))
        ).fetchone()
        conn.close()
        if cliente:
            if cliente["status"] != "ativo":
                return render_template("login.html", erro="Sua conta ainda não foi ativada. Conclua o pagamento.")
            session["cliente_id"] = cliente["id"]
            session["cliente_nome"] = cliente["nome"]
            return redirect(url_for("dashboard"))
        return render_template("login.html", erro="E-mail ou senha incorretos.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# ── Dashboard do cliente ───────────────────────────────────────────────────────
@app.route("/dashboard")
@login_required
def dashboard():
    cid = session["cliente_id"]
    mes = date.today().strftime("%Y-%m")
    conn = get_db()
    gastos = conn.execute(
        "SELECT * FROM gastos WHERE cliente_id=? AND data LIKE ? ORDER BY data DESC",
        (cid, f"{mes}%")
    ).fetchall()
    total = conn.execute(
        "SELECT COALESCE(SUM(valor),0) as t FROM gastos WHERE cliente_id=? AND data LIKE ?",
        (cid, f"{mes}%")
    ).fetchone()["t"]
    por_cat = conn.execute(
        "SELECT categoria, SUM(valor) as total FROM gastos WHERE cliente_id=? AND data LIKE ? GROUP BY categoria ORDER BY total DESC",
        (cid, f"{mes}%")
    ).fetchall()
    cliente = conn.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone()
    conn.close()
    return render_template("dashboard.html",
        gastos=gastos, total=total, por_cat=por_cat,
        cliente=cliente, mes=mes
    )

# ── API de gastos ──────────────────────────────────────────────────────────────
@app.route("/api/gastos", methods=["POST"])
@login_required
def adicionar_gasto():
    data = request.json
    cid  = session["cliente_id"]
    conn = get_db()
    conn.execute(
        "INSERT INTO gastos (cliente_id, descricao, valor, categoria, data, fonte) VALUES (?,?,?,?,?,?)",
        (cid, data["descricao"], float(data["valor"]), data["categoria"],
         data.get("data", date.today().isoformat()), data.get("fonte","manual"))
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/gastos/<int:gid>", methods=["DELETE"])
@login_required
def deletar_gasto(gid):
    conn = get_db()
    conn.execute("DELETE FROM gastos WHERE id=? AND cliente_id=?", (gid, session["cliente_id"]))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ── Webhook WhatsApp (Evolution API) ──────────────────────────────────────────
@app.route("/webhook/whatsapp", methods=["POST"])
def webhook_whatsapp():
    """Recebe mensagens da Evolution API e aciona o agente."""
    from agente.agente import processar_mensagem
    import logging
    payload = request.json
    logging.warning(f"WEBHOOK PAYLOAD: {payload}")
    try:
        # Tenta diferentes formatos do payload da Evolution API
        msg = None
        fone = None

        # Formato Evolution Bot
        if payload.get("message"):
            msg = payload.get("message", {}).get("conversation") or \
                  payload.get("message", {}).get("extendedTextMessage", {}).get("text") or \
                  payload.get("message", {}).get("body", "")
            fone = payload.get("remoteJid", "").replace("@s.whatsapp.net", "")

        # Formato webhook padrão
        elif payload.get("data"):
            data = payload["data"]
            msg = data.get("message", {}).get("conversation") or \
                  data.get("message", {}).get("extendedTextMessage", {}).get("text") or \
                  data.get("body", "")
            fone = data.get("key", {}).get("remoteJid", "").replace("@s.whatsapp.net", "")

        # Formato direto
        elif payload.get("body"):
            msg = payload.get("body", "")
            fone = payload.get("from", "").replace("@s.whatsapp.net", "")

        if not msg or not fone:
            logging.warning(f"Payload não reconhecido: {payload}")
            return jsonify({"status": "ignorado"}), 200

        # Ignora mensagens do próprio bot
        if payload.get("fromMe") or payload.get("data", {}).get("key", {}).get("fromMe"):
            return jsonify({"status": "ignorado"}), 200

        resposta = processar_mensagem(fone, msg)
        return jsonify({"status": "ok", "resposta": resposta})
    except Exception as e:
        logging.error(f"Erro webhook: {e}, payload: {payload}")
        return jsonify({"status": "erro", "detalhe": str(e)}), 400

# ── Relatório mensal (acionado por cron ou manualmente) ───────────────────────
@app.route("/relatorio/gerar/<int:cliente_id>")
def gerar_relatorio(cliente_id):
    from relatorio.gerador import gerar_pdf
    mes = request.args.get("mes", date.today().strftime("%Y-%m"))
    caminho = gerar_pdf(cliente_id, mes)
    return jsonify({"arquivo": caminho})

# Inicializa banco ao importar (necessário para gunicorn)
with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
