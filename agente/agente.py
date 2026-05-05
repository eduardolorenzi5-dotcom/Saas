"""
Agente de WhatsApp — interpreta mensagens com Claude e salva gastos no banco.
"""
import os, sys, json, requests
from datetime import date, datetime, timezone, timedelta

def hoje_brasil():
    """Retorna a data atual no fuso horário de Brasília (UTC-3)."""
    return datetime.now(timezone(timedelta(hours=-3))).date()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import get_db

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
EVOLUTION_URL = os.environ.get("EVOLUTION_URL", "http://localhost:8080")
EVOLUTION_KEY = os.environ.get("EVOLUTION_KEY", "")
EVOLUTION_INSTANCE = os.environ.get("EVOLUTION_INSTANCE", "minha-instancia")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
APP_URL = os.environ.get("APP_URL", "https://saas-production-2a7a.up.railway.app")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

CATEGORIAS = ["Alimentação","Transporte","Saúde","Lazer","Moradia","Educação","Roupas","Outros"]

MESES_PT = {
    1:"Janeiro",2:"Fevereiro",3:"Março",4:"Abril",
    5:"Maio",6:"Junho",7:"Julho",8:"Agosto",
    9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro"
}

def mes_ano_pt(d=None):
    if d is None:
        d = hoje_brasil()
    return f"{MESES_PT[d.month]}/{d.year}"

def formatar_data(data_iso):
    """Converte YYYY-MM-DD para DD/MM/YYYY."""
    try:
        y, m, dia = data_iso.split("-")
        return f"{dia}/{m}/{y}"
    except Exception:
        return data_iso

def buscar_cliente_por_fone(fone):
    import logging
    digits = "".join(c for c in fone if c.isdigit())
    if not digits.startswith("55"):
        digits = "55" + digits

    # Gera variantes com e sem o 9º dígito brasileiro (55 + DDD 2 dig + numero 8 ou 9 dig)
    variantes = [digits]
    if len(digits) == 12:  # sem o 9 extra → tenta adicionar
        variantes.append(digits[:4] + "9" + digits[4:])
    elif len(digits) == 13:  # com o 9 extra → tenta remover
        variantes.append(digits[:4] + digits[5:])

    logging.warning(f"[BUSCA_CLIENTE] fone_raw={fone!r} variantes={variantes}")

    conn = get_db()
    cliente = None
    for v in variantes:
        cliente = conn.execute(
            "SELECT * FROM clientes WHERE whatsapp = %s", (v,)
        ).fetchone()
        if cliente:
            break

    # Fallback: busca parcial pelo sufixo do número (últimos 8 dígitos)
    if not cliente and len(digits) >= 8:
        sufixo = digits[-8:]
        cliente = conn.execute(
            "SELECT * FROM clientes WHERE whatsapp LIKE %s", (f"%{sufixo}",)
        ).fetchone()
        if cliente:
            logging.warning(f"[BUSCA_CLIENTE] encontrado via sufixo {sufixo!r}: id={cliente['id']} whatsapp={cliente['whatsapp']!r}")

    if cliente:
        logging.warning(f"[BUSCA_CLIENTE] cliente encontrado: id={cliente['id']} whatsapp={cliente['whatsapp']!r}")
    else:
        logging.warning(f"[BUSCA_CLIENTE] cliente NAO encontrado para variantes={variantes}")

    conn.close()
    return cliente

def salvar_gasto(cliente_id, descricao, valor, categoria, data_gasto):
    import logging
    logging.warning(f"[SALVAR_GASTO] cliente_id={cliente_id} descricao={descricao!r} valor={valor} data={data_gasto!r}")
    conn = get_db()
    conn.execute(
        "INSERT INTO gastos (cliente_id, descricao, valor, categoria, data, fonte) VALUES (%s, %s, %s, %s, %s, %s)",
        (cliente_id, descricao, valor, categoria, data_gasto, "whatsapp")
    )
    conn.commit()
    conn.close()
    logging.warning(f"[SALVAR_GASTO] OK - gasto salvo para cliente_id={cliente_id}")

def deletar_todos_gastos(cliente_id, mes=None):
    conn = get_db()
    if mes:
        conn.execute("DELETE FROM gastos WHERE cliente_id=%s AND data LIKE %s", (cliente_id, f"{mes}%"))
    else:
        conn.execute("DELETE FROM gastos WHERE cliente_id=%s", (cliente_id,))
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

def historico_gastos(cliente_id):
    from datetime import timedelta
    hoje = hoje_brasil()
    tres_meses_atras = (hoje.replace(day=1) - timedelta(days=1)).replace(day=1) - timedelta(days=1)
    tres_meses_atras = tres_meses_atras.replace(day=1)
    conn = get_db()
    gastos = conn.execute(
        "SELECT descricao, valor, categoria, data FROM gastos WHERE cliente_id=%s AND data >= %s ORDER BY data DESC",
        (cliente_id, tres_meses_atras.isoformat())
    ).fetchall()
    conn.close()
    return [dict(g) for g in gastos]

def resumo_mes(cliente_id):
    mes = hoje_brasil().strftime("%Y-%m")
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

def gerar_analise_financeira(gastos):
    if not gastos:
        return "Ainda não tenho gastos suficientes para fazer uma análise. Continue registrando seus gastos!"

    linhas_gastos = "\n".join(
        f"- {g['data']}: {g['descricao']} | R$ {float(g['valor']):.2f} | {g['categoria']}"
        for g in gastos
    )
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 800,
        "system": f"""Você é um consultor financeiro pessoal via WhatsApp. Analise os gastos do cliente e forneça insights práticos e personalizados.

Baseado nos dados, responda em português, de forma amigável e direta (máximo 300 palavras), incluindo:
1. 📊 Onde está gastando mais (top 2-3 categorias)
2. ⚠️ O que precisa economizar (identifique padrões preocupantes)
3. 📈 Tendência para a próxima semana (baseado na frequência e padrão dos gastos)
4. 💡 1 dica prática e personalizada

Hoje: {hoje_brasil().isoformat()}
Use emojis para deixar a mensagem mais visual. Seja específico com os valores.""",
        "messages": [{"role": "user", "content": f"Meus gastos dos últimos meses:\n{linhas_gastos}"}]
    }
    res = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=20)
    res.raise_for_status()
    return res.json()["content"][0]["text"].strip()

def salvar_renda(cliente_id, valor):
    conn = get_db()
    conn.execute("UPDATE clientes SET renda_mensal=%s WHERE id=%s", (valor, cliente_id))
    conn.commit()
    conn.close()

def verificar_agenda_conectada(cliente_id):
    conn = get_db()
    row = conn.execute("SELECT google_refresh_token FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
    conn.close()
    return bool(row and row["google_refresh_token"])

def gerar_link_agenda(cliente_id):
    return f"{APP_URL}/agenda/conectar/{cliente_id}"

CORES_AGENDA = {
    "lavanda": "1", "lavender": "1",
    "verde": "2", "sage": "2", "salvia": "2",
    "roxo": "3", "uva": "3", "grape": "3",
    "rosa": "4", "flamingo": "4",
    "amarelo": "4", "banana": "5",
    "laranja": "6", "tangerina": "6",
    "azul": "7", "peacock": "7",
    "azul-escuro": "8", "azul escuro": "8", "mirtilo": "8", "blueberry": "8",
    "verde-escuro": "9", "verde escuro": "9", "manjericao": "9",
    "vermelho": "11", "tomate": "11", "tomato": "11",
    "cinza": "None",
}

def _cor_para_id(cor):
    if not cor:
        return None
    return CORES_AGENDA.get(cor.lower().strip())

def _google_refresh_token(refresh_token):
    """Troca o refresh_token por um novo access_token."""
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]

def criar_evento_agenda(cliente_id, titulo, data_hora_iso, duracao_min=60, cor=None):
    import datetime as dt

    conn = get_db()
    row = conn.execute(
        "SELECT google_access_token, google_refresh_token FROM clientes WHERE id=%s",
        (cliente_id,)
    ).fetchone()
    conn.close()

    if not row or not row["google_refresh_token"]:
        return None

    access_token = row["google_access_token"]
    # Tenta criar o evento; se 401, renova o token e tenta de novo
    for tentativa in range(2):
        inicio = dt.datetime.fromisoformat(data_hora_iso)
        fim = inicio + dt.timedelta(minutes=duracao_min)
        event = {
            "summary": titulo,
            "start": {"dateTime": inicio.isoformat(), "timeZone": "America/Sao_Paulo"},
            "end": {"dateTime": fim.isoformat(), "timeZone": "America/Sao_Paulo"},
        }
        color_id = _cor_para_id(cor)
        if color_id and color_id != "None":
            event["colorId"] = color_id
        resp = requests.post(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=event, timeout=15
        )
        if resp.status_code == 401 and tentativa == 0:
            access_token = _google_refresh_token(row["google_refresh_token"])
            conn = get_db()
            conn.execute("UPDATE clientes SET google_access_token=%s WHERE id=%s", (access_token, cliente_id))
            conn.commit()
            conn.close()
            continue
        resp.raise_for_status()
        return resp.json().get("htmlLink")

def chamar_claude(mensagem, historico=[]):
    """Chama a API do Claude para interpretar a mensagem."""
    system = f"""Você é um assistente financeiro amigável via WhatsApp.
Seu papel é ajudar o usuário a registrar gastos e consultar o resumo financeiro.

Ao receber uma mensagem, identifique se é:
1. Um REGISTRO de gasto — extraia: descricao, valor (número), categoria, data
2. Uma EXCLUSÃO do último gasto — ex: "apaga o último", "cancela o último gasto"
3. Uma EXCLUSÃO por descrição — ex: "apaga o mercado", "cancela os 50 reais do uber"
4. Uma EXCLUSÃO de todos os gastos — ex: "apaga tudo", "zera meus gastos", "limpa o histórico", "apaga todos os gastos do mês"
4. Uma CONSULTA de resumo — ex: "quanto gastei?", "resumo do mês"
5. Um pedido de ANÁLISE financeira — ex: "analisa meus gastos", "onde estou gastando mais?", "como estão minhas finanças?", "tendência de gastos", "o que devo economizar?"
6. Um pedido de DASHBOARD/GRÁFICO — ex: "manda o gráfico", "quero ver meu dashboard", "relatório visual", "gráfico de gastos"
7. Um pedido para CONECTAR Google Agenda — ex: "quero conectar minha agenda", "conectar google agenda", "ativar agenda"
8. Um AGENDAMENTO no Google Agenda — ex: "médico amanhã às 14h", "reunião sexta às 10h", "dentista dia 10 às 15 horas"
9. Um REGISTRO de renda — ex: "ganho 3000 por mês", "meu salário é 5000", "recebo 2500 mensais", "minha renda é 4000"
10. Outra mensagem — responda de forma amigável

Categorias disponíveis: {', '.join(CATEGORIAS)}

Se for um registro de UM gasto, responda APENAS com JSON no formato:
{{"acao": "registrar", "descricao": "...", "valor": 0.00, "categoria": "...", "data": "YYYY-MM-DD"}}

Se for um registro de MÚLTIPLOS gastos na mesma mensagem (ex: "gastei 50 no mercado, 30 no uber e 15 no café"), responda com JSON no formato:
{{"acao": "registrar_multiplos", "gastos": [{{"descricao": "...", "valor": 0.00, "categoria": "...", "data": "YYYY-MM-DD"}}, ...]}}

Se for exclusão do último gasto:
{{"acao": "deletar_ultimo"}}

Se for exclusão de todos os gastos (mês atual ou histórico completo):
{{"acao": "deletar_tudo", "mes": "YYYY-MM"}}
(use "mes" com o mês atual se disser "deste mês", omita "mes" se quiser apagar tudo)

Se for exclusão por descrição (extraia a descrição e opcionalmente o valor):
{{"acao": "deletar", "descricao": "...", "valor": 0.00}}
(omita "valor" se não mencionado)

Se for consulta de resumo, responda:
{{"acao": "resumo"}}

Se for pedido de análise financeira:
{{"acao": "analise"}}

Se for pedido de dashboard/gráfico visual:
{{"acao": "dashboard"}}

Se for pedido para conectar Google Agenda:
{{"acao": "conectar_agenda"}}

Se for um agendamento (extraia título, data/hora, duração em minutos e cor opcional):
{{"acao": "agendar", "titulo": "...", "data_hora": "YYYY-MM-DDTHH:MM:00", "duracao_min": 60, "cor": "vermelho"}}
(use 60 minutos como padrão se não informado. Interprete datas relativas como "amanhã", "sexta", "dia 10" com base em hoje. Omita "cor" se não mencionada. Cores possíveis: vermelho, laranja, amarelo, verde, azul, azul-escuro, roxo, rosa, cinza.)

Se for registro de renda mensal:
{{"acao": "registrar_renda", "valor": 0.00}}

Para outras mensagens:
{{"acao": "mensagem", "texto": "sua resposta aqui"}}

Data de hoje: {hoje_brasil().isoformat()}
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

def gerar_imagem_dashboard(cliente_id):
    import io, base64
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mes = hoje_brasil().strftime("%Y-%m")
    conn = get_db()
    por_cat = conn.execute(
        "SELECT categoria, SUM(valor) as total FROM gastos WHERE cliente_id=%s AND data LIKE %s GROUP BY categoria ORDER BY total DESC",
        (cliente_id, f"{mes}%")
    ).fetchall()
    total_geral = conn.execute(
        "SELECT COALESCE(SUM(valor),0) as t FROM gastos WHERE cliente_id=%s AND data LIKE %s",
        (cliente_id, f"{mes}%")
    ).fetchone()["t"]
    conn.close()

    if not por_cat:
        return None

    categorias = [r["categoria"] for r in por_cat]
    valores = [float(r["total"]) for r in por_cat]
    percentuais = [v / total_geral * 100 if total_geral else 0 for v in valores]

    cores = ["#FF6B6B","#4ECDC4","#45B7D1","#96CEB4","#FFEAA7","#DDA0DD","#98D8C8","#F7DC6F","#E8A87C"]

    fig, ax = plt.subplots(figsize=(8, max(3, len(categorias) * 0.9 + 1.5)))
    fig.patch.set_facecolor("#F8F9FA")
    ax.set_facecolor("#F8F9FA")

    bars = ax.barh(categorias, valores, color=cores[:len(categorias)], height=0.55, edgecolor="white", linewidth=1.5)

    for bar, val, pct in zip(bars, valores, percentuais):
        ax.text(
            bar.get_width() + max(valores) * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"R$ {val:,.2f}  {pct:.1f}%",
            va="center", fontsize=9, color="#333333"
        )

    mes_nome = mes_ano_pt()
    ax.set_title(f"Gastos por Categoria — {mes_nome}\nTotal: R$ {total_geral:,.2f}", fontsize=12, fontweight="bold", pad=12, color="#222222")
    ax.invert_yaxis()
    ax.set_xlim(0, max(valores) * 1.45)
    ax.tick_params(axis="y", labelsize=10)
    ax.xaxis.set_visible(False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(False)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close()
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")

def enviar_imagem_whatsapp(fone, imagem_b64, caption=""):
    if not EVOLUTION_KEY:
        return
    url = f"{EVOLUTION_URL}/message/sendMedia/{EVOLUTION_INSTANCE}"
    headers = {"apikey": EVOLUTION_KEY, "Content-Type": "application/json"}
    body = {
        "number": fone,
        "mediatype": "image",
        "mimetype": "image/png",
        "caption": caption,
        "media": imagem_b64,
        "fileName": "relatorio.png",
    }
    requests.post(url, headers=headers, json=body, timeout=20)

def enviar_whatsapp(fone, mensagem):
    """Envia mensagem de resposta via Evolution API."""
    if not EVOLUTION_KEY:
        print(f"[WPP → {fone}] {mensagem}")
        return
    url = f"{EVOLUTION_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    headers = {"apikey": EVOLUTION_KEY, "Content-Type": "application/json"}
    body = {"number": fone, "text": mensagem}
    requests.post(url, headers=headers, json=body, timeout=10)

def analisar_comprovante_claude(imagem_b64, caption=""):
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    conteudo = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": imagem_b64}
        },
        {
            "type": "text",
            "text": (
                f'Analise este comprovante/nota fiscal/recibo e extraia os dados do gasto.\n'
                f'Legenda enviada pelo usuário: "{caption}"\n\n'
                f"Responda APENAS com JSON no formato:\n"
                f'{{"descricao": "...", "valor": 0.00, "categoria": "...", "data": "YYYY-MM-DD"}}\n\n'
                f"Categorias disponíveis: {', '.join(CATEGORIAS)}\n"
                f"Data de hoje: {hoje_brasil().isoformat()}\n"
                f"Se não conseguir identificar algum campo, use 'Outros' como categoria e a data de hoje.\n"
                f"Se a imagem não for um comprovante de gasto, responda: {{\"erro\": \"nao_e_comprovante\"}}"
            )
        }
    ]
    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": conteudo}]
    }
    res = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=25)
    res.raise_for_status()
    texto = res.json()["content"][0]["text"].strip().replace("```json", "").replace("```", "").strip()
    return json.loads(texto)

def _audio_file(audio_b64, mime_type):
    """Retorna (audio_bytes, ext, content_type) para envio à API de transcrição."""
    import base64
    audio_bytes = base64.b64decode(audio_b64)
    if "ogg" in mime_type or "opus" in mime_type:
        return audio_bytes, "ogg", "audio/ogg"
    elif "mp4" in mime_type or "m4a" in mime_type:
        return audio_bytes, "m4a", "audio/mp4"
    elif "webm" in mime_type:
        return audio_bytes, "webm", "audio/webm"
    elif "mpeg" in mime_type or "mp3" in mime_type:
        return audio_bytes, "mp3", "audio/mpeg"
    return audio_bytes, "ogg", "audio/ogg"

def transcrever_audio_groq(audio_b64, mime_type="audio/ogg"):
    import io, logging
    audio_bytes, ext, ct = _audio_file(audio_b64, mime_type)
    logging.warning(f"[AUDIO-GROQ] ext={ext} bytes={len(audio_bytes)}")
    files = {"file": (f"audio.{ext}", io.BytesIO(audio_bytes), ct)}
    data  = {"model": "whisper-large-v3", "language": "pt", "response_format": "text"}
    resp  = requests.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        files=files, data=data, timeout=30
    )
    logging.warning(f"[AUDIO-GROQ] status={resp.status_code} body={resp.text[:200]}")
    resp.raise_for_status()
    return resp.text.strip()

def transcrever_audio_openai(audio_b64, mime_type="audio/ogg"):
    import io, logging
    audio_bytes, ext, ct = _audio_file(audio_b64, mime_type)
    logging.warning(f"[AUDIO-OPENAI] ext={ext} bytes={len(audio_bytes)}")
    files = {"file": (f"audio.{ext}", io.BytesIO(audio_bytes), ct)}
    data  = {"model": "whisper-1", "language": "pt", "response_format": "text"}
    resp  = requests.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        files=files, data=data, timeout=30
    )
    logging.warning(f"[AUDIO-OPENAI] status={resp.status_code} body={resp.text[:200]}")
    resp.raise_for_status()
    return resp.text.strip()

def transcrever_audio(audio_b64, mime_type="audio/ogg"):
    """OpenAI como primário (estável), Groq como fallback gratuito."""
    import logging
    if OPENAI_API_KEY:
        try:
            return transcrever_audio_openai(audio_b64, mime_type)
        except Exception as e:
            logging.error(f"[AUDIO] OpenAI falhou ({e}), tentando Groq...")
    if GROQ_API_KEY:
        try:
            return transcrever_audio_groq(audio_b64, mime_type)
        except Exception as e:
            logging.error(f"[AUDIO] Groq também falhou ({e})")
            raise
    raise RuntimeError("Nenhuma chave de transcrição configurada (OPENAI_API_KEY ou GROQ_API_KEY)")

def processar_audio(fone, audio_b64, mime_type="audio/ogg"):
    cliente = buscar_cliente_por_fone(fone)
    if not cliente:
        enviar_whatsapp(fone, "Olá! Não encontrei sua conta. Cadastre-se no Controla Fácil para começar.")
        return "cliente não encontrado"
    if cliente["status"] != "ativo":
        enviar_whatsapp(fone, "Sua conta ainda não está ativa. Conclua o pagamento no Controla Fácil.")
        return "conta inativa"
    if not GROQ_API_KEY and not OPENAI_API_KEY:
        enviar_whatsapp(fone, "Transcrição de áudio não configurada. Envie sua mensagem em texto.")
        return "transcrição não configurada"
    try:
        texto = transcrever_audio(audio_b64, mime_type)
        if not texto:
            enviar_whatsapp(fone, "Não consegui entender o áudio. Tente enviar em texto.")
            return "transcrição vazia"
        import logging
        logging.warning(f"[ÁUDIO TRANSCRITO de {fone}]: {texto}")
        return processar_mensagem(fone, texto, _cliente=cliente)
    except Exception as e:
        import logging, traceback
        logging.error(f"Erro ao transcrever áudio: {e}\n{traceback.format_exc()}")
        enviar_whatsapp(fone, "Não consegui processar o áudio. Tente enviar em texto.")
        return "erro transcrição"

def processar_imagem(fone, imagem_b64, caption=""):
    cliente = buscar_cliente_por_fone(fone)
    if not cliente:
        enviar_whatsapp(fone, "Olá! Não encontrei sua conta. Cadastre-se no Controla Fácil para começar.")
        return "cliente não encontrado"
    if cliente["status"] != "ativo":
        enviar_whatsapp(fone, "Sua conta ainda não está ativa. Conclua o pagamento no Controla Fácil.")
        return "conta inativa"
    try:
        resultado = analisar_comprovante_claude(imagem_b64, caption)
        if resultado.get("erro") == "nao_e_comprovante":
            enviar_whatsapp(fone, "Não consegui identificar um comprovante nessa imagem. Envie a foto de um recibo ou nota fiscal.")
            return "imagem inválida"
        data_comp = resultado.get("data", hoje_brasil().isoformat())
        salvar_gasto(
            cliente["id"],
            resultado["descricao"],
            float(resultado["valor"]),
            resultado["categoria"],
            data_comp
        )
        resposta = (
            f"✅ Comprovante registrado!\n"
            f"📝 {resultado['descricao']}\n"
            f"💰 R$ {float(resultado['valor']):.2f}\n"
            f"📂 {resultado['categoria']}\n"
            f"📅 {formatar_data(data_comp)}"
        )
    except Exception as e:
        import logging, traceback
        logging.error(f"Erro ao analisar comprovante: {e}\n{traceback.format_exc()}")
        resposta = "Não consegui ler o comprovante. Tente uma foto mais nítida ou descreva o gasto em texto."
    enviar_whatsapp(fone, resposta)
    return resposta

def processar_mensagem(fone, mensagem, _cliente=None):
    """Função principal chamada pelo webhook."""
    cliente = _cliente or buscar_cliente_por_fone(fone)
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
                resultado.get("data", hoje_brasil().isoformat())
            )
            data_gasto = resultado.get("data", hoje_brasil().isoformat())
            resposta = (
                f"✅ Registrado!\n"
                f"📝 {resultado['descricao']}\n"
                f"💰 R$ {float(resultado['valor']):.2f}\n"
                f"📂 {resultado['categoria']}\n"
                f"📅 {formatar_data(data_gasto)}"
            )

        elif acao == "registrar_multiplos":
            gastos = resultado.get("gastos", [])
            total = 0.0
            linhas = ["✅ Gastos registrados!\n"]
            for g in gastos:
                data_g = g.get("data", hoje_brasil().isoformat())
                salvar_gasto(
                    cliente["id"],
                    g["descricao"],
                    float(g["valor"]),
                    g["categoria"],
                    data_g
                )
                total += float(g["valor"])
                linhas.append(f"📝 {g['descricao']} — R$ {float(g['valor']):.2f} ({g['categoria']}) {formatar_data(data_g)}")
            linhas.append(f"\n💰 Total: R$ {total:.2f}")
            resposta = "\n".join(linhas)

        elif acao == "deletar_tudo":
            mes = resultado.get("mes")
            deletar_todos_gastos(cliente["id"], mes)
            if mes:
                resposta = f"🗑️ Todos os gastos de {mes_ano_pt(date.fromisoformat(mes + '-01'))} foram apagados."
            else:
                resposta = "🗑️ Todo o histórico de gastos foi apagado."

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

        elif acao == "dashboard":
            imagem = gerar_imagem_dashboard(cliente["id"])
            if imagem:
                mes_nome = mes_ano_pt()
                enviar_imagem_whatsapp(fone, imagem, f"📊 Seus gastos de {mes_nome}")
                resposta = ""
            else:
                resposta = "Você ainda não tem gastos registrados este mês para gerar o gráfico."

        elif acao == "analise":
            gastos = historico_gastos(cliente["id"])
            resposta = gerar_analise_financeira(gastos)

        elif acao == "resumo":
            total, por_cat = resumo_mes(cliente["id"])
            renda = float(cliente["renda_mensal"]) if cliente.get("renda_mensal") else None
            linhas = [f"📊 *Resumo de {mes_ano_pt()}*", ""]
            if renda:
                saldo = renda - total
                pct = (total / renda * 100) if renda else 0
                linhas.append(f"💵 Renda: R$ {renda:.2f}")
                linhas.append(f"💸 Gasto: R$ {total:.2f} ({pct:.1f}%)")
                linhas.append(f"{'✅' if saldo >= 0 else '⚠️'} Saldo: R$ {saldo:.2f}")
            else:
                linhas.append(f"💰 Total gasto: R$ {total:.2f}")
                linhas.append("💡 _Dica: informe sua renda com 'meu salário é 3000' para ver o saldo_")
            linhas.append("")
            for c in por_cat:
                linhas.append(f"  • {c['categoria']}: R$ {c['s']:.2f}")
            resposta = "\n".join(linhas)

        elif acao == "registrar_renda":
            valor = float(resultado.get("valor", 0))
            if valor > 0:
                salvar_renda(cliente["id"], valor)
                resposta = (
                    f"✅ Renda mensal registrada: R$ {valor:.2f}\n\n"
                    f"Agora consigo te mostrar quanto você já gastou em relação à sua renda. "
                    f"Envie *resumo* para ver!"
                )
            else:
                resposta = "Não consegui identificar o valor da renda. Tente: *meu salário é 3000*"

        elif acao == "conectar_agenda":
            link = gerar_link_agenda(cliente["id"])
            resposta = (
                f"📅 Para conectar seu Google Agenda, clique no link abaixo:\n\n"
                f"{link}\n\n"
                f"⚠️ *Atenção:* o Google pode exibir um aviso dizendo que o app não foi verificado. "
                f"É normal! Basta clicar em *'Avançado'* e depois em *'Ir para Controla Fácil'* para continuar.\n\n"
                f"Após autorizar, você poderá agendar compromissos direto aqui pelo WhatsApp! 😊"
            )

        elif acao == "agendar":
            if not verificar_agenda_conectada(cliente["id"]):
                link = gerar_link_agenda(cliente["id"])
                resposta = (
                    f"📅 Sua agenda ainda não está conectada. Clique no link abaixo para autorizar:\n\n"
                    f"{link}\n\n"
                    f"⚠️ *Atenção:* o Google pode exibir um aviso dizendo que o app não foi verificado. "
                    f"É normal! Clique em *'Avançado'* e depois em *'Ir para Controla Fácil'* para continuar.\n\n"
                    f"Após conectar, envie o agendamento novamente."
                )
            else:
                titulo = resultado.get("titulo", "Compromisso")
                data_hora = resultado.get("data_hora", "")
                duracao = int(resultado.get("duracao_min", 60))
                cor = resultado.get("cor")
                try:
                    link_evento = criar_evento_agenda(cliente["id"], titulo, data_hora, duracao, cor)
                    from datetime import datetime as _dt
                    dt_fmt = _dt.fromisoformat(data_hora)
                    cor_emoji = {"vermelho":"🔴","laranja":"🟠","amarelo":"🟡","verde":"🟢","azul":"🔵","roxo":"🟣","rosa":"🩷","cinza":"⚫"}.get((cor or "").lower(), "")
                    resposta = (
                        f"✅ Agendado no Google Agenda!\n"
                        f"📌 {titulo}\n"
                        f"📅 {dt_fmt.strftime('%d/%m/%Y')} às {dt_fmt.strftime('%H:%M')}\n"
                        f"⏱️ Duração: {duracao} min"
                        + (f"\n🎨 Cor: {cor_emoji} {cor.capitalize()}" if cor else "")
                    )
                except Exception as e:
                    import logging, traceback
                    logging.error(f"Erro ao criar evento: {e}\n{traceback.format_exc()}")
                    resposta = "Não consegui criar o evento na agenda. Tente novamente."

        else:
            resposta = resultado.get("texto", "Como posso te ajudar?")

    except Exception as e:
        import logging, traceback
        logging.error(f"Erro agente: {e}\n{traceback.format_exc()}")
        resposta = "Desculpe, não consegui processar sua mensagem. Tente novamente."

    enviar_whatsapp(fone, resposta)
    return resposta
