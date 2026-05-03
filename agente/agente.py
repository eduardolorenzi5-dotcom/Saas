"""
Agente de WhatsApp — interpreta mensagens com Claude e salva gastos no banco.
"""
import os, sqlite3, json, requests
from datetime import date

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "gastos.db")
EVOLUTION_URL = os.environ.get("EVOLUTION_URL", "http://localhost:8080")
EVOLUTION_KEY = os.environ.get("EVOLUTION_KEY", "")
EVOLUTION_INSTANCE = os.environ.get("EVOLUTION_INSTANCE", "minha-instancia")

CATEGORIAS = ["Alimentação","Transporte","Saúde","Lazer","Moradia","Educação","Roupas","Outros"]

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def buscar_cliente_por_fone(fone):
    fone_limpo = fone.replace("+","").replace("-","").replace(" ","").replace("(","").replace(")","")
    conn = get_db()
    cliente = conn.execute(
        "SELECT * FROM clientes WHERE REPLACE(REPLACE(REPLACE(whatsapp,'-',''),'(',''),')','') LIKE ?",
        (f"%{fone_limpo[-8:]}",)
    ).fetchone()
    conn.close()
    return cliente

def salvar_gasto(cliente_id, descricao, valor, categoria, data_gasto):
    conn = get_db()
    conn.execute(
        "INSERT INTO gastos (cliente_id, descricao, valor, categoria, data, fonte) VALUES (?,?,?,?,?,?)",
        (cliente_id, descricao, valor, categoria, data_gasto, "whatsapp")
    )
    conn.commit()
    conn.close()

def resumo_mes(cliente_id):
    mes = date.today().strftime("%Y-%m")
    conn = get_db()
    total = conn.execute(
        "SELECT COALESCE(SUM(valor),0) as t FROM gastos WHERE cliente_id=? AND data LIKE ?",
        (cliente_id, f"{mes}%")
    ).fetchone()["t"]
    por_cat = conn.execute(
        "SELECT categoria, SUM(valor) as s FROM gastos WHERE cliente_id=? AND data LIKE ? GROUP BY categoria ORDER BY s DESC",
        (cliente_id, f"{mes}%")
    ).fetchall()
    conn.close()
    return total, [dict(r) for r in por_cat]

def chamar_claude(mensagem, historico=[]):
    """Chama a API do Claude para interpretar a mensagem."""
    system = f"""Você é um assistente financeiro amigável via WhatsApp.
Seu papel é ajudar o usuário a registrar gastos e consultar o resumo financeiro.

Ao receber uma mensagem, identifique se é:
1. Um REGISTRO de gasto — extraia: descricao, valor (número), categoria, data
2. Uma CONSULTA de resumo — responda com "RESUMO"
3. Outra mensagem — responda de forma amigável

Categorias disponíveis: {', '.join(CATEGORIAS)}

Se for um registro, responda APENAS com JSON no formato:
{{"acao": "registrar", "descricao": "...", "valor": 0.00, "categoria": "...", "data": "YYYY-MM-DD"}}

Se for consulta de resumo, responda:
{{"acao": "resumo"}}

Para outras mensagens:
{{"acao": "mensagem", "texto": "sua resposta aqui"}}

Data de hoje: {date.today().isoformat()}
Responda sempre em português. Seja breve e amigável."""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 500,
        "system": system,
        "messages": [{"role": "user", "content": mensagem}]
    }
    res = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=15)
    res.raise_for_status()
    texto = res.json()["content"][0]["text"].strip()
    # Limpa possíveis backticks
    texto = texto.replace("```json","").replace("```","").strip()
    return json.loads(texto)

def enviar_whatsapp(fone, mensagem):
    """Envia mensagem de resposta via Evolution API."""
    if not EVOLUTION_KEY:
        print(f"[WPP → {fone}] {mensagem}")
        return
    url = f"{EVOLUTION_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    headers = {"apikey": EVOLUTION_KEY, "Content-Type": "application/json"}
    body = {"number": fone, "text": mensagem}
    requests.post(url, headers=headers, json=body, timeout=10)

def processar_mensagem(fone, mensagem):
    """Função principal chamada pelo webhook."""
    cliente = buscar_cliente_por_fone(fone)
    if not cliente:
        enviar_whatsapp(fone, "Olá! Não encontrei sua conta. Cadastre-se no Controla Fácil para começar.")
        return "cliente não encontrado"

    if cliente["status"] != "ativo":
        enviar_whatsapp(fone, "Sua conta ainda não está ativa. Conclua o pagamento no Controla Fácil.")
        return "conta inativa"

    try:
        resultado = chamar_claude(mensagem)
        acao = resultado.get("acao")

        if acao == "registrar":
            salvar_gasto(
                cliente["id"],
                resultado["descricao"],
                float(resultado["valor"]),
                resultado["categoria"],
                resultado.get("data", date.today().isoformat())
            )
            resposta = (
                f"✅ Registrado!\n"
                f"📝 {resultado['descricao']}\n"
                f"💰 R$ {float(resultado['valor']):.2f}\n"
                f"📂 {resultado['categoria']}\n"
                f"📅 {resultado.get('data', date.today().isoformat())}"
            )

        elif acao == "resumo":
            total, por_cat = resumo_mes(cliente["id"])
            mes_nome = date.today().strftime("%B/%Y")
            linhas = [f"📊 *Resumo de {mes_nome}*", f"💰 Total: R$ {total:.2f}", ""]
            for c in por_cat:
                linhas.append(f"  • {c['categoria']}: R$ {c['s']:.2f}")
            resposta = "\n".join(linhas)

        else:
            resposta = resultado.get("texto", "Como posso te ajudar?")

    except Exception as e:
        import logging, traceback
        logging.error(f"Erro agente: {e}\n{traceback.format_exc()}")
        resposta = "Desculpe, não consegui processar sua mensagem. Tente novamente."

    enviar_whatsapp(fone, resposta)
    return resposta
