from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import os, hashlib, secrets, logging
from datetime import datetime, date, timezone, timedelta

def hoje_brasil():
    return datetime.now(timezone(timedelta(hours=-3))).date()
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lembretes (
                id SERIAL PRIMARY KEY,
                cliente_id INTEGER NOT NULL,
                mensagem TEXT NOT NULL,
                hora TEXT NOT NULL,
                data TEXT,
                recorrente BOOLEAN DEFAULT FALSE,
                ativo BOOLEAN DEFAULT TRUE,
                criado_em TIMESTAMP DEFAULT NOW(),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS categorias (
                id SERIAL PRIMARY KEY,
                cliente_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                emoji TEXT DEFAULT '📦',
                criado_em TIMESTAMP DEFAULT NOW(),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id),
                UNIQUE (cliente_id, nome)
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
            CREATE TABLE IF NOT EXISTS lembretes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                mensagem TEXT NOT NULL,
                hora TEXT NOT NULL,
                data TEXT,
                recorrente INTEGER DEFAULT 0,
                ativo INTEGER DEFAULT 1,
                criado_em TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            );
            CREATE TABLE IF NOT EXISTS categorias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                emoji TEXT DEFAULT '📦',
                criado_em TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id),
                UNIQUE (cliente_id, nome)
            );
        """)
    # Adiciona colunas extras se não existirem
    if USE_PG:
        for col in ["reset_token TEXT", "reset_expiry TEXT",
                    "google_access_token TEXT", "google_refresh_token TEXT", "google_token_expiry TEXT",
                    "renda_mensal REAL"]:
            conn.execute(f"ALTER TABLE clientes ADD COLUMN IF NOT EXISTS {col}")
    else:
        for col in ["reset_token TEXT", "reset_expiry TEXT",
                    "google_access_token TEXT", "google_refresh_token TEXT", "google_token_expiry TEXT",
                    "renda_mensal REAL"]:
            try:
                conn.execute(f"ALTER TABLE clientes ADD COLUMN {col}")
            except Exception:
                pass
    conn.commit()

    # Migração: popula categorias padrão para clientes que ainda não têm nenhuma
    CATS_PADRAO = [
        ("Alimentação","🍽️"), ("Transporte","🚗"), ("Saúde","💊"),
        ("Lazer","🎉"), ("Moradia","🏠"), ("Educação","📚"),
        ("Roupas","👕"), ("Outros","📦")
    ]
    try:
        clientes_sem_cat = conn.execute(
            "SELECT id FROM clientes WHERE id NOT IN (SELECT DISTINCT cliente_id FROM categorias)"
        ).fetchall()
        for c in clientes_sem_cat:
            for nome, emoji in CATS_PADRAO:
                try:
                    if USE_PG:
                        conn.execute(
                            "INSERT INTO categorias (cliente_id, nome, emoji) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                            (c["id"], nome, emoji)
                        )
                    else:
                        conn.execute(
                            "INSERT OR IGNORE INTO categorias (cliente_id, nome, emoji) VALUES (?, ?, ?)",
                            (c["id"], nome, emoji)
                        )
                except Exception:
                    pass
        conn.commit()
    except Exception as e:
        import logging as _log; _log.warning(f"[CATS] migração: {e}")

    # Garante plano único sem deletar (evita violação de FK com clientes existentes)
    descricao_plano = "Controle de gastos via WhatsApp com IA + dashboard + relatórios"
    if USE_PG:
        row = conn.execute("SELECT id FROM planos WHERE nome = %s", ("Controla Fácil",)).fetchone()
        if row:
            conn.execute("UPDATE planos SET preco=%s, descricao=%s WHERE nome=%s",
                         (14.90, descricao_plano, "Controla Fácil"))
        else:
            conn.execute("INSERT INTO planos (nome, preco, descricao) VALUES (%s, %s, %s)",
                         ("Controla Fácil", 14.90, descricao_plano))
    else:
        row = conn.execute("SELECT id FROM planos WHERE nome = ?", ("Controla Fácil",)).fetchone()
        if row:
            conn.execute("UPDATE planos SET preco=?, descricao=? WHERE nome=?",
                         (14.90, descricao_plano, "Controla Fácil"))
        else:
            conn.execute("INSERT INTO planos (nome, preco, descricao) VALUES (?, ?, ?)",
                         ("Controla Fácil", 14.90, descricao_plano))
    conn.commit()
    conn.close()

def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

CATS_PADRAO = [
    ("Alimentação","🍽️"), ("Transporte","🚗"), ("Saúde","💊"),
    ("Lazer","🎉"), ("Moradia","🏠"), ("Educação","📚"),
    ("Roupas","👕"), ("Outros","📦")
]

def _popular_categorias_padrao(conn, cliente_id):
    """Insere categorias padrão para um novo cliente."""
    for nome, emoji in CATS_PADRAO:
        try:
            if USE_PG:
                conn.execute(
                    "INSERT INTO categorias (cliente_id, nome, emoji) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (cliente_id, nome, emoji)
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO categorias (cliente_id, nome, emoji) VALUES (?, ?, ?)",
                    (cliente_id, nome, emoji)
                )
        except Exception:
            pass

def enviar_wpp_boas_vindas(whatsapp, nome):
    """Envia mensagem de boas-vindas pelo WhatsApp via Evolution API."""
    import urllib.request, json as _json
    url = os.environ.get("EVOLUTION_URL", "").rstrip("/")
    instance = os.environ.get("EVOLUTION_INSTANCE", "")
    key = os.environ.get("EVOLUTION_KEY", "")
    if not url or not instance or not key:
        logging.warning("[WPP] EVOLUTION_URL/INSTANCE/KEY não configurados")
        return
    numero = "".join(c for c in (whatsapp or "") if c.isdigit())
    if not numero:
        logging.warning("[WPP] Número inválido para boas-vindas")
        return
    mensagem = (
        f"Olá, {nome}! 👋\n\n"
        f"Sou o seu assistente financeiro do *Controla Fácil*! Estou aqui para te ajudar a organizar suas finanças de forma simples.\n\n"
        f"Veja o que você pode me enviar:\n\n"
        f"💬 *Registrar gasto:*\n"
        f"\"Gastei R$50 no mercado\"\n"
        f"\"Paguei R$120 de conta de luz\"\n\n"
        f"🎤 *Mensagem de voz:* é só falar o gasto\n\n"
        f"📸 *Foto de comprovante:* manda a foto que eu leio e registro\n\n"
        f"📊 *Ver resumo:*\n"
        f"\"Quanto gastei esse mês?\"\n"
        f"\"Dashboard\"\n\n"
        f"📅 *Google Agenda:*\n"
        f"\"Agendar dentista sexta às 14h\"\n"
        f"_(conecte sua agenda no painel web primeiro)_\n\n"
        f"Qualquer dúvida é só me perguntar. Vamos começar? 😊"
    )
    payload = _json.dumps({
        "number": numero,
        "text": mensagem,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/message/sendText/{instance}",
        data=payload,
        headers={
            "apikey": key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            logging.info(f"[WPP] Boas-vindas enviado para {numero} — status {resp.status}")
    except Exception as e:
        logging.error(f"[WPP] Falha ao enviar boas-vindas para {numero}: {e}")


def _brevo_post(payload_dict):
    import urllib.request, json as _json
    api_key = os.environ.get("BREVO_API_KEY", "")
    if not api_key:
        raise Exception("BREVO_API_KEY não configurado")
    payload = _json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={"api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status not in (200, 201):
            raise Exception(f"Brevo retornou status {resp.status}")


def enviar_email_boas_vindas(destinatario, nome):
    import json as _json
    sender_email = os.environ.get("BREVO_FROM_EMAIL", "")
    sender_name = os.environ.get("BREVO_FROM_NAME", "Controla Fácil")
    numero_wpp = os.environ.get("WHATSAPP_NUMBER", "")

    html = f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;color:#1a1a1a;">
  <div style="background:#6366f1;padding:32px 24px;border-radius:12px 12px 0 0;text-align:center;">
    <h1 style="color:#fff;margin:0;font-size:24px;">Bem-vindo ao Controla Fácil! 🎉</h1>
  </div>
  <div style="background:#fff;padding:32px 24px;border:1px solid #e5e5e3;border-top:none;border-radius:0 0 12px 12px;">
    <p style="font-size:16px;">Olá, <strong>{nome}</strong>!</p>
    <p style="font-size:15px;color:#444;">Sua conta está ativa. Agora você pode controlar seus gastos direto pelo WhatsApp de forma simples e inteligente.</p>

    <div style="background:#f4f4f2;border-radius:10px;padding:20px 24px;margin:24px 0;">
      <h2 style="font-size:16px;margin:0 0 16px;color:#6366f1;">📱 Como usar pelo WhatsApp</h2>
      <p style="margin:0 0 8px;font-size:14px;color:#444;">Envie mensagens naturais para o nosso número:</p>
      <p style="font-size:18px;font-weight:bold;color:#1a1a1a;margin:0 0 16px;">{numero_wpp if numero_wpp else 'Número enviado em breve'}</p>

      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <tr style="background:#e0e7ff;">
          <th style="padding:8px 12px;text-align:left;border-radius:6px 0 0 0;">O que você diz</th>
          <th style="padding:8px 12px;text-align:left;border-radius:0 6px 0 0;">O que acontece</th>
        </tr>
        <tr style="border-bottom:1px solid #e5e5e3;">
          <td style="padding:10px 12px;color:#333;">"Gastei R$50 no mercado"</td>
          <td style="padding:10px 12px;color:#555;">Registra o gasto automaticamente</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e5e3;">
          <td style="padding:10px 12px;color:#333;">"Gastei R$30 no almoço"</td>
          <td style="padding:10px 12px;color:#555;">Categoriza como Alimentação</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e5e3;">
          <td style="padding:10px 12px;color:#333;">"Quanto gastei esse mês?"</td>
          <td style="padding:10px 12px;color:#555;">Envia resumo completo por categoria</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e5e3;">
          <td style="padding:10px 12px;color:#333;">"Dashboard"</td>
          <td style="padding:10px 12px;color:#555;">Envia gráfico visual dos gastos</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e5e3;">
          <td style="padding:10px 12px;color:#333;">Foto de um comprovante</td>
          <td style="padding:10px 12px;color:#555;">Lê e registra o valor automaticamente</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e5e3;">
          <td style="padding:10px 12px;color:#333;">Mensagem de voz</td>
          <td style="padding:10px 12px;color:#555;">Transcreve e registra o gasto</td>
        </tr>
        <tr>
          <td style="padding:10px 12px;color:#333;">"Agendar dentista sexta às 14h"</td>
          <td style="padding:10px 12px;color:#555;">Cria evento no Google Agenda</td>
        </tr>
      </table>
    </div>

    <div style="background:#eff6ff;border-radius:10px;padding:16px 20px;margin-bottom:16px;">
      <h2 style="font-size:15px;margin:0 0 8px;color:#1e40af;">📅 Google Agenda</h2>
      <p style="font-size:14px;color:#444;margin:0;">Para usar o agendamento, conecte sua conta Google no painel web. Depois é só pedir pelo WhatsApp!</p>
    </div>

    <div style="background:#f0fdf4;border-radius:10px;padding:16px 20px;margin-bottom:24px;">
      <h2 style="font-size:15px;margin:0 0 8px;color:#065f46;">🌐 Painel web</h2>
      <p style="font-size:14px;color:#444;margin:0;">Acesse seu painel completo com gráficos e histórico em <a href="https://controlafacilai.com.br/login" style="color:#6366f1;">controlafacilai.com.br</a></p>
    </div>

    <p style="font-size:14px;color:#888;">Qualquer dúvida, responda este e-mail. Estamos aqui para ajudar!</p>
    <p style="font-size:14px;color:#888;margin-bottom:0;">— Equipe Controla Fácil</p>
  </div>
</div>
"""
    _brevo_post({
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": destinatario, "name": nome}],
        "subject": "Bem-vindo ao Controla Fácil — sua conta está ativa! 🎉",
        "htmlContent": html,
    })
    logging.info(f"[EMAIL] Boas-vindas enviado para {destinatario}")


def enviar_email_reset(destinatario, link):
    sender_email = os.environ.get("BREVO_FROM_EMAIL", "")
    sender_name = os.environ.get("BREVO_FROM_NAME", "Controla Fácil")
    if not sender_email:
        raise Exception("BREVO_FROM_EMAIL nao configurado")
    corpo = (
        f"Olá!\n\n"
        f"Recebemos uma solicitação para redefinir sua senha no Controla Fácil.\n\n"
        f"Clique no link abaixo para criar uma nova senha (válido por 1 hora):\n\n"
        f"{link}\n\n"
        f"Se você não solicitou isso, ignore este e-mail.\n\n"
        f"— Equipe Controla Fácil"
    )
    _brevo_post({
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": destinatario}],
        "subject": "Redefinição de senha — Controla Fácil",
        "textContent": corpo,
    })

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

ADMIN_KEY = os.environ.get("ADMIN_KEY", "controla2024")

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.args.get("key") != ADMIN_KEY and session.get("admin") != True:
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    erro = None
    if request.method == "POST":
        if request.form.get("key") == ADMIN_KEY:
            session["admin"] = True
            return redirect(url_for("admin_painel"))
        erro = "Chave incorreta."
    return render_template("admin_login.html", erro=erro)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))

@app.route("/admin")
@admin_required
def admin_painel():
    conn = get_db()
    clientes = conn.execute("""
        SELECT c.id, c.nome, c.email, c.whatsapp, c.status, c.criado_em,
               c.renda_mensal, c.google_refresh_token,
               p.nome as plano_nome, p.preco,
               COUNT(g.id) as total_gastos,
               COALESCE(SUM(g.valor), 0) as total_gasto_mes
        FROM clientes c
        LEFT JOIN planos p ON c.plano_id = p.id
        LEFT JOIN gastos g ON g.cliente_id = c.id AND g.data LIKE %s
        GROUP BY c.id, c.nome, c.email, c.whatsapp, c.status, c.criado_em,
                 c.renda_mensal, c.google_refresh_token, p.nome, p.preco
        ORDER BY c.criado_em DESC
    """, (hoje_brasil().strftime("%Y-%m") + "%",)).fetchall()
    total_clientes = len(clientes)
    ativos = sum(1 for c in clientes if c["status"] == "ativo")
    receita = sum(float(c["preco"] or 0) for c in clientes if c["status"] == "ativo")
    conn.close()
    return render_template("admin.html",
        clientes=clientes, total_clientes=total_clientes,
        ativos=ativos, receita=receita
    )

@app.route("/admin/ativar/<int:cliente_id>", methods=["POST"])
@admin_required
def admin_ativar(cliente_id):
    conn = get_db()
    cliente = conn.execute("SELECT nome, email, whatsapp, status FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
    conn.execute("UPDATE clientes SET status='ativo' WHERE id=%s", (cliente_id,))
    conn.commit()
    conn.close()
    if cliente and cliente["status"] != "ativo":
        try:
            enviar_email_boas_vindas(cliente["email"], cliente["nome"])
        except Exception as e:
            logging.error(f"[EMAIL] Falha boas-vindas para {cliente['email']}: {e}")
        try:
            enviar_wpp_boas_vindas(cliente["whatsapp"], cliente["nome"])
        except Exception as e:
            logging.error(f"[WPP] Falha boas-vindas para {cliente['whatsapp']}: {e}")
    return redirect(url_for("admin_painel"))

@app.route("/admin/desativar/<int:cliente_id>", methods=["POST"])
@admin_required
def admin_desativar(cliente_id):
    conn = get_db()
    conn.execute("UPDATE clientes SET status='pendente' WHERE id=%s", (cliente_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_painel"))

@app.route("/admin/relatorio/<int:cliente_id>", methods=["POST"])
@admin_required
def admin_relatorio(cliente_id):
    from relatorio.gerador import gerar_e_enviar_pdf_wpp
    conn = get_db()
    cliente = conn.execute("SELECT whatsapp FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
    conn.close()
    mes = hoje_brasil().strftime("%Y-%m")
    try:
        ok = gerar_e_enviar_pdf_wpp(cliente_id, mes, cliente["whatsapp"] if cliente else "")
        return redirect(url_for("admin_painel") + ("?ok=relatorio_enviado" if ok else "?erro=relatorio_falhou"))
    except Exception as e:
        logging.error(f"[RELATORIO] Erro: {e}")
        return redirect(url_for("admin_painel") + "?erro=relatorio_falhou")

@app.route("/admin/cancelar/<int:cliente_id>", methods=["POST"])
@admin_required
def admin_cancelar(cliente_id):
    conn = get_db()
    conn.execute("UPDATE clientes SET status='cancelado' WHERE id=%s", (cliente_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_painel"))

@app.route("/admin/deletar/<int:cliente_id>", methods=["POST"])
@admin_required
def admin_deletar(cliente_id):
    conn = get_db()
    conn.execute("DELETE FROM gastos WHERE cliente_id=%s", (cliente_id,))
    conn.execute("DELETE FROM pagamentos WHERE cliente_id=%s", (cliente_id,))
    conn.execute("DELETE FROM clientes WHERE id=%s", (cliente_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_painel"))

@app.route("/admin/criar-conta", methods=["POST"])
@admin_required
def admin_criar_conta():
    nome     = request.form.get("nome", "").strip()
    email    = request.form.get("email", "").strip().lower()
    senha    = request.form.get("senha", "").strip()
    whatsapp = normalizar_whatsapp(request.form.get("whatsapp", "").strip())
    if not all([nome, email, senha]):
        return redirect(url_for("admin_painel") + "?erro=campos_obrigatorios")
    conn = get_db()
    plano = conn.execute("SELECT id FROM planos LIMIT 1").fetchone()
    plano_id = plano["id"] if plano else None
    try:
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO clientes (nome, email, senha_hash, whatsapp, plano_id, token_acesso, status) VALUES (%s, %s, %s, %s, %s, %s, 'ativo')",
            (nome, email, hash_senha(senha), whatsapp or None, plano_id, token)
        )
        novo = conn.execute("SELECT id FROM clientes WHERE email=%s", (email,)).fetchone()
        if novo:
            _popular_categorias_padrao(conn, novo["id"])
        conn.commit()
    except Exception as e:
        conn.close()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return redirect(url_for("admin_painel") + "?erro=email_duplicado")
        raise
    conn.close()
    try:
        enviar_email_boas_vindas(email, nome)
    except Exception as e:
        logging.error(f"[EMAIL] Falha boas-vindas para {email}: {e}")
    if whatsapp:
        try:
            enviar_wpp_boas_vindas(whatsapp, nome)
        except Exception as e:
            logging.error(f"[WPP] Falha boas-vindas para {whatsapp}: {e}")
    return redirect(url_for("admin_painel") + "?ok=conta_criada")

@app.route("/admin/atualizar_whatsapp/<int:cliente_id>", methods=["POST"])
@admin_required
def admin_atualizar_whatsapp(cliente_id):
    novo = normalizar_whatsapp(request.form.get("whatsapp", "").strip())
    conn = get_db()
    conn.execute("UPDATE clientes SET whatsapp=%s WHERE id=%s", (novo, cliente_id))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_painel"))

@app.route("/privacidade")
def privacidade():
    return render_template("privacidade.html")

@app.route("/termos")
def termos():
    return render_template("termos.html")


def gerar_backup_csv():
    """Exporta clientes e gastos como dois CSVs num ZIP em memória. Retorna bytes."""
    import csv, io, zipfile
    conn = get_db()
    clientes = conn.execute("SELECT id, nome, email, whatsapp, status, criado_em FROM clientes ORDER BY id").fetchall()
    gastos = conn.execute("SELECT id, cliente_id, descricao, valor, categoria, data, fonte, criado_em FROM gastos ORDER BY id").fetchall()
    conn.close()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for nome_arq, rows, cabecalho in [
            ("clientes.csv", clientes, ["id","nome","email","whatsapp","status","criado_em"]),
            ("gastos.csv",   gastos,   ["id","cliente_id","descricao","valor","categoria","data","fonte","criado_em"]),
        ]:
            s = io.StringIO()
            w = csv.writer(s)
            w.writerow(cabecalho)
            for r in rows:
                w.writerow([r[c] for c in cabecalho])
            zf.writestr(nome_arq, s.getvalue())
    buf.seek(0)
    return buf.read()


def enviar_backup_email():
    """Envia backup ZIP por e-mail via Brevo. Chamado manualmente ou por cron."""
    import urllib.request, json as _json, base64
    api_key = os.environ.get("BREVO_API_KEY", "")
    sender_email = os.environ.get("BREVO_FROM_EMAIL", "")
    sender_name = os.environ.get("BREVO_FROM_NAME", "Controla Fácil")
    destino = os.environ.get("BACKUP_EMAIL", sender_email)

    if not api_key or not sender_email or not destino:
        raise Exception("BREVO_API_KEY, BREVO_FROM_EMAIL ou BACKUP_EMAIL não configurado")

    dados = gerar_backup_csv()
    nome_arquivo = f"backup_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"

    payload = _json.dumps({
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": destino}],
        "subject": f"Backup Controla Fácil — {datetime.now().strftime('%d/%m/%Y')}",
        "textContent": f"Backup automático gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}.\nAnexo: {nome_arquivo}",
        "attachment": [{
            "name": nome_arquivo,
            "content": base64.b64encode(dados).decode("utf-8"),
        }],
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
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status not in (200, 201):
            raise Exception(f"Brevo retornou status {resp.status}")
    logging.info(f"[BACKUP] Enviado para {destino} — {len(dados)} bytes")


@app.route("/admin/backup", methods=["POST"])
@admin_required
def admin_backup():
    try:
        enviar_backup_email()
        return redirect(url_for("admin_painel") + "?ok=backup_enviado")
    except Exception as e:
        logging.error(f"[BACKUP] Erro: {e}")
        return redirect(url_for("admin_painel") + "?erro=backup_falhou")


@app.route("/cron/backup")
def cron_backup():
    """Endpoint para cron job diário (Railway Cron ou UptimeRobot). Protegido por token."""
    token = request.args.get("token", "")
    esperado = os.environ.get("CRON_SECRET", "")
    if not esperado or token != esperado:
        return jsonify({"erro": "não autorizado"}), 403
    try:
        enviar_backup_email()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logging.error(f"[BACKUP] Cron erro: {e}")
        return jsonify({"status": "erro", "msg": str(e)}), 500


@app.route("/health")
def health():
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        return jsonify({"status": "ok", "db": "ok"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "db": str(e)}), 500

@app.route("/")
def index():
    conn = get_db()
    planos = conn.execute("SELECT * FROM planos WHERE nome = %s" if USE_PG else "SELECT * FROM planos WHERE nome = ?", ("Controla Fácil",)).fetchall()
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
            # Verifica variantes do número (com e sem o 9º dígito)
            wpp_variantes = [whatsapp]
            if len(whatsapp) == 12:
                wpp_variantes.append(whatsapp[:4] + "9" + whatsapp[4:])
            elif len(whatsapp) == 13:
                wpp_variantes.append(whatsapp[:4] + whatsapp[5:])
            wpp_existente = None
            for v in wpp_variantes:
                wpp_existente = conn.execute("SELECT id FROM clientes WHERE whatsapp=%s", (v,)).fetchone()
                if wpp_existente:
                    break
            if wpp_existente:
                conn.close()
                return render_template("cadastro.html", erro="Esse WhatsApp já está cadastrado. Se é seu, use a recuperação de senha para acessar sua conta.")
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
    planos = conn.execute("SELECT * FROM planos WHERE nome = %s" if USE_PG else "SELECT * FROM planos WHERE nome = ?", ("Controla Fácil",)).fetchall()
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
                            try:
                                enviar_email_boas_vindas(cliente["email"], cliente["nome"])
                            except Exception as e:
                                logging.error(f"[EMAIL] Boas-vindas pós-pagamento: {e}")
                            try:
                                enviar_wpp_boas_vindas(cliente["whatsapp"], cliente["nome"])
                            except Exception as e:
                                logging.error(f"[WPP] Boas-vindas pós-pagamento: {e}")
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
    import json as _json, calendar as _cal, logging as _log
    from datetime import date as _date
    cid = session["cliente_id"]
    hoje = hoje_brasil()

    # Permite navegar por mês via ?mes=YYYY-MM
    mes_param = request.args.get("mes", "")
    try:
        ano, mnum = [int(x) for x in mes_param.split("-")]
        mes_dt = _date(ano, mnum, 1)
    except Exception:
        mes_dt = _date(hoje.year, hoje.month, 1)
    mes = mes_dt.strftime("%Y-%m")

    # Mês anterior e próximo para navegação
    if mes_dt.month == 1:
        mes_ant = _date(mes_dt.year - 1, 12, 1).strftime("%Y-%m")
    else:
        mes_ant = _date(mes_dt.year, mes_dt.month - 1, 1).strftime("%Y-%m")
    if mes_dt.month == 12:
        mes_prox = _date(mes_dt.year + 1, 1, 1).strftime("%Y-%m")
    else:
        mes_prox = _date(mes_dt.year, mes_dt.month + 1, 1).strftime("%Y-%m")

    mes_atual = hoje.strftime("%Y-%m")
    is_mes_atual = (mes == mes_atual)

    conn = get_db()
    gastos = conn.execute(
        "SELECT * FROM gastos WHERE cliente_id=%s AND data LIKE %s ORDER BY data DESC",
        (cid, f"{mes}%")
    ).fetchall()
    _log.warning(f"[DASHBOARD] cliente_id={cid} mes={mes} gastos_encontrados={len(gastos)}")
    total = conn.execute(
        "SELECT COALESCE(SUM(valor),0) as t FROM gastos WHERE cliente_id=%s AND data LIKE %s",
        (cid, f"{mes}%")
    ).fetchone()["t"]
    por_cat = conn.execute(
        "SELECT categoria, SUM(valor) as total FROM gastos WHERE cliente_id=%s AND data LIKE %s GROUP BY categoria ORDER BY total DESC",
        (cid, f"{mes}%")
    ).fetchall()
    por_dia_rows = conn.execute(
        "SELECT data, SUM(valor) as total FROM gastos WHERE cliente_id=%s AND data LIKE %s GROUP BY data ORDER BY data",
        (cid, f"{mes}%")
    ).fetchall()
    cliente = conn.execute("SELECT * FROM clientes WHERE id=%s", (cid,)).fetchone()
    cats_usuario = conn.execute(
        "SELECT nome, emoji FROM categorias WHERE cliente_id=%s ORDER BY nome", (cid,)
    ).fetchall()
    conn.close()

    # Série acumulada por dia
    dias_no_mes = _cal.monthrange(mes_dt.year, mes_dt.month)[1]
    ultimo_dia = hoje.day if is_mes_atual else dias_no_mes
    gastos_por_dia = {r["data"]: float(r["total"]) for r in por_dia_rows}
    labels_dias = [str(d) for d in range(1, ultimo_dia + 1)]
    serie_diaria = []
    acumulado = 0
    for d in range(1, ultimo_dia + 1):
        key = f"{mes}-{d:02d}"
        acumulado += gastos_por_dia.get(key, 0)
        serie_diaria.append(round(acumulado, 2))

    renda = float(cliente["renda_mensal"]) if cliente["renda_mensal"] else None
    saldo = round(renda - float(total), 2) if renda else None

    from agente.agente import MESES_PT
    mes_nome = f"{MESES_PT[mes_dt.month]} {mes_dt.year}"

    return render_template("dashboard.html",
        gastos=gastos, total=float(total), por_cat=por_cat,
        cliente=cliente, mes=mes, mes_nome=mes_nome,
        renda=renda, saldo=saldo,
        labels_dias=_json.dumps(labels_dias),
        serie_diaria=_json.dumps(serie_diaria),
        cats_labels=_json.dumps([r["categoria"] for r in por_cat]),
        cats_valores=_json.dumps([float(r["total"]) for r in por_cat]),
        mes_ant=mes_ant, mes_prox=mes_prox,
        is_mes_atual=is_mes_atual,
        cats_usuario=cats_usuario,
    )

@app.route("/debug/session")
@login_required
def debug_session():
    cid = session["cliente_id"]
    conn = get_db()
    cliente = conn.execute("SELECT id, nome, email, whatsapp, status FROM clientes WHERE id=%s", (cid,)).fetchone()
    gastos_todos = conn.execute(
        "SELECT id, descricao, valor, categoria, data, fonte, criado_em FROM gastos WHERE cliente_id=%s ORDER BY criado_em DESC LIMIT 20",
        (cid,)
    ).fetchall()
    conn.close()
    resultado = {
        "session_cliente_id": cid,
        "cliente": dict(cliente) if cliente else None,
        "gastos_recentes": [dict(g) for g in gastos_todos]
    }
    return jsonify(resultado)

@app.route("/perfil/whatsapp", methods=["POST"])
@login_required
def atualizar_whatsapp():
    novo = normalizar_whatsapp(request.form.get("whatsapp", "").strip())
    if len(novo) < 10:
        return redirect(url_for("dashboard") + "?wpp_erro=numero_invalido")
    cid = session["cliente_id"]
    conn = get_db()
    existente = conn.execute(
        "SELECT id FROM clientes WHERE whatsapp=%s AND id != %s", (novo, cid)
    ).fetchone()
    if existente:
        conn.close()
        return redirect(url_for("dashboard") + "?wpp_erro=ja_cadastrado")
    conn.execute("UPDATE clientes SET whatsapp=%s WHERE id=%s", (novo, cid))
    conn.commit()
    conn.close()
    return redirect(url_for("dashboard") + "?wpp_ok=1")

@app.route("/assinatura")
@login_required
def assinatura():
    cid = session["cliente_id"]
    conn = get_db()
    cliente = conn.execute("""
        SELECT c.*, p.nome as plano_nome, p.preco, p.descricao as plano_desc
        FROM clientes c LEFT JOIN planos p ON c.plano_id = p.id
        WHERE c.id = %s
    """, (cid,)).fetchone()
    pagamentos = conn.execute(
        "SELECT * FROM pagamentos WHERE cliente_id=%s ORDER BY criado_em DESC LIMIT 5",
        (cid,)
    ).fetchall()
    conn.close()
    return render_template("assinatura.html", cliente=cliente, pagamentos=pagamentos)

@app.route("/cancelar-assinatura", methods=["POST"])
@login_required
def cancelar_assinatura():
    cid = session["cliente_id"]
    conn = get_db()
    conn.execute("UPDATE clientes SET status='cancelado' WHERE id=%s", (cid,))
    conn.commit()
    conn.close()
    session.clear()
    return redirect(url_for("index") + "?cancelado=1")

@app.route("/api/gastos", methods=["POST"])
@login_required
def adicionar_gasto():
    data = request.json
    cid  = session["cliente_id"]
    conn = get_db()
    conn.execute(
        "INSERT INTO gastos (cliente_id, descricao, valor, categoria, data, fonte) VALUES (%s, %s, %s, %s, %s, %s)",
        (cid, data["descricao"], float(data["valor"]), data["categoria"],
         data.get("data", hoje_brasil().isoformat()), data.get("fonte", "manual"))
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
    mes = hoje_brasil().strftime("%Y-%m")
    conn = get_db()
    conn.execute("DELETE FROM gastos WHERE cliente_id=%s AND data LIKE %s", (session["cliente_id"], f"{mes}%"))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/categorias", methods=["GET"])
@login_required
def listar_categorias():
    cid = session["cliente_id"]
    conn = get_db()
    cats = conn.execute(
        "SELECT nome, emoji FROM categorias WHERE cliente_id=%s ORDER BY nome", (cid,)
    ).fetchall()
    conn.close()
    return jsonify([{"nome": c["nome"], "emoji": c["emoji"]} for c in cats])

@app.route("/api/categorias", methods=["POST"])
@login_required
def adicionar_categoria():
    cid = session["cliente_id"]
    data = request.json or {}
    nome = (data.get("nome") or "").strip()
    emoji = (data.get("emoji") or "📦").strip() or "📦"
    if not nome:
        return jsonify({"erro": "Nome obrigatório"}), 400
    if len(nome) > 40:
        return jsonify({"erro": "Nome muito longo"}), 400
    conn = get_db()
    try:
        if USE_PG:
            conn.execute(
                "INSERT INTO categorias (cliente_id, nome, emoji) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (cid, nome, emoji)
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO categorias (cliente_id, nome, emoji) VALUES (?, ?, ?)",
                (cid, nome, emoji)
            )
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"erro": str(e)}), 500
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/categorias/<nome>", methods=["DELETE"])
@login_required
def deletar_categoria(nome):
    cid = session["cliente_id"]
    conn = get_db()
    # Não permite deletar se houver gastos com essa categoria neste mês
    em_uso = conn.execute(
        "SELECT COUNT(*) as n FROM gastos WHERE cliente_id=%s AND categoria=%s", (cid, nome)
    ).fetchone()
    if em_uso and em_uso["n"] > 0:
        conn.close()
        return jsonify({"erro": f"Categoria em uso em {em_uso['n']} gasto(s). Altere os gastos antes de remover."}), 400
    conn.execute("DELETE FROM categorias WHERE cliente_id=%s AND nome=%s", (cid, nome))
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

@app.route("/agenda/conectar/<int:cliente_id>")
def agenda_conectar(cliente_id):
    import urllib.parse
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI", "")
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar.events",
        "access_type": "offline",
        "prompt": "consent",
        "state": str(cliente_id)
    })
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")

@app.route("/agenda/callback")
def agenda_callback():
    import urllib.request, urllib.parse, json as _json
    code = request.args.get("code", "")
    state = request.args.get("state", "")
    try:
        cliente_id = int(state)
    except ValueError:
        return "Estado inválido.", 400
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI", "")
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            tokens = _json.loads(resp.read())
    except Exception as e:
        logging.error(f"Erro ao trocar token Google: {e}", exc_info=True)
        return "Erro ao conectar agenda. Tente novamente.", 500
    conn = get_db()
    conn.execute(
        "UPDATE clientes SET google_access_token=%s, google_refresh_token=%s WHERE id=%s",
        (tokens.get("access_token"), tokens.get("refresh_token"), cliente_id)
    )
    conn.commit()
    conn.close()
    return render_template("agenda_conectada.html")

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

def _buscar_midia_evolution(msg_id, remote_jid):
    """Busca base64 de qualquer mídia (imagem, áudio, documento) via Evolution API."""
    import requests as _req
    ev_url = os.environ.get("EVOLUTION_URL", "")
    ev_key = os.environ.get("EVOLUTION_KEY", "")
    ev_inst = os.environ.get("EVOLUTION_INSTANCE", "")
    if not ev_url or not msg_id:
        return None
    try:
        r = _req.post(
            f"{ev_url}/chat/getBase64FromMediaMessage/{ev_inst}",
            headers={"apikey": ev_key, "Content-Type": "application/json"},
            json={"message": {"key": {"id": msg_id, "remoteJid": remote_jid}}},
            timeout=20
        )
        logging.warning(f"[MIDIA] Evolution getBase64 status={r.status_code} body={r.text[:200]}")
        if r.status_code in (200, 201):
            data = r.json()
            return data.get("base64") or data.get("data")
    except Exception as e:
        logging.warning(f"Falha ao buscar mídia via Evolution API: {e}")
    return None

def _extrair_audio_b64(payload):
    """Tenta extrair áudio em base64 do payload do webhook via Evolution API."""
    import base64 as _b64
    data = payload.get("data", {})
    msg = data.get("message", {})
    audio_msg = msg.get("audioMessage") or msg.get("pttMessage")
    if not audio_msg:
        return None, None
    mime_type = audio_msg.get("mimetype", "audio/ogg")
    remote_jid = data.get("key", {}).get("remoteJid", "")
    msg_id = data.get("key", {}).get("id", "")
    b64 = _buscar_midia_evolution(msg_id, remote_jid)
    if b64:
        return b64, mime_type
    return None, None

def _extrair_imagem_b64_evolution(payload):
    """Extrai imagem de payload da Evolution API usando getBase64FromMediaMessage."""
    import base64 as _b64, requests as _req
    data = payload.get("data", {})
    msg = data.get("message", {})
    img_msg = msg.get("imageMessage")
    if not img_msg:
        return None, ""
    caption = img_msg.get("caption", "")
    remote_jid = data.get("key", {}).get("remoteJid", "")
    msg_id = data.get("key", {}).get("id", "")
    b64 = _buscar_midia_evolution(msg_id, remote_jid)
    return b64, caption

@app.route("/webhook/whatsapp", methods=["POST"])
def webhook_whatsapp():
    from agente.agente import processar_mensagem, processar_imagem, processar_audio
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
            # Detecta áudio no formato inputs: query = "audioMessage|<messageId>"
            if msg and msg.startswith("audioMessage|"):
                msg_id = msg.split("|", 1)[1]
                # Usa dados do próprio payload quando disponíveis
                ev_url = inputs.get("serverUrl") or os.environ.get("EVOLUTION_URL", "")
                ev_key = inputs.get("apiKey") or os.environ.get("EVOLUTION_KEY", "")
                ev_inst = inputs.get("instanceName") or os.environ.get("EVOLUTION_INSTANCE", "")
                remote_jid = inputs.get("remoteJid") or (fone + "@s.whatsapp.net")
                import requests as _req
                try:
                    r = _req.post(
                        f"{ev_url}/chat/getBase64FromMediaMessage/{ev_inst}",
                        headers={"apikey": ev_key, "Content-Type": "application/json"},
                        json={"message": {"key": {"id": msg_id, "remoteJid": remote_jid}}},
                        timeout=20
                    )
                    logging.warning(f"[AUDIO] Evolution response {r.status_code}: {r.text[:200]}")
                    if r.status_code in (200, 201):
                        audio_b64 = r.json().get("base64") or r.json().get("data")
                        if audio_b64 and fone:
                            resposta = processar_audio(fone, audio_b64, "audio/ogg")
                            return jsonify({"output": resposta, "status": "ok"})
                except Exception as e:
                    logging.error(f"Erro ao buscar áudio inputs: {e}")
                return jsonify({"output": "Não consegui processar o áudio. Tente em texto.", "status": "ok"}), 200
            # Detecta imagem no formato inputs: query = "imageMessage|<messageId>"
            if msg and msg.startswith("imageMessage|"):
                msg_id = msg.split("|", 1)[1]
                ev_url = inputs.get("serverUrl") or os.environ.get("EVOLUTION_URL", "")
                ev_key = inputs.get("apiKey") or os.environ.get("EVOLUTION_KEY", "")
                ev_inst = inputs.get("instanceName") or os.environ.get("EVOLUTION_INSTANCE", "")
                remote_jid = inputs.get("remoteJid") or (fone + "@s.whatsapp.net")
                caption = inputs.get("caption") or inputs.get("text") or ""
                import requests as _req2
                try:
                    r2 = _req2.post(
                        f"{ev_url}/chat/getBase64FromMediaMessage/{ev_inst}",
                        headers={"apikey": ev_key, "Content-Type": "application/json"},
                        json={"message": {"key": {"id": msg_id, "remoteJid": remote_jid}}},
                        timeout=20
                    )
                    logging.warning(f"[IMAGEM] Evolution response {r2.status_code}: {r2.text[:200]}")
                    if r2.status_code in (200, 201):
                        img_b64 = r2.json().get("base64") or r2.json().get("data")
                        if img_b64 and fone:
                            resposta = processar_imagem(fone, img_b64, caption)
                            return jsonify({"output": resposta, "status": "ok"})
                except Exception as e:
                    logging.error(f"Erro ao buscar imagem inputs: {e}")
                return jsonify({"output": "Não consegui processar a imagem. Tente descrever o valor em texto.", "status": "ok"}), 200
            imagem_b64 = _extrair_imagem_b64(payload, inputs)
        elif payload.get("query"):
            msg = payload.get("query", "")
            fone = payload.get("remoteJid", "").replace("@s.whatsapp.net", "") or \
                   payload.get("user", "").replace("@s.whatsapp.net", "")
            imagem_b64 = _extrair_imagem_b64(payload, {})
        elif payload.get("data"):
            data = payload["data"]
            fone = data.get("key", {}).get("remoteJid", "").replace("@s.whatsapp.net", "")
            # Detecta áudio
            audio_b64, audio_mime = _extrair_audio_b64(payload)
            if audio_b64:
                if fone:
                    resposta = processar_audio(fone, audio_b64, audio_mime)
                    return jsonify({"output": resposta, "status": "ok"})
            # Detecta imagem via Evolution API
            imagem_b64, caption_img = _extrair_imagem_b64_evolution(payload)
            if imagem_b64:
                if fone:
                    resposta = processar_imagem(fone, imagem_b64, caption_img)
                    return jsonify({"output": resposta, "status": "ok"})
            # Mensagem de texto normal
            msg = data.get("message", {}).get("conversation") or \
                  data.get("message", {}).get("extendedTextMessage", {}).get("text") or \
                  data.get("body", "")
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



@app.route("/relatorio/gerar/<int:cliente_id>")
def gerar_relatorio(cliente_id):
    from relatorio.gerador import gerar_pdf
    mes = request.args.get("mes", hoje_brasil().strftime("%Y-%m"))
    caminho = gerar_pdf(cliente_id, mes)
    return jsonify({"arquivo": caminho})

with app.app_context():
    init_db()

# ── THREAD DE LEMBRETES ──────────────────────────────────────────────────────
def _verificar_lembretes():
    """Roda em background, verifica lembretes a cada minuto e envia via WhatsApp."""
    import time as _time
    _time.sleep(10)  # aguarda app subir
    while True:
        try:
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            agora = _dt.now(_tz(_td(hours=-3)))
            hora_atual = agora.strftime("%H:%M")
            data_atual = agora.strftime("%Y-%m-%d")
            with app.app_context():
                conn = get_db()
                ph = "%s" if USE_PG else "?"
                lembretes = conn.execute(f"""
                    SELECT l.id, l.mensagem, l.hora, l.recorrente,
                           c.whatsapp, c.nome
                    FROM lembretes l
                    JOIN clientes c ON l.cliente_id = c.id
                    WHERE l.ativo = {'true' if USE_PG else '1'}
                      AND l.hora = {ph}
                      AND (l.data = {ph} OR l.recorrente = {'true' if USE_PG else '1'})
                      AND c.status = 'ativo'
                """, (hora_atual, data_atual)).fetchall()
                for lem in lembretes:
                    try:
                        from agente.agente import enviar_whatsapp
                        enviar_whatsapp(lem["whatsapp"],
                            f"⏰ *Lembrete:* {lem['mensagem']}")
                        if not lem["recorrente"]:
                            conn.execute(f"UPDATE lembretes SET ativo = {'false' if USE_PG else '0'} WHERE id = {ph}", (lem["id"],))
                            conn.commit()
                        logging.info(f"[LEMBRETE] Enviado para {lem['whatsapp']}: {lem['mensagem']}")
                    except Exception as e:
                        logging.error(f"[LEMBRETE] Erro ao enviar: {e}")
                conn.close()
        except Exception as e:
            logging.error(f"[LEMBRETE] Erro no loop: {e}")
        import time as _time
        _time.sleep(60)

import threading as _threading
_t = _threading.Thread(target=_verificar_lembretes, daemon=True)
_t.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
