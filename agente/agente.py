"""
Agente de WhatsApp — interpreta mensagens com Claude e salva gastos no banco.
"""
import os, sys, json, requests
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import get_db

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
EVOLUTION_URL = os.environ.get("EVOLUTION_URL", "http://localhost:8080")
EVOLUTION_KEY = os.environ.get("EVOLUTION_KEY", "")
EVOLUTION_INSTANCE = os.environ.get("EVOLUTION_INSTANCE", "minha-instancia")

CATEGORIAS = ["Alimentação","Transporte","Saúde","Lazer","Moradia","Educação","Roupas","Outros"]

def buscar_cliente_por_fone(fone):
    digits = "".join(c for c in fone if c.isdigit())
    if not digits.startswith("55"):
        digits = "55" + digits

    # Gera variantes com e sem o 9º dígito brasileiro (55 + DDD 2 dig + numero 8 ou 9 dig)
    variantes = [digits]
    if len(digits) == 12:  # sem o 9 extra → tenta adicionar
        variantes.append(digits[:4] + "9" + digits[4:])
    elif len(digits) == 13:  # com o 9 extra → tenta remover
        variantes.append(digits[:4] + digits[5:])

    conn = get_db()
    cliente = None
    for v in variantes:
        cliente = conn.execute(
            "SELECT * FROM clientes WHERE whatsapp = %s", (v,)
        ).fetchone()
        if cliente:
            break
    conn.close()
    return cliente

def salvar_gasto(cliente_id, descricao, valor, categoria, data_gasto):
    conn = get_db()
    conn.execute(
        "INSERT INTO gastos (cliente_id, descricao, valor, categoria, data, fonte) VALUES (%s, %s, %s, %s, %s, %s)",
        (cliente_id, descricao, valor, categoria, data_gasto, "whatsapp")
    )
    conn.commit()
    conn.close()

def deletar_ultimo_gasto(cliente_id):
    conn = get_db()
    ultimo = conn.execute(
        "SELECT id, descricao, valor FROM gastos WHERE cliente_id=%s ORDER BY criado_em DESC LIMIT 1",
        (cliente_id,)
    ).fetchone()
    if not ultimo:
        conn.close()
        return None
    conn.execute("DELETE FROM gastos WHERE id=%s AND cliente_id=%s", (ultimo["id"], cliente_id))
    conn.commit()
    conn.close()
    return dict(ultimo)

def deletar_gasto_por_descricao(cliente_id, descricao, valor=None):
    conn = get_db()
    if valor is not None:
        gasto = conn.execute(
            "SELECT id, descricao, valor FROM gastos WHERE cliente_id=%s AND LOWER(descricao) LIKE LOWER(%s) AND valor=%s ORDER BY criado_em DESC LIMIT 1",
            (cliente_id, f"%{descricao}%", valor)
        ).fetchone()
    else:
        gasto = conn.execute(
            "SELECT id, descricao, valor FROM gastos WHERE cliente_id=%s AND LOWER(descricao) LIKE LOWER(%s) ORDER BY criado_em DESC LIMIT 1",
            (cliente_id, f"%{descricao}%")
        ).fetchone()
    if not gasto:
        conn.close()
        return None
    conn.execute("DELETE FROM gastos WHERE id=%s AND cliente_id=%s", (gasto["id"], cliente_id))
    conn.commit()
    conn.close()
    return dict(gasto)

def resumo_mes(cliente_id):
    mes = date.today().strftime("%Y-%m")
    conn = get_db()
    total = conn.execute(
        "SELECT COALESCE(SUM(valor),0) as t FROM gastos WHERE cliente_id=%s AND data LIKE %s",
        (cliente_id, f"{mes}%")
    ).fetchone()["t"]
    por_cat = conn.execute(
        "SELECT categoria, SUM(valor) as s FROM gastos WHERE cliente_id=%s AND data LIKE %s GROUP BY categoria ORDER BY s DESC",
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
2. Uma EXCLUSÃO do último gasto — ex: "apaga o último", "cancela o último gasto"
3. Uma EXCLUSÃO por descrição — ex: "apaga o mercado", "cancela os 50 reais do uber"
4. Uma CONSULTA de resumo — ex: "quanto gastei?", "resumo do mês"
5. Outra mensagem — responda de forma amigável

Categorias disponíveis: {', '.join(CATEGORIAS)}

Se for um registro, responda APENAS com JSON no formato:
{{"acao": "registrar", "descricao": "...", "valor": 0.00, "categoria": "...", "data": "YYYY-MM-DD"}}

Se for exclusão do último gasto:
{{"acao": "deletar_ultimo"}}

Se for exclusão por descrição (extraia a descrição e opcionalmente o valor):
{{"acao": "deletar", "descricao": "...", "valor": 0.00}}
(omita "valor" se não mencionado)

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

        elif acao == "deletar_ultimo":
            gasto = deletar_ultimo_gasto(cliente["id"])
            if gasto:
                resposta = f"🗑️ Último gasto removido!\n📝 {gasto['descricao']} — R$ {float(gasto['valor']):.2f}"
            else:
                resposta = "Não encontrei nenhum gasto para remover."

        elif acao == "deletar":
            desc = resultado.get("descricao", "")
            valor = resultado.get("valor")
            gasto = deletar_gasto_por_descricao(cliente["id"], desc, float(valor) if valor else None)
            if gasto:
                resposta = f"🗑️ Gasto removido!\n📝 {gasto['descricao']} — R$ {float(gasto['valor']):.2f}"
            else:
                resposta = f"Não encontrei nenhum gasto com '{desc}' para remover."

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
