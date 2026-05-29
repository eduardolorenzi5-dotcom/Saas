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

# Abstração de provedor WhatsApp (evolution ou meta)
from agente.wpp_provider import send_text as _wpp_send_text, send_image_b64 as _wpp_send_image_b64
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
APP_URL = os.environ.get("APP_URL", "https://saas-production-2a7a.up.railway.app")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

CATEGORIAS = ["Alimentação","Transporte","Saúde","Lazer","Moradia","Educação","Roupas","Outros"]

def get_contas_cliente(cliente_id):
    """Retorna lista de contas bancárias do cliente [{id, nome, tipo}]."""
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT id, nome, tipo FROM contas_bancarias WHERE cliente_id=%s AND ativo=TRUE ORDER BY nome",
            (cliente_id,)
        ).fetchall()
        conn.close()
        return [{"id": r["id"], "nome": r["nome"], "tipo": r["tipo"]} for r in rows]
    except Exception:
        return []

def get_categorias_cliente(cliente_id):
    """Retorna lista de categorias personalizadas do cliente, ou padrão."""
    try:
        conn = get_db()
        USE_PG = bool(os.environ.get("DATABASE_URL"))
        if USE_PG:
            rows = conn.execute(
                "SELECT nome FROM categorias WHERE cliente_id=%s ORDER BY nome", (cliente_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT nome FROM categorias WHERE cliente_id=? ORDER BY nome", (cliente_id,)
            ).fetchall()
        conn.close()
        if rows:
            return [r["nome"] for r in rows]
    except Exception:
        pass
    return CATEGORIAS

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

    # ── Plano Casal: mensagem de grupo (JID termina em @g.us) ────────────────
    if fone.endswith("@g.us"):
        conn = get_db()
        cliente = conn.execute(
            "SELECT * FROM clientes WHERE grupo_wpp_id = %s AND status = 'ativo'", (fone,)
        ).fetchone()
        conn.close()
        if cliente:
            logging.warning(f"[BUSCA_CLIENTE] grupo encontrado: id={cliente['id']} grupo={fone!r}")
        else:
            logging.warning(f"[BUSCA_CLIENTE] grupo NAO mapeado: {fone!r}")
        return cliente

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

    # 1. Busca por whatsapp principal
    for v in variantes:
        cliente = conn.execute(
            "SELECT * FROM clientes WHERE whatsapp = %s", (v,)
        ).fetchone()
        if cliente:
            break

    # 2. Busca por whatsapp2 (Plano Casal — número do cônjuge)
    if not cliente:
        for v in variantes:
            cliente = conn.execute(
                "SELECT * FROM clientes WHERE whatsapp2 = %s", (v,)
            ).fetchone()
            if cliente:
                logging.warning(f"[BUSCA_CLIENTE] encontrado via whatsapp2 {v!r}: id={cliente['id']}")
                break

    # 3. Fallback: busca parcial pelo sufixo do número (últimos 8 dígitos)
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

def salvar_gasto(cliente_id, descricao, valor, categoria, data_gasto, conta_id=None):
    import logging
    logging.warning(f"[SALVAR_GASTO] cliente_id={cliente_id} descricao={descricao!r} valor={valor} data={data_gasto!r} conta_id={conta_id}")
    conn = get_db()
    conn.execute(
        "INSERT INTO gastos (cliente_id, descricao, valor, categoria, data, fonte, conta_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (cliente_id, descricao, valor, categoria, data_gasto, "whatsapp", conta_id)
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

def editar_gasto_por_descricao(cliente_id, descricao, novo_valor=None, nova_descricao=None, nova_categoria=None, nova_data=None):
    """Encontra o gasto mais recente pela descrição e atualiza os campos informados."""
    conn = get_db()
    gasto = conn.execute(
        "SELECT id, descricao, valor, categoria, data FROM gastos "
        "WHERE cliente_id=%s AND LOWER(descricao) LIKE LOWER(%s) ORDER BY criado_em DESC LIMIT 1",
        (cliente_id, f"%{descricao}%")
    ).fetchone()
    if not gasto:
        conn.close()
        return None
    gasto = dict(gasto)
    val_final  = float(novo_valor)      if novo_valor      is not None else float(gasto["valor"])
    desc_final = nova_descricao.strip() if nova_descricao               else gasto["descricao"]
    cat_final  = nova_categoria         if nova_categoria               else gasto["categoria"]
    data_final = nova_data              if nova_data                    else gasto["data"]
    conn.execute(
        "UPDATE gastos SET descricao=%s, valor=%s, categoria=%s, data=%s WHERE id=%s AND cliente_id=%s",
        (desc_final, val_final, cat_final, data_final, gasto["id"], cliente_id)
    )
    conn.commit()
    conn.close()
    gasto.update({"valor": val_final, "descricao": desc_final, "categoria": cat_final, "data": data_final})
    return gasto

def editar_renda_por_descricao(cliente_id, descricao, novo_valor=None, nova_descricao=None, novo_tipo=None, nova_data=None):
    """Encontra a renda mais recente pela descrição e atualiza os campos informados."""
    conn = get_db()
    renda = conn.execute(
        "SELECT id, descricao, valor, tipo, data FROM rendas "
        "WHERE cliente_id=%s AND LOWER(descricao) LIKE LOWER(%s) ORDER BY criado_em DESC LIMIT 1",
        (cliente_id, f"%{descricao}%")
    ).fetchone()
    if not renda:
        conn.close()
        return None
    renda = dict(renda)
    val_final  = float(novo_valor)      if novo_valor      is not None else float(renda["valor"])
    desc_final = nova_descricao.strip() if nova_descricao               else renda["descricao"]
    tipo_final = novo_tipo              if novo_tipo                    else renda["tipo"]
    data_final = nova_data              if nova_data                    else renda["data"]
    conn.execute(
        "UPDATE rendas SET descricao=%s, valor=%s, tipo=%s, data=%s WHERE id=%s AND cliente_id=%s",
        (desc_final, val_final, tipo_final, data_final, renda["id"], cliente_id)
    )
    conn.commit()
    conn.close()
    renda.update({"valor": val_final, "descricao": desc_final, "tipo": tipo_final, "data": data_final})
    return renda

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

def registrar_entrada_renda(cliente_id, descricao, valor, tipo, data, conta_id=None):
    """Registra uma entrada de renda na tabela rendas."""
    USE_PG = bool(os.environ.get("DATABASE_URL"))
    conn = get_db()
    if USE_PG:
        conn.execute(
            "INSERT INTO rendas (cliente_id, descricao, valor, tipo, data, fonte, conta_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (cliente_id, descricao, valor, tipo, data, "whatsapp", conta_id)
        )
    else:
        conn.execute(
            "INSERT INTO rendas (cliente_id, descricao, valor, tipo, data, fonte, conta_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cliente_id, descricao, valor, tipo, data, "whatsapp", conta_id)
        )
    conn.commit()
    conn.close()

def verificar_agenda_conectada(cliente_id):
    conn = get_db()
    row = conn.execute("SELECT google_refresh_token FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
    conn.close()
    return bool(row and row["google_refresh_token"])

def listar_eventos_google_hoje(cliente_id):
    """Busca os eventos de hoje no Google Calendar do cliente. Retorna lista de dicts ou None se não conectado."""
    import datetime as dt
    conn = get_db()
    row = conn.execute(
        "SELECT google_access_token, google_refresh_token FROM clientes WHERE id=%s",
        (cliente_id,)
    ).fetchone()
    conn.close()
    if not row or not row["google_refresh_token"]:
        return None  # agenda não conectada
    access_token = row["google_access_token"]
    hoje = dt.date.today()
    time_min = dt.datetime(hoje.year, hoje.month, hoje.day, 0, 0, 0).isoformat() + "-03:00"
    time_max = dt.datetime(hoje.year, hoje.month, hoje.day, 23, 59, 59).isoformat() + "-03:00"
    for tentativa in range(2):
        resp = requests.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 20,
            },
            timeout=15
        )
        if resp.status_code == 401 and tentativa == 0:
            access_token = _google_refresh_token(row["google_refresh_token"])
            conn2 = get_db()
            conn2.execute("UPDATE clientes SET google_access_token=%s WHERE id=%s", (access_token, cliente_id))
            conn2.commit()
            conn2.close()
            continue
        if resp.status_code != 200:
            return []
        itens = resp.json().get("items", [])
        eventos = []
        for item in itens:
            titulo = item.get("summary", "Sem título")
            inicio = item.get("start", {})
            hora_str = ""
            if "dateTime" in inicio:
                dt_obj = dt.datetime.fromisoformat(inicio["dateTime"])
                hora_str = dt_obj.strftime("%H:%M")
            else:
                hora_str = "Dia todo"
            eventos.append({"titulo": titulo, "hora": hora_str})
        return eventos
    return []

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

def buscar_historico_conversa(cliente_id, limite=10):
    """Retorna as últimas N mensagens da conversa do cliente (janela de 2 horas)."""
    conn = get_db()
    try:
        USE_PG = bool(os.environ.get("DATABASE_URL"))
        if USE_PG:
            rows = conn.execute(
                """SELECT role, conteudo FROM conversa_historico
                   WHERE cliente_id=%s
                     AND criado_em >= NOW() - INTERVAL '2 hours'
                   ORDER BY criado_em DESC LIMIT %s""",
                (cliente_id, limite)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT role, conteudo FROM conversa_historico
                   WHERE cliente_id=?
                     AND criado_em >= datetime('now', '-2 hours')
                   ORDER BY criado_em DESC LIMIT ?""",
                (cliente_id, limite)
            ).fetchall()
        conn.close()
        # Reverter para ordem cronológica (mais antigo primeiro)
        return [{"role": r["role"], "content": r["conteudo"]} for r in reversed(rows)]
    except Exception as e:
        import logging; logging.warning(f"[HISTORICO] Erro ao buscar: {e}")
        try: conn.close()
        except: pass
        return []

def salvar_historico_conversa(cliente_id, role, conteudo):
    """Salva uma mensagem no histórico de conversa e limpa mensagens antigas."""
    conn = get_db()
    USE_PG = bool(os.environ.get("DATABASE_URL"))
    try:
        if USE_PG:
            conn.execute(
                "INSERT INTO conversa_historico (cliente_id, role, conteudo) VALUES (%s, %s, %s)",
                (cliente_id, role, conteudo)
            )
            # Mantém apenas as últimas 30 mensagens por cliente
            conn.execute(
                """DELETE FROM conversa_historico WHERE cliente_id=%s AND id NOT IN (
                   SELECT id FROM conversa_historico WHERE cliente_id=%s ORDER BY id DESC LIMIT 30
                )""",
                (cliente_id, cliente_id)
            )
        else:
            conn.execute(
                "INSERT INTO conversa_historico (cliente_id, role, conteudo) VALUES (?, ?, ?)",
                (cliente_id, role, conteudo)
            )
            conn.execute(
                """DELETE FROM conversa_historico WHERE cliente_id=? AND id NOT IN (
                   SELECT id FROM conversa_historico WHERE cliente_id=? ORDER BY id DESC LIMIT 30
                )""",
                (cliente_id, cliente_id)
            )
        conn.commit()
    except Exception as e:
        import logging; logging.error(f"[HISTORICO] Erro ao salvar: {e}")
    finally:
        try: conn.close()
        except: pass

def chamar_claude(mensagem, historico=[], categorias=None, contas=None):
    """Chama a API do Claude para interpretar a mensagem."""
    cats_list = categorias if categorias else CATEGORIAS

    # Monta bloco de contas bancárias para o prompt
    if contas:
        contas_texto = "Contas bancárias do cliente:\n" + "\n".join(
            f"  - ID {c['id']}: \"{c['nome']}\" ({c['tipo']})" for c in contas
        )
        contas_instrucao = (
            "\n\nSe o usuário mencionar uma conta bancária pelo nome (ex: 'na conta do Nubank', "
            "'no Bradesco', 'na poupança'), identifique o ID da conta acima e inclua conta_id no JSON. "
            "Se não mencionar conta, omita conta_id."
        )
    else:
        contas_texto = ""
        contas_instrucao = ""

    system = f"""Você é um assistente financeiro amigável via WhatsApp.
Seu papel é ajudar o usuário a registrar gastos e consultar o resumo financeiro.

Ao receber uma mensagem, identifique se é:
1. Um REGISTRO de gasto — extraia: descricao, valor (número), categoria, data
2. Uma EXCLUSÃO do último gasto — ex: "apaga o último", "cancela o último gasto"
3. Uma EXCLUSÃO por descrição — ex: "apaga o mercado", "cancela os 50 reais do uber"
4. Uma EXCLUSÃO de todos os gastos — ex: "apaga todos os gastos", "zera meus gastos", "limpa o histórico", "apaga todos os gastos do mês"
4b. Uma LIMPEZA TOTAL (gastos + rendas + saldo) — ex: "apaga tudo", "zera tudo", "limpa tudo", "quero começar do zero", "apaga todas as informações", "reinicia minha conta"
4. Uma CONSULTA de resumo — ex: "quanto gastei?", "resumo do mês", "quanto ganhei?", "qual meu saldo?", "como estou esse mês?", "quanto tenho de saldo?", "quanto entrou esse mês?", "qual minha renda esse mês?"
5. Um pedido de ANÁLISE financeira — ex: "analisa meus gastos", "onde estou gastando mais?", "como estão minhas finanças?", "tendência de gastos", "o que devo economizar?"
6. Um pedido de DASHBOARD/GRÁFICO — ex: "manda o gráfico", "quero ver meu dashboard", "relatório visual", "gráfico de gastos"
7. Um pedido de RELATÓRIO PDF — ex: "quero meu relatório", "manda o PDF", "relatório completo", "relatório do mês", "relatório em PDF", "extrato do mês"
7. Um pedido para CONECTAR Google Agenda — ex: "quero conectar minha agenda", "conectar google agenda", "ativar agenda"
8. Um AGENDAMENTO no Google Agenda — ex: "médico amanhã às 14h", "reunião sexta às 10h", "dentista dia 10 às 15 horas"
9. Um REGISTRO de renda — ex: "recebi meu salário de 3000", "caiu meu salário", "recebi um freela de 500", "entrou 200 de renda extra", "ganho 3000 por mês", "meu salário é 5000"
9b. EXCLUIR renda — ex: "excluir minha renda extra", "apagar renda de freela", "remover renda do mês", "excluir informações de renda", "deletar renda extra", "apaga minha renda"
9c. EDITAR gasto — ex: "corrige o uber para 45", "muda o mercado de 80 para 65", "a categoria do almoço é Alimentação", "o gasto do posto foi 120 não 90", "arruma o valor do netflix", "edita o lançamento do mercado"
9d. EDITAR renda — ex: "corrige meu salário para 3500", "o freela foi 800 não 600", "muda a descrição da renda para Comissão"
10. Um LEMBRETE — ex: "me lembre de passear com os cachorros às 14h", "lembrete: reunião às 9h", "todo dia às 8h me lembre de tomar remédio", "lembrete amanhã às 10h: dentista"
11. EXCLUIR um lembrete — ex: "exclua esse lembrete", "cancela o lembrete do médico", "excluir lembrete", "remove o lembrete de passear com os cachorros", "apagar lembrete"
12. LISTAR lembretes ativos — ex: "quais meus lembretes?", "ver lembretes", "meus lembretes ativos"
13. VER COMPROMISSOS DE HOJE — ex: "meus compromissos hoje", "o que tenho hoje?", "agenda de hoje", "me manda minha agenda", "lembretes de hoje", "o que está agendado hoje?", "quais eventos tenho hoje?"
14. REGISTRAR conta mensal recorrente (débito automático todo mês) — ex: "toda mês pago energia 100 reais no dia 10", "aluguel 1500 todo dia 5", "internet 80 reais vence dia 15", "cadastra débito automático da academia 99 no dia 1"
15. PARCELAMENTO — ex: "comprei um sapato em 10x de 50 a partir do dia 5/6", "parcelei a geladeira em 12x de 200 reais a partir de julho dia 10", "agende 6 parcelas de 150 da TV começando dia 01/07", "tenho 8 parcelas de 80 do notebook"
16. LISTAR parcelamentos — ex: "meus parcelamentos", "minhas parcelas ativas", "o que tenho parcelado?", "parcelas em aberto"
17. CANCELAR parcelamento — ex: "cancela as parcelas do sapato", "excluir parcelamento da geladeira", "parar débito das parcelas do notebook"
18. LISTAR contas mensais — ex: "minhas contas mensais", "contas a pagar", "quais contas tenho?", "débitos automáticos cadastrados"
19. EXCLUIR conta mensal — ex: "remover conta da luz", "excluir débito automático do aluguel", "apagar conta mensal da academia"
20. MARCAR conta mensal como PAGA — ex: "paguei a conta de luz", "marquei o aluguel como pago", "paguei energia"
21. MARCAR TODAS as contas vencidas como pagas — ex: "paguei todas as contas vencidas", "marquei todas como pagas"
22. Outra mensagem — responda de forma amigável

Categorias disponíveis: {', '.join(cats_list)}
(Use SEMPRE uma das categorias listadas acima. Se nenhuma se encaixar, use a última da lista.)

Se for um registro de UM gasto, responda APENAS com JSON no formato:
{{"acao": "registrar", "descricao": "...", "valor": 0.00, "categoria": "...", "data": "YYYY-MM-DD"}}
(inclua "conta_id": <ID> se o usuário mencionar uma conta bancária; omita se não mencionar)

Se for um registro de MÚLTIPLOS gastos na mesma mensagem (ex: "gastei 50 no mercado, 30 no uber e 15 no café"), responda com JSON no formato:
{{"acao": "registrar_multiplos", "gastos": [{{"descricao": "...", "valor": 0.00, "categoria": "...", "data": "YYYY-MM-DD"}}, ...]}}
(em cada gasto, inclua "conta_id": <ID> se o usuário mencionar uma conta; omita se não mencionar)

Se for exclusão do último gasto:
{{"acao": "deletar_ultimo"}}

Se for exclusão de todos os gastos (mês atual ou histórico completo):
{{"acao": "deletar_tudo", "mes": "YYYY-MM"}}
(use "mes" com o mês atual se disser "deste mês", omita "mes" se quiser apagar tudo)

Se for limpeza total (apagar tudo: gastos + rendas + saldo zerado):
{{"acao": "zerar_tudo"}}

Se for exclusão por descrição (extraia a descrição e opcionalmente o valor):
{{"acao": "deletar", "descricao": "...", "valor": 0.00}}
(omita "valor" se não mencionado)

Se for consulta de resumo, responda:
{{"acao": "resumo"}}

Se for pedido de análise financeira:
{{"acao": "analise"}}

Se for pedido de dashboard/gráfico visual:
{{"acao": "dashboard"}}

Se for pedido de relatório PDF completo (geral, sem filtro por conta):
{{"acao": "relatorio"}}

Se for pedido de relatório PDF de UMA conta específica (ex: "relatório da conta Bradesco", "extrato em PDF do Nubank"):
{{"acao": "relatorio_conta", "conta_nome": "Bradesco"}}
- conta_nome: nome/parte do nome da conta mencionada pelo usuário

Se for pedido para conectar Google Agenda:
{{"acao": "conectar_agenda"}}

Se for um agendamento (extraia título, data/hora, duração em minutos e cor opcional):
{{"acao": "agendar", "titulo": "...", "data_hora": "YYYY-MM-DDTHH:MM:00", "duracao_min": 60, "cor": "vermelho"}}
(use 60 minutos como padrão se não informado. Interprete datas relativas como "amanhã", "sexta", "dia 10" com base em hoje. Omita "cor" se não mencionada. Cores possíveis: vermelho, laranja, amarelo, verde, azul, azul-escuro, roxo, rosa, cinza.)

Se for registro de renda:
{{"acao": "registrar_renda", "descricao": "...", "valor": 0.00, "tipo": "fixo", "data": "YYYY-MM-DD"}}
(inclua "conta_id": <ID> se o usuário mencionar uma conta bancária; omita se não mencionar)
- Use tipo "extra" SOMENTE se o usuário usar explicitamente as palavras "extra", "renda extra" ou "adicional"
- Em TODOS os outros casos use tipo "fixo" (salário, freela, comissão, bico, venda, qualquer renda)
- descricao: nome da renda (ex: "Salário", "Freela design", "Comissão de vendas")

Se for EDITAR/CORRIGIR um gasto existente (valor, descrição, categoria ou data):
{{"acao": "editar_gasto", "descricao": "palavra-chave do gasto", "novo_valor": 0.00, "nova_descricao": "...", "nova_categoria": "...", "nova_data": "YYYY-MM-DD"}}
- descricao: palavra-chave para localizar o gasto (obrigatório)
- novo_valor / nova_descricao / nova_categoria / nova_data: inclua SOMENTE os campos que o usuário quer mudar
- Exemplos: "corrige o uber para 45 reais" → {{"acao":"editar_gasto","descricao":"uber","novo_valor":45.00}}
            "muda categoria do mercado para Alimentação" → {{"acao":"editar_gasto","descricao":"mercado","nova_categoria":"Alimentação"}}
            "o almoço de ontem foi 32 reais, não 25" → {{"acao":"editar_gasto","descricao":"almoço","novo_valor":32.00}}

Se for EDITAR/CORRIGIR uma renda existente:
{{"acao": "editar_renda", "descricao": "palavra-chave da renda", "novo_valor": 0.00, "nova_descricao": "...", "novo_tipo": "fixo", "nova_data": "YYYY-MM-DD"}}
- descricao: palavra-chave para localizar a renda (obrigatório)
- inclua SOMENTE os campos que o usuário quer mudar

Se for EXCLUIR renda:
{{"acao": "deletar_renda", "tipo": "extra", "descricao": ""}}
- tipo: "fixo", "extra" ou "todos" (se quiser apagar tudo)
- descricao: palavra-chave da renda (ex: "freela") ou vazio para apagar todas do tipo

Se for um LEMBRETE (extraia mensagem, hora no formato HH:MM, data se mencionada, e se é recorrente):
{{"acao": "lembrete", "mensagem": "passear com os cachorros", "hora": "14:00", "data": "YYYY-MM-DD", "recorrente": false}}
- Se for "todo dia" / "todos os dias" / "diariamente": recorrente=true, omita data e dia_mes
- Se for "todo dia X" / "todo mês no dia X" / "dia X de cada mês" (ex: "todo dia 10 pagar energia"): use dia_mes=X, recorrente=false, omita data
  Exemplo: {{"acao": "lembrete", "mensagem": "pagar conta de energia", "hora": "09:00", "dia_mes": 10, "recorrente": false}}
- Se for hoje ou sem data específica: use a data de hoje, recorrente=false
- Se for amanhã: use data de amanhã, recorrente=false
- Hora sempre no formato HH:MM (ex: 14:00, 09:30, 08:00)
- Se o usuário não informar hora, use 09:00 como padrão

Se for EXCLUIR lembrete (inclui "exclua esse lembrete", "cancela lembrete", "apagar lembrete", "excluir"):
{{"acao": "deletar_lembrete", "descricao": "palavra-chave do lembrete ou vazio se não informado"}}
- Se o usuário não mencionar qual lembrete (ex: "exclua esse lembrete"), deixe descricao como string vazia ""
- Se mencionar qual (ex: "cancela o lembrete do médico"), coloque a palavra-chave: "médico"

Se for LISTAR lembretes:
{{"acao": "listar_lembretes"}}

Se for VER COMPROMISSOS DE HOJE (agenda + lembretes do dia):
{{"acao": "compromissos_hoje"}}

Se for REGISTRAR conta mensal recorrente com DÉBITO AUTOMÁTICO (ex: energia todo dia 10, aluguel todo dia 5):
{{"acao": "registrar_conta_mensal", "descricao": "Energia", "valor": 100.00, "dia_vencimento": 10, "categoria": "Moradia"}}
- valor: obrigatório para débito automático
- dia_vencimento: número do dia do mês (1 a 31)
- categoria: use uma das categorias disponíveis (ex: Moradia, Outros)
- conta_id: inclua se o usuário mencionar uma conta bancária
- O sistema vai criar o gasto AUTOMATICAMENTE todo mês nesse dia

Se for PARCELAMENTO (compra parcelada com débito automático mensal):
{{"acao": "parcelamento", "descricao": "Sapato", "valor_parcela": 50.00, "num_parcelas": 10, "data_primeira": "2026-06-05", "categoria": "Roupas"}}
- descricao: nome da compra
- valor_parcela: valor de cada parcela
- num_parcelas: total de parcelas
- data_primeira: data da 1ª parcela no formato YYYY-MM-DD (interprete "a partir do dia 05/06" como 2026-06-05)
- categoria: categoria do gasto
- conta_id: inclua se o usuário mencionar uma conta bancária
- O sistema debita automaticamente cada parcela na mesma data dos meses seguintes

Se for LISTAR parcelamentos ativos:
{{"acao": "listar_parcelamentos"}}

Se for CANCELAR/EXCLUIR parcelamento:
{{"acao": "cancelar_parcelamento", "descricao": "palavra-chave do parcelamento"}}

Se for LISTAR contas mensais:
{{"acao": "listar_contas_mensais"}}

Se for EXCLUIR conta mensal:
{{"acao": "excluir_conta_mensal", "descricao": "palavra-chave da conta"}}

Se for MARCAR UMA conta como paga:
{{"acao": "marcar_conta_paga", "descricao": "palavra-chave da conta"}}

Se for MARCAR TODAS as contas vencidas/com advertência como pagas:
{{"acao": "marcar_todas_pagas"}}

Para outras mensagens:
{{"acao": "mensagem", "texto": "sua resposta aqui"}}

{contas_texto}{contas_instrucao}

Data de hoje: {hoje_brasil().isoformat()}
Responda sempre em português. Seja breve e amigável."""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    # Monta o array de mensagens com histórico + mensagem atual
    messages = list(historico) + [{"role": "user", "content": mensagem}]
    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 500,
        "system": system,
        "messages": messages
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
    """Envia imagem base64 via provedor ativo (Evolution ou Meta)."""
    _wpp_send_image_b64(fone, imagem_b64, caption=caption, filename="relatorio.png")

def enviar_whatsapp(fone, mensagem):
    """Envia mensagem de texto via provedor ativo (Evolution ou Meta)."""
    _wpp_send_text(fone, mensagem)

def analisar_comprovante_claude(imagem_b64, caption="", categorias=None):
    cats_list = categorias if categorias else CATEGORIAS
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
                f"Categorias disponíveis: {', '.join(cats_list)}\n"
                f"Data de hoje: {hoje_brasil().isoformat()}\n"
                f"Use SEMPRE uma das categorias listadas. Se não souber qual, use a última da lista.\n"
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
        cats = get_categorias_cliente(cliente["id"])
        resultado = analisar_comprovante_claude(imagem_b64, caption, categorias=cats)
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
            f"✅ Transação registrada com sucesso!\n\n"
            f"🔍 Tipo: Saída\n"
            f"✏️ Descrição: {resultado['descricao']}\n"
            f"💲 Valor: R$ {float(resultado['valor']):.2f}\n"
            f"📂 Categoria: {resultado['categoria']}\n"
            f"📅 Data: {formatar_data(data_comp)}"
        )
    except Exception as e:
        import logging, traceback
        logging.error(f"Erro ao analisar comprovante: {e}\n{traceback.format_exc()}")
        resposta = "Não consegui ler o comprovante. Tente uma foto mais nítida ou descreva o gasto em texto."
    # Salva comprovante no histórico como contexto
    salvar_historico_conversa(cliente["id"], "user", f"[Comprovante enviado] {caption}" if caption else "[Comprovante enviado]")
    if resposta:
        salvar_historico_conversa(cliente["id"], "assistant", resposta)
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
        cats = get_categorias_cliente(cliente["id"])
        contas = get_contas_cliente(cliente["id"])
        # Carrega histórico da conversa (últimas mensagens das últimas 2 horas)
        historico = buscar_historico_conversa(cliente["id"])
        # Salva a mensagem do usuário no histórico antes de processar
        salvar_historico_conversa(cliente["id"], "user", mensagem)
        resultado = chamar_claude(mensagem, historico=historico, categorias=cats, contas=contas)
        acao = resultado.get("acao")

        if acao == "registrar":
            conta_id = resultado.get("conta_id") or None
            conta_nome = next((c["nome"] for c in contas if c["id"] == conta_id), None) if conta_id else None
            salvar_gasto(
                cliente["id"],
                resultado["descricao"],
                float(resultado["valor"]),
                resultado["categoria"],
                resultado.get("data", hoje_brasil().isoformat()),
                conta_id=conta_id
            )
            data_gasto = resultado.get("data", hoje_brasil().isoformat())
            resposta = (
                f"✅ Transação registrada com sucesso!\n\n"
                f"🔍 Tipo: Saída\n"
                f"✏️ Descrição: {resultado['descricao']}\n"
                f"💲 Valor: R$ {float(resultado['valor']):.2f}\n"
                f"📂 Categoria: {resultado['categoria']}\n"
                f"📅 Data: {formatar_data(data_gasto)}"
            )
            if conta_nome:
                resposta += f"\n🏦 Conta: {conta_nome}"

        elif acao == "registrar_multiplos":
            gastos = resultado.get("gastos", [])
            total = 0.0
            linhas = ["✅ Transações registradas com sucesso!\n"]
            for g in gastos:
                data_g = g.get("data", hoje_brasil().isoformat())
                conta_id_g = g.get("conta_id") or None
                conta_nome_g = next((c["nome"] for c in contas if c["id"] == conta_id_g), None) if conta_id_g else None
                salvar_gasto(
                    cliente["id"],
                    g["descricao"],
                    float(g["valor"]),
                    g["categoria"],
                    data_g,
                    conta_id=conta_id_g
                )
                total += float(g["valor"])
                linha = (
                    f"🔍 Tipo: Saída\n"
                    f"✏️ Descrição: {g['descricao']}\n"
                    f"💲 Valor: R$ {float(g['valor']):.2f}\n"
                    f"📂 Categoria: {g['categoria']}\n"
                    f"📅 Data: {formatar_data(data_g)}"
                )
                if conta_nome_g:
                    linha += f"\n🏦 Conta: {conta_nome_g}"
                linhas.append(linha)
            linhas.append(f"\n💰 Total: R$ {total:.2f}")
            resposta = "\n\n".join(linhas)

        elif acao == "deletar_tudo":
            mes = resultado.get("mes")
            deletar_todos_gastos(cliente["id"], mes)
            if mes:
                resposta = f"🗑️ Todos os gastos de {mes_ano_pt(date.fromisoformat(mes + '-01'))} foram apagados."
            else:
                resposta = "🗑️ Todo o histórico de gastos foi apagado."

        elif acao == "zerar_tudo":
            USE_PG = bool(os.environ.get("DATABASE_URL"))
            conn_z = get_db()
            try:
                # Apaga todos os gastos
                conn_z.execute("DELETE FROM gastos WHERE cliente_id=%s", (cliente["id"],))
                # Apaga todas as rendas
                conn_z.execute("DELETE FROM rendas WHERE cliente_id=%s", (cliente["id"],))
                # Zera renda_mensal estática
                conn_z.execute("UPDATE clientes SET renda_mensal=NULL WHERE id=%s", (cliente["id"],))
                conn_z.commit()
                resposta = "✅ Tudo zerado! Gastos, rendas e saldo foram apagados.\n\nVocê está começando do zero. 🚀"
            except Exception as e_z:
                import logging; logging.error(f"Erro zerar_tudo: {e_z}")
                resposta = "Não consegui apagar tudo. Tente novamente."
            finally:
                try: conn_z.close()
                except: pass

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

        elif acao == "editar_gasto":
            desc        = resultado.get("descricao", "")
            novo_valor  = resultado.get("novo_valor")
            nova_desc   = resultado.get("nova_descricao")
            nova_cat    = resultado.get("nova_categoria")
            nova_data   = resultado.get("nova_data")
            if not desc:
                resposta = "Me diga o nome do gasto que quer corrigir. Ex: 'corrige o uber para R$ 45'."
            else:
                gasto = editar_gasto_por_descricao(
                    cliente["id"], desc,
                    novo_valor=float(novo_valor) if novo_valor is not None else None,
                    nova_descricao=nova_desc,
                    nova_categoria=nova_cat,
                    nova_data=nova_data
                )
                if gasto:
                    resposta = (
                        f"✏️ Gasto atualizado!\n\n"
                        f"📝 Descrição: {gasto['descricao']}\n"
                        f"💲 Valor: R$ {float(gasto['valor']):.2f}\n"
                        f"📂 Categoria: {gasto['categoria']}\n"
                        f"📅 Data: {formatar_data(gasto['data'])}"
                    )
                else:
                    resposta = f"Não encontrei nenhum gasto com '{desc}'. Verifique o nome e tente novamente."

        elif acao == "editar_renda":
            desc       = resultado.get("descricao", "")
            novo_valor = resultado.get("novo_valor")
            nova_desc  = resultado.get("nova_descricao")
            novo_tipo  = resultado.get("novo_tipo")
            nova_data  = resultado.get("nova_data")
            if not desc:
                resposta = "Me diga o nome da renda que quer corrigir. Ex: 'corrige o salário para R$ 3500'."
            else:
                renda = editar_renda_por_descricao(
                    cliente["id"], desc,
                    novo_valor=float(novo_valor) if novo_valor is not None else None,
                    nova_descricao=nova_desc,
                    novo_tipo=novo_tipo,
                    nova_data=nova_data
                )
                if renda:
                    resposta = (
                        f"✏️ Renda atualizada!\n\n"
                        f"📝 Descrição: {renda['descricao']}\n"
                        f"💲 Valor: R$ {float(renda['valor']):.2f}\n"
                        f"📂 Tipo: {'Fixa 💼' if renda['tipo'] == 'fixo' else 'Extra ⚡'}\n"
                        f"📅 Data: {formatar_data(renda['data'])}"
                    )
                else:
                    resposta = f"Não encontrei nenhuma renda com '{desc}'. Verifique o nome e tente novamente."

        elif acao == "dashboard":
            imagem = gerar_imagem_dashboard(cliente["id"])
            if imagem:
                mes_nome = mes_ano_pt()
                enviar_imagem_whatsapp(fone, imagem, f"📊 Seus gastos de {mes_nome}")
                resposta = ""
            else:
                resposta = "Você ainda não tem gastos registrados este mês para gerar o gráfico."

        elif acao == "relatorio":
            import logging
            mes_rel = hoje_brasil().strftime("%Y-%m")
            enviar_whatsapp(fone, "⏳ Gerando seu relatório PDF completo, aguarde um instante...")
            try:
                from relatorio.gerador import gerar_e_enviar_pdf_wpp
                ok = gerar_e_enviar_pdf_wpp(cliente["id"], mes_rel, cliente["whatsapp"])
                if ok:
                    resposta = ""
                else:
                    resposta = "Não consegui enviar o PDF. Tente novamente em instantes."
            except Exception as e:
                logging.error(f"[PDF] Erro ao gerar relatório: {e}")
                resposta = "Ocorreu um erro ao gerar o relatório. Tente novamente."

        elif acao == "relatorio_conta":
            import logging
            mes_rel = hoje_brasil().strftime("%Y-%m")
            conta_nome_busca = dados.get("conta_nome", "").strip().lower()
            # Localiza a conta pelo nome (busca parcial)
            conn_rc = get_db()
            contas_rc = conn_rc.execute(
                "SELECT id, nome FROM contas_bancarias WHERE cliente_id=%s AND ativo=TRUE ORDER BY nome",
                (cliente["id"],)
            ).fetchall()
            conn_rc.close()
            conta_achada = None
            if conta_nome_busca:
                for c in contas_rc:
                    if conta_nome_busca in c["nome"].lower() or c["nome"].lower() in conta_nome_busca:
                        conta_achada = c
                        break
            if not conta_achada and contas_rc:
                # Se não encontrou por nome, tenta correspondência mais flexível
                for c in contas_rc:
                    partes = conta_nome_busca.split()
                    if any(p in c["nome"].lower() for p in partes if len(p) > 2):
                        conta_achada = c
                        break
            if conta_achada:
                enviar_whatsapp(fone, f"⏳ Gerando relatório da conta *{conta_achada['nome']}*, aguarde um instante...")
                try:
                    from relatorio.gerador import gerar_e_enviar_pdf_wpp
                    ok = gerar_e_enviar_pdf_wpp(
                        cliente["id"], mes_rel, cliente["whatsapp"],
                        conta_id=conta_achada["id"]
                    )
                    if ok:
                        resposta = ""
                    else:
                        resposta = "Não consegui enviar o PDF. Tente novamente em instantes."
                except Exception as e:
                    logging.error(f"[PDF] Erro ao gerar relatório por conta: {e}")
                    resposta = "Ocorreu um erro ao gerar o relatório. Tente novamente."
            else:
                nomes = ", ".join(c["nome"] for c in contas_rc) if contas_rc else "nenhuma"
                resposta = f"Não encontrei a conta '{dados.get('conta_nome', '')}'. Suas contas: {nomes}."

        elif acao == "analise":
            gastos = historico_gastos(cliente["id"])
            resposta = gerar_analise_financeira(gastos)

        elif acao == "resumo":
            total, por_cat = resumo_mes(cliente["id"])
            renda_estatica = float(cliente["renda_mensal"]) if cliente.get("renda_mensal") else None
            # Busca rendas do mês atual (com fallback caso tabela não exista ainda)
            rendas_rows = []
            try:
                import logging as _log
                USE_PG = bool(os.environ.get("DATABASE_URL"))
                conn_r = get_db()
                mes_atual = hoje_brasil().strftime("%Y-%m")
                if USE_PG:
                    rendas_rows = conn_r.execute(
                        "SELECT descricao, valor, tipo FROM rendas WHERE cliente_id=%s AND data LIKE %s ORDER BY tipo, valor DESC",
                        (cliente["id"], f"{mes_atual}%")
                    ).fetchall()
                else:
                    rendas_rows = conn_r.execute(
                        "SELECT descricao, valor, tipo FROM rendas WHERE cliente_id=? AND data LIKE ? ORDER BY tipo, valor DESC",
                        (cliente["id"], f"{mes_atual}%")
                    ).fetchall()
                conn_r.close()
                _log.warning(f"[RESUMO] cliente_id={cliente['id']} mes={mes_atual} rendas_rows={[dict(r) for r in rendas_rows]} renda_mensal={cliente.get('renda_mensal')}")
            except Exception as e_renda:
                import logging as _log
                _log.warning(f"[RESUMO] Erro ao buscar rendas: {e_renda}")
            total_renda = sum(float(r["valor"]) for r in rendas_rows)
            renda_fixa = sum(float(r["valor"]) for r in rendas_rows if r["tipo"] == "fixo")
            renda_extra = sum(float(r["valor"]) for r in rendas_rows if r["tipo"] == "extra")
            import logging as _log2; _log2.warning(f"[RESUMO] total_renda={total_renda} renda_fixa={renda_fixa} renda_extra={renda_extra} renda_estatica={renda_estatica}")
            # Se há renda extra na tabela mas a fixa ainda está só no campo legado,
            # soma os dois para não ignorar a renda fixa estática
            if renda_estatica and renda_fixa == 0 and renda_extra > 0:
                renda_ref = renda_estatica + renda_extra
                renda_fixa = renda_estatica   # exibe como fixa no resumo
            elif total_renda > 0:
                renda_ref = total_renda
            else:
                renda_ref = renda_estatica
            linhas = [f"📊 *Resumo de {mes_ano_pt()}*", ""]
            if renda_ref:
                saldo = renda_ref - total
                pct = (total / renda_ref * 100) if renda_ref else 0
                linhas.append(f"💵 *Receitas do mês: R$ {renda_ref:.2f}*")
                linhas.append(f"💸 Gasto: R$ {total:.2f} ({pct:.1f}%)")
                linhas.append(f"{'✅' if saldo >= 0 else '⚠️'} Saldo: R$ {saldo:.2f}")
            else:
                linhas.append(f"💰 Total gasto: R$ {total:.2f}")
                linhas.append("💡 _Dica: informe sua renda com 'recebi meu salário de 3000' para ver o saldo_")
            linhas.append("")
            for c in por_cat:
                linhas.append(f"  • {c['categoria']}: R$ {c['s']:.2f}")
            resposta = "\n".join(linhas)

        elif acao == "registrar_renda":
            valor = float(resultado.get("valor", 0))
            descricao = resultado.get("descricao", "Renda").strip() or "Renda"
            tipo = resultado.get("tipo", "extra")
            data_renda = resultado.get("data", hoje_brasil().isoformat())
            conta_id_renda = resultado.get("conta_id") or None
            conta_nome_renda = next((c["nome"] for c in contas if c["id"] == conta_id_renda), None) if conta_id_renda else None
            if valor > 0:
                # Registra entrada na tabela rendas
                registrar_entrada_renda(cliente["id"], descricao, valor, tipo, data_renda, conta_id=conta_id_renda)
                # Se for fixo, também atualiza renda_mensal de referência
                if tipo == "fixo":
                    salvar_renda(cliente["id"], valor)
                label_tipo = "Renda fixa" if tipo == "fixo" else "Renda extra"
                resposta = (
                    f"✅ Transação registrada com sucesso!\n\n"
                    f"🔍 Tipo: Entrada\n"
                    f"✏️ Descrição: {descricao}\n"
                    f"💲 Valor: R$ {valor:.2f}\n"
                    f"📂 Categoria: {label_tipo}\n"
                    f"📅 Data: {formatar_data(data_renda)}\n\n"
                    f"Envie *resumo* para ver seu saldo do mês!"
                )
                if conta_nome_renda:
                    resposta += f"\n🏦 Conta: {conta_nome_renda}"
            else:
                resposta = "Não consegui identificar o valor da renda. Tente: *recebi meu salário de 3000* ou *freela de 500*"

        elif acao == "conectar_agenda":
            link = gerar_link_agenda(cliente["id"])
            resposta = (
                f"📅 Para conectar seu Google Agenda, clique no link abaixo:\n\n"
                f"{link}\n\n"
                f"Após autorizar, você poderá agendar compromissos direto aqui pelo WhatsApp! 😊"
            )

        elif acao == "agendar":
            if not verificar_agenda_conectada(cliente["id"]):
                link = gerar_link_agenda(cliente["id"])
                resposta = (
                    f"📅 Sua agenda ainda não está conectada. Clique no link abaixo para autorizar:\n\n"
                    f"{link}\n\n"
                    f"Após conectar, envie o agendamento novamente. 😊"
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

        elif acao == "lembrete":
            USE_PG = bool(os.environ.get("DATABASE_URL"))
            import datetime as _datetime
            mensagem_lem = resultado.get("mensagem", "").strip()
            hora_lem = (resultado.get("hora") or "09:00").strip()
            data_lem = resultado.get("data")
            recorrente = resultado.get("recorrente", False)
            dia_mes = resultado.get("dia_mes")  # int ou None — lembrete mensal

            if not mensagem_lem:
                resposta = "Não entendi o lembrete. Tente: *me lembre de todo dia 10 pagar a conta de energia*"
            else:
                # Garante hora no formato HH:MM
                if len(hora_lem) == 4 and ":" not in hora_lem:
                    hora_lem = hora_lem[:2] + ":" + hora_lem[2:]
                # Só define data pontual se não for recorrente diário nem mensal
                if not data_lem and not recorrente and not dia_mes:
                    data_lem = hoje_brasil().isoformat()
                conn_lem = get_db()
                ph = "%s" if USE_PG else "?"
                # Remove lembretes ativos idênticos (mesma mensagem + hora) antes de criar
                if USE_PG:
                    conn_lem.execute(
                        "UPDATE lembretes SET ativo=FALSE WHERE cliente_id=%s AND mensagem ILIKE %s AND hora=%s AND ativo=TRUE",
                        (cliente["id"], mensagem_lem, hora_lem)
                    )
                else:
                    conn_lem.execute(
                        "UPDATE lembretes SET ativo=0 WHERE cliente_id=? AND LOWER(mensagem)=LOWER(?) AND hora=? AND ativo=1",
                        (cliente["id"], mensagem_lem, hora_lem)
                    )
                conn_lem.execute(
                    f"INSERT INTO lembretes (cliente_id, mensagem, hora, data, recorrente, dia_mes) VALUES ({ph},{ph},{ph},{ph},{ph},{ph})",
                    (cliente["id"], mensagem_lem, hora_lem,
                     data_lem if not recorrente and not dia_mes else None,
                     recorrente, dia_mes)
                )
                conn_lem.commit()
                conn_lem.close()

                # ── Auto-cadastra como conta mensal quando tem dia_mes ─────────
                # Lembrete com dia fixo do mês = conta recorrente → registra automaticamente
                if dia_mes:
                    try:
                        import re as _re
                        # Extrai valor do texto do lembrete (ex: "pagar R$ 447,00 seguro")
                        _valor_match = _re.search(r'R\$\s*([\d.,]+)', mensagem_lem)
                        _valor_conta = None
                        if _valor_match:
                            _valor_conta = float(_valor_match.group(1).replace(".", "").replace(",", "."))
                        # Extrai descrição: remove "pagar", "R$ xxx", "todo dia X" do texto
                        _desc = _re.sub(r'(pagar|todo\s*dia\s*\d+|R\$\s*[\d.,]+)', '', mensagem_lem, flags=_re.IGNORECASE).strip()
                        _desc = _re.sub(r'\s+', ' ', _desc).strip(" ,-")
                        if not _desc:
                            _desc = mensagem_lem[:40].strip()
                        # Verifica se já existe conta com descrição similar
                        conn_conta = get_db()
                        if USE_PG:
                            _existe = conn_conta.execute(
                                "SELECT id FROM contas_mensais WHERE cliente_id=%s AND ativo=TRUE AND LOWER(descricao) LIKE %s",
                                (cliente["id"], f"%{_desc[:15].lower()}%")
                            ).fetchone()
                            if not _existe:
                                conn_conta.execute(
                                    "INSERT INTO contas_mensais (cliente_id, descricao, valor, dia_vencimento) VALUES (%s, %s, %s, %s)",
                                    (cliente["id"], _desc, _valor_conta, dia_mes)
                                )
                        else:
                            _existe = conn_conta.execute(
                                "SELECT id FROM contas_mensais WHERE cliente_id=? AND ativo=1 AND LOWER(descricao) LIKE ?",
                                (cliente["id"], f"%{_desc[:15].lower()}%")
                            ).fetchone()
                            if not _existe:
                                conn_conta.execute(
                                    "INSERT INTO contas_mensais (cliente_id, descricao, valor, dia_vencimento) VALUES (?, ?, ?, ?)",
                                    (cliente["id"], _desc, _valor_conta, dia_mes)
                                )
                        conn_conta.commit()
                        conn_conta.close()
                    except Exception as _e_conta:
                        import logging; logging.warning(f"[AUTO-CONTA] Erro ao criar conta mensal: {_e_conta}")
                # ─────────────────────────────────────────────────────────────

                if dia_mes:
                    resposta = (
                        f"⏰ Lembrete mensal criado!\n"
                        f"Todo dia *{dia_mes}* às *{hora_lem}* vou te lembrar de:\n\n"
                        f"_{mensagem_lem}_\n\n"
                        f"Você só precisou cadastrar uma vez — eu lembro todo mês automaticamente! 🗓️\n"
                        f"Para excluir, responda: *excluir lembrete*"
                    )
                elif recorrente:
                    resposta = f"⏰ Lembrete criado!\nTodo dia às *{hora_lem}* vou te lembrar de:\n\n_{mensagem_lem}_\n\nPara excluir, responda: *excluir lembrete*"
                else:
                    try:
                        data_fmt = _datetime.date.fromisoformat(data_lem).strftime("%d/%m/%Y")
                    except Exception:
                        data_fmt = data_lem
                    resposta = f"⏰ Lembrete criado!\nÀs *{hora_lem}* de {data_fmt} vou te lembrar de:\n\n_{mensagem_lem}_\n\nPara excluir, responda: *excluir lembrete*"

        elif acao == "deletar_renda":
            USE_PG = bool(os.environ.get("DATABASE_URL"))
            tipo_del = resultado.get("tipo", "todos").strip()
            descricao_del = resultado.get("descricao", "").strip()
            mes_atual = hoje_brasil().strftime("%Y-%m")
            conn_r = get_db()
            ph = "%s" if USE_PG else "?"
            try:
                # Monta query de acordo com filtros
                if descricao_del:
                    # Tem palavra-chave
                    if USE_PG:
                        rows = conn_r.execute(
                            "SELECT id, descricao, valor FROM rendas WHERE cliente_id=%s AND data LIKE %s AND descricao ILIKE %s",
                            (cliente["id"], f"{mes_atual}%", f"%{descricao_del}%")
                        ).fetchall()
                        if not rows:
                            rows = conn_r.execute(
                                "SELECT id, descricao, valor FROM rendas WHERE cliente_id=%s AND descricao ILIKE %s",
                                (cliente["id"], f"%{descricao_del}%")
                            ).fetchall()
                    else:
                        rows = conn_r.execute(
                            "SELECT id, descricao, valor FROM rendas WHERE cliente_id=? AND descricao LIKE ?",
                            (cliente["id"], f"%{descricao_del}%")
                        ).fetchall()
                elif tipo_del == "todos":
                    if USE_PG:
                        rows = conn_r.execute(
                            "SELECT id, descricao, valor FROM rendas WHERE cliente_id=%s AND data LIKE %s",
                            (cliente["id"], f"{mes_atual}%")
                        ).fetchall()
                    else:
                        rows = conn_r.execute(
                            "SELECT id, descricao, valor FROM rendas WHERE cliente_id=? AND data LIKE ?",
                            (cliente["id"], f"{mes_atual}%")
                        ).fetchall()
                else:
                    if USE_PG:
                        rows = conn_r.execute(
                            "SELECT id, descricao, valor FROM rendas WHERE cliente_id=%s AND data LIKE %s AND tipo=%s",
                            (cliente["id"], f"{mes_atual}%", tipo_del)
                        ).fetchall()
                    else:
                        rows = conn_r.execute(
                            "SELECT id, descricao, valor FROM rendas WHERE cliente_id=? AND data LIKE ? AND tipo=?",
                            (cliente["id"], f"{mes_atual}%", tipo_del)
                        ).fetchall()

                if not rows:
                    resposta = "Não encontrei nenhuma renda para excluir com esse critério. Envie *resumo* para ver suas rendas registradas."
                else:
                    for row in rows:
                        if USE_PG:
                            conn_r.execute("DELETE FROM rendas WHERE id=%s", (row["id"],))
                        else:
                            conn_r.execute("DELETE FROM rendas WHERE id=?", (row["id"],))
                    conn_r.commit()
                    # Recalcula renda_mensal com as rendas fixas que ainda restam no mês
                    mes_atual_str = hoje_brasil().strftime("%Y-%m")
                    total_fixo_restante = conn_r.execute(
                        "SELECT COALESCE(SUM(valor),0) as t FROM rendas WHERE cliente_id=%s AND tipo='fixo' AND data LIKE %s",
                        (cliente["id"], f"{mes_atual_str}%")
                    ).fetchone()["t"]
                    nova_renda_ref = float(total_fixo_restante) if float(total_fixo_restante) > 0 else None
                    if USE_PG:
                        conn_r.execute("UPDATE clientes SET renda_mensal=%s WHERE id=%s", (nova_renda_ref, cliente["id"]))
                    else:
                        conn_r.execute("UPDATE clientes SET renda_mensal=? WHERE id=?", (nova_renda_ref, cliente["id"]))
                    conn_r.commit()
                    if len(rows) == 1:
                        r = rows[0]
                        resposta = f"🗑️ Renda excluída!\n_{r['descricao']}_ — R$ {float(r['valor']):.2f}"
                    else:
                        total_del = sum(float(r["valor"]) for r in rows)
                        resposta = f"🗑️ {len(rows)} rendas excluídas! Total removido: R$ {total_del:.2f}"
            except Exception as e_rd:
                import logging; logging.error(f"Erro deletar renda: {e_rd}")
                resposta = "Não consegui excluir a renda. Tente: *excluir renda extra* ou *apagar renda de freela*"
            finally:
                try: conn_r.close()
                except: pass

        elif acao == "deletar_lembrete":
            USE_PG = bool(os.environ.get("DATABASE_URL"))
            descricao_busca = resultado.get("descricao", "").strip()
            conn_lem = get_db()
            ph = "%s" if USE_PG else "?"
            try:
                if descricao_busca:
                    # Busca por palavra-chave na mensagem
                    if USE_PG:
                        lembretes_ativos = conn_lem.execute(
                            "SELECT id, mensagem, hora FROM lembretes WHERE cliente_id=%s AND ativo=TRUE AND mensagem ILIKE %s",
                            (cliente["id"], f"%{descricao_busca}%")
                        ).fetchall()
                    else:
                        lembretes_ativos = conn_lem.execute(
                            "SELECT id, mensagem, hora FROM lembretes WHERE cliente_id=? AND ativo=1 AND mensagem LIKE ?",
                            (cliente["id"], f"%{descricao_busca}%")
                        ).fetchall()
                else:
                    # Sem palavra-chave: busca o lembrete mais recente ativo
                    if USE_PG:
                        lembretes_ativos = conn_lem.execute(
                            "SELECT id, mensagem, hora FROM lembretes WHERE cliente_id=%s AND ativo=TRUE ORDER BY id DESC LIMIT 1",
                            (cliente["id"],)
                        ).fetchall()
                    else:
                        lembretes_ativos = conn_lem.execute(
                            "SELECT id, mensagem, hora FROM lembretes WHERE cliente_id=? AND ativo=1 ORDER BY id DESC LIMIT 1",
                            (cliente["id"],)
                        ).fetchall()

                if not lembretes_ativos:
                    resposta = "Não encontrei nenhum lembrete ativo para excluir. Envie *meus lembretes* para ver a lista."
                elif len(lembretes_ativos) == 1:
                    lem = lembretes_ativos[0]
                    conn_lem.execute(f"UPDATE lembretes SET ativo=FALSE WHERE id={ph}", (lem["id"],)) if USE_PG else conn_lem.execute("UPDATE lembretes SET ativo=0 WHERE id=?", (lem["id"],))
                    conn_lem.commit()
                    resposta = f"🗑️ Lembrete excluído!\n_{lem['mensagem']}_ (às {lem['hora']})"
                else:
                    # Múltiplos encontrados — exclui todos que batem
                    ids = [l["id"] for l in lembretes_ativos]
                    for lid in ids:
                        if USE_PG:
                            conn_lem.execute("UPDATE lembretes SET ativo=FALSE WHERE id=%s", (lid,))
                        else:
                            conn_lem.execute("UPDATE lembretes SET ativo=0 WHERE id=?", (lid,))
                    conn_lem.commit()
                    nomes = ", ".join([f"_{l['mensagem']}_" for l in lembretes_ativos])
                    resposta = f"🗑️ {len(ids)} lembretes excluídos: {nomes}"
            except Exception as e_del:
                import logging; logging.error(f"Erro deletar lembrete: {e_del}")
                resposta = "Não consegui excluir o lembrete. Tente: *excluir lembrete do médico*"
            finally:
                conn_lem.close()

        elif acao == "listar_lembretes":
            USE_PG = bool(os.environ.get("DATABASE_URL"))
            conn_lem = get_db()
            try:
                if USE_PG:
                    lembretes_ativos = conn_lem.execute(
                        "SELECT mensagem, hora, data, recorrente, dia_mes FROM lembretes WHERE cliente_id=%s AND ativo=TRUE ORDER BY dia_mes NULLS LAST, hora",
                        (cliente["id"],)
                    ).fetchall()
                else:
                    lembretes_ativos = conn_lem.execute(
                        "SELECT mensagem, hora, data, recorrente, dia_mes FROM lembretes WHERE cliente_id=? AND ativo=1 ORDER BY dia_mes, hora",
                        (cliente["id"],)
                    ).fetchall()
                conn_lem.close()
                if not lembretes_ativos:
                    resposta = "Você não tem lembretes ativos no momento.\n\nPara criar um, diga: *me lembre de todo dia 10 pagar a conta de energia*"
                else:
                    linhas = [f"⏰ *Seus lembretes ativos ({len(lembretes_ativos)}):*", ""]
                    for l in lembretes_ativos:
                        if l["dia_mes"]:
                            tipo = f"🗓️ Todo dia {l['dia_mes']} do mês"
                        elif l["recorrente"]:
                            tipo = "🔁 Todo dia"
                        else:
                            tipo = f"📅 {l['data'] or 'hoje'}"
                        linhas.append(f"• _{l['mensagem']}_ — {tipo} às *{l['hora']}*")
                    linhas.append("\nPara excluir, diga: *excluir lembrete do [nome]*")
                    resposta = "\n".join(linhas)
            except Exception as e_list:
                import logging; logging.error(f"Erro listar lembretes: {e_list}")
                resposta = "Não consegui buscar seus lembretes. Tente novamente."
            finally:
                try: conn_lem.close()
                except: pass

        elif acao == "registrar_conta_mensal":
            descricao  = resultado.get("descricao", "").strip() or "Conta"
            valor      = resultado.get("valor")
            dia        = int(resultado.get("dia_vencimento", 1))
            dia        = max(1, min(31, dia))
            categoria  = resultado.get("categoria") or "Outros"
            conta_id   = resultado.get("conta_id") or None
            conta_nome = next((c["nome"] for c in contas if c["id"] == conta_id), None) if conta_id else None
            USE_PG_cm  = bool(os.environ.get("DATABASE_URL"))
            conn_cm    = get_db()
            try:
                if USE_PG_cm:
                    conn_cm.execute(
                        "INSERT INTO contas_mensais (cliente_id, descricao, valor, dia_vencimento, categoria, conta_id, auto_debitar) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (cliente["id"], descricao, valor, dia, categoria, conta_id, True)
                    )
                else:
                    conn_cm.execute(
                        "INSERT INTO contas_mensais (cliente_id, descricao, valor, dia_vencimento, categoria, conta_id, auto_debitar) VALUES (?,?,?,?,?,?,?)",
                        (cliente["id"], descricao, valor, dia, categoria, conta_id, 1)
                    )
                conn_cm.commit()
            finally:
                try: conn_cm.close()
                except: pass
            valor_str = f"R$ {valor:.2f}" if valor else "valor não informado"
            resposta = (
                f"✅ Débito automático cadastrado!\n\n"
                f"📋 *{descricao}*\n"
                f"💲 Valor: {valor_str}\n"
                f"📂 Categoria: {categoria}\n"
                f"📅 Todo dia *{dia}* do mês\n"
                + (f"🏦 Conta: {conta_nome}\n" if conta_nome else "")
                + f"\n💡 O sistema vai lançar esse gasto automaticamente todo mês nessa data e te avisar aqui."
            )

        elif acao == "parcelamento":
            import calendar as _cal_p
            descricao     = resultado.get("descricao", "").strip() or "Compra parcelada"
            valor_parcela = float(resultado.get("valor_parcela") or 0)
            num_parcelas  = int(resultado.get("num_parcelas") or 0)
            data_primeira = resultado.get("data_primeira") or hoje_brasil().isoformat()
            categoria     = resultado.get("categoria") or "Outros"
            conta_id      = resultado.get("conta_id") or None
            conta_nome    = next((c["nome"] for c in contas if c["id"] == conta_id), None) if conta_id else None
            if valor_parcela <= 0 or num_parcelas < 1:
                resposta = "Não entendi os detalhes do parcelamento. Me diga: nome, valor de cada parcela, número de parcelas e data da 1ª parcela."
            else:
                USE_PG_p = bool(os.environ.get("DATABASE_URL"))
                conn_p   = get_db()
                try:
                    conn_p.execute(
                        "INSERT INTO parcelamentos (cliente_id, descricao, valor_parcela, num_parcelas, data_primeira, categoria, conta_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (cliente["id"], descricao, valor_parcela, num_parcelas, data_primeira, categoria, conta_id)
                    )
                    conn_p.commit()
                finally:
                    try: conn_p.close()
                    except: pass
                total = valor_parcela * num_parcelas
                # Calcula datas das primeiras parcelas para mostrar
                from datetime import date as _date_p
                def _data_p(n):
                    primeira = _date_p.fromisoformat(data_primeira)
                    if n == 1: return primeira
                    mes_t = primeira.month + (n - 1)
                    ano_t = primeira.year + (mes_t - 1) // 12
                    mes_t = ((mes_t - 1) % 12) + 1
                    return _date_p(ano_t, mes_t, min(primeira.day, _cal_p.monthrange(ano_t, mes_t)[1]))
                linhas_datas = ""
                for i in range(1, min(4, num_parcelas + 1)):
                    dt = _data_p(i)
                    linhas_datas += f"  {i}ª parcela: {dt.strftime('%d/%m/%Y')}\n"
                if num_parcelas > 3:
                    linhas_datas += f"  ...\n  {num_parcelas}ª parcela: {_data_p(num_parcelas).strftime('%d/%m/%Y')}\n"
                resposta = (
                    f"✅ Parcelamento cadastrado!\n\n"
                    f"🛍️ *{descricao}*\n"
                    f"💲 {num_parcelas}x de R$ {valor_parcela:.2f} = R$ {total:.2f}\n"
                    f"📂 Categoria: {categoria}\n"
                    + (f"🏦 Conta: {conta_nome}\n" if conta_nome else "")
                    + f"\n📅 *Vencimentos:*\n{linhas_datas}"
                    f"\n💡 Cada parcela será lançada automaticamente na data de vencimento com aviso aqui no WhatsApp."
                )

        elif acao == "listar_parcelamentos":
            USE_PG_lp = bool(os.environ.get("DATABASE_URL"))
            conn_lp = get_db()
            try:
                if USE_PG_lp:
                    parcs = conn_lp.execute(
                        "SELECT id, descricao, valor_parcela, num_parcelas, parcelas_pagas, data_primeira, ativo FROM parcelamentos WHERE cliente_id=%s ORDER BY criado_em DESC",
                        (cliente["id"],)
                    ).fetchall()
                else:
                    parcs = conn_lp.execute(
                        "SELECT id, descricao, valor_parcela, num_parcelas, parcelas_pagas, data_primeira, ativo FROM parcelamentos WHERE cliente_id=? ORDER BY criado_em DESC",
                        (cliente["id"],)
                    ).fetchall()
            finally:
                try: conn_lp.close()
                except: pass
            if not parcs:
                resposta = "Você não tem parcelamentos cadastrados.\n\nPara cadastrar, diga:\n_\"comprei sapato em 10x de 50 a partir do dia 05/06\"_"
            else:
                from datetime import date as _date_lp
                import calendar as _cal_lp
                def _prox_data(data_primeira, parcelas_pagas, num_parcelas):
                    proxima = parcelas_pagas + 1
                    if proxima > num_parcelas: return None
                    primeira = _date_lp.fromisoformat(data_primeira)
                    if proxima == 1: return primeira
                    mes_t = primeira.month + (proxima - 1)
                    ano_t = primeira.year + (mes_t - 1) // 12
                    mes_t = ((mes_t - 1) % 12) + 1
                    return _date_lp(ano_t, mes_t, min(primeira.day, _cal_lp.monthrange(ano_t, mes_t)[1]))
                linhas = ["📦 *Seus parcelamentos:*\n"]
                for p in parcs:
                    pagas = p["parcelas_pagas"]
                    total_p = p["num_parcelas"]
                    ativo = p["ativo"]
                    prox = _prox_data(p["data_primeira"], pagas, total_p)
                    status = "✅ Quitado" if pagas >= total_p else ("🔴 Cancelado" if not ativo else f"⏳ {pagas}/{total_p} pagas")
                    prox_str = f" · próxima em {prox.strftime('%d/%m/%Y')}" if prox and ativo else ""
                    linhas.append(f"🛍️ *{p['descricao']}*\n   {total_p}x R$ {float(p['valor_parcela']):.2f} | {status}{prox_str}")
                resposta = "\n\n".join(linhas)

        elif acao == "cancelar_parcelamento":
            desc_c = resultado.get("descricao", "").strip()
            USE_PG_cp = bool(os.environ.get("DATABASE_URL"))
            conn_cp = get_db()
            try:
                if USE_PG_cp:
                    p = conn_cp.execute(
                        "SELECT id, descricao, parcelas_pagas, num_parcelas FROM parcelamentos WHERE cliente_id=%s AND ativo=TRUE AND LOWER(descricao) LIKE LOWER(%s) ORDER BY criado_em DESC LIMIT 1",
                        (cliente["id"], f"%{desc_c}%")
                    ).fetchone()
                    if p:
                        conn_cp.execute("UPDATE parcelamentos SET ativo=FALSE WHERE id=%s", (p["id"],))
                        conn_cp.commit()
                else:
                    p = conn_cp.execute(
                        "SELECT id, descricao, parcelas_pagas, num_parcelas FROM parcelamentos WHERE cliente_id=? AND ativo=1 AND LOWER(descricao) LIKE LOWER(?) ORDER BY criado_em DESC LIMIT 1",
                        (cliente["id"], f"%{desc_c}%")
                    ).fetchone()
                    if p:
                        conn_cp.execute("UPDATE parcelamentos SET ativo=0 WHERE id=?", (p["id"],))
                        conn_cp.commit()
            finally:
                try: conn_cp.close()
                except: pass
            if p:
                restavam = p["num_parcelas"] - p["parcelas_pagas"]
                resposta = (
                    f"🚫 Parcelamento cancelado!\n\n"
                    f"🛍️ *{p['descricao']}*\n"
                    f"📊 Foram pagas {p['parcelas_pagas']}/{p['num_parcelas']} parcelas\n"
                    f"⚠️ As {restavam} parcelas restantes foram canceladas e não serão mais debitadas."
                )
            else:
                resposta = f"Não encontrei nenhum parcelamento ativo com '{desc_c}'."

        elif acao == "listar_contas_mensais":
            import datetime as _dt
            hoje_dt = _dt.date.today()
            mes_atual = hoje_dt.month
            ano_atual = hoje_dt.year
            USE_PG_cm = bool(os.environ.get("DATABASE_URL"))
            conn_cm = get_db()
            try:
                if USE_PG_cm:
                    contas = conn_cm.execute(
                        "SELECT id, descricao, valor, dia_vencimento FROM contas_mensais WHERE cliente_id=%s AND ativo=TRUE ORDER BY dia_vencimento",
                        (cliente["id"],)
                    ).fetchall()
                    # Verifica quais já foram pagas este mês (aparecem em gastos)
                    gastos_mes = conn_cm.execute(
                        "SELECT LOWER(descricao) as desc FROM gastos WHERE cliente_id=%s AND data LIKE %s",
                        (cliente["id"], f"{hoje_dt.strftime('%Y-%m')}%")
                    ).fetchall()
                else:
                    contas = conn_cm.execute(
                        "SELECT id, descricao, valor, dia_vencimento FROM contas_mensais WHERE cliente_id=? AND ativo=1 ORDER BY dia_vencimento",
                        (cliente["id"],)
                    ).fetchall()
                    gastos_mes = conn_cm.execute(
                        "SELECT LOWER(descricao) as desc FROM gastos WHERE cliente_id=? AND data LIKE ?",
                        (cliente["id"], f"{hoje_dt.strftime('%Y-%m')}%")
                    ).fetchall()
            finally:
                try: conn_cm.close()
                except: pass

            if not contas:
                resposta = (
                    "Você ainda não tem contas mensais cadastradas. 📋\n\n"
                    "Para cadastrar, diga:\n"
                    "_\"adiciona conta de luz vence dia 10\"_\n"
                    "_\"aluguel de 1500 reais todo dia 5\"_"
                )
            else:
                mes_str = hoje_dt.strftime("%Y-%m")
                gastos_desc = {g["desc"] for g in gastos_mes}
                # Busca pagamentos explícitos desta tabela (marcados manualmente)
                try:
                    if USE_PG_loc:
                        pagas_ids = {r["conta_id"] for r in conn_cm.execute(
                            "SELECT conta_id FROM contas_pagamentos WHERE cliente_id=%s AND mes=%s AND conta_id IS NOT NULL",
                            (cliente["id"], mes_str)
                        ).fetchall()}
                    else:
                        pagas_ids = {r["conta_id"] for r in conn_cm.execute(
                            "SELECT conta_id FROM contas_pagamentos WHERE cliente_id=? AND mes=? AND conta_id IS NOT NULL",
                            (cliente["id"], mes_str)
                        ).fetchall()}
                except Exception:
                    pagas_ids = set()
                hoje_dia = hoje_dt.day
                meses_pt = ["","Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
                linhas = [f"📋 *Suas contas mensais — {meses_pt[mes_atual]}/{ano_atual}*\n"]
                total_previsto = 0.0
                total_pago = 0.0
                for c in contas:
                    desc = c["descricao"]
                    valor_c = float(c["valor"]) if c["valor"] else None
                    dia_v = c["dia_vencimento"]
                    # Verifica se paga: tabela de pagamentos OU gastos do mês
                    paga_manual = c["id"] in pagas_ids
                    paga_gasto = any(desc.lower() in g or g in desc.lower() for g in gastos_desc)
                    paga = paga_manual or paga_gasto
                    venceu = dia_v < hoje_dia
                    if paga:
                        status = "✅ paga"
                        if valor_c: total_pago += valor_c
                    elif venceu:
                        status = "⚠️ vencida"
                    else:
                        dias_p = dia_v - hoje_dia
                        status = f"🔜 vence em {dias_p}d" if dias_p > 0 else "📌 vence hoje"
                    valor_str = f"R$ {valor_c:.2f}" if valor_c else "—"
                    if valor_c:
                        total_previsto += valor_c
                    linhas.append(f"• *{desc}* — {valor_str} | dia {dia_v} | {status}")
                if total_previsto > 0:
                    linhas.append(f"\n💰 Total previsto: R$ {total_previsto:.2f}")
                    if total_pago > 0:
                        linhas.append(f"✅ Já pago: R$ {total_pago:.2f}")
                        pendente = total_previsto - total_pago
                        if pendente > 0:
                            linhas.append(f"⏳ Pendente: R$ {pendente:.2f}")
                linhas.append("\nPara marcar como paga: _\"paguei a conta de [nome]\"_")
                linhas.append("Para remover: _\"excluir conta da [nome]\"_")
                resposta = "\n".join(linhas)

        elif acao == "excluir_conta_mensal":
            desc_busca = resultado.get("descricao", "").strip().lower()
            USE_PG_cm = bool(os.environ.get("DATABASE_URL"))
            conn_cm = get_db()
            try:
                if USE_PG_cm:
                    conta = conn_cm.execute(
                        "SELECT id, descricao FROM contas_mensais WHERE cliente_id=%s AND ativo=TRUE AND LOWER(descricao) LIKE %s ORDER BY id DESC LIMIT 1",
                        (cliente["id"], f"%{desc_busca}%")
                    ).fetchone()
                    if conta:
                        conn_cm.execute("UPDATE contas_mensais SET ativo=FALSE WHERE id=%s", (conta["id"],))
                        conn_cm.commit()
                        resposta = f"🗑️ Conta *{conta['descricao']}* removida das contas mensais."
                    else:
                        resposta = f"Não encontrei nenhuma conta com \"{desc_busca}\". Envie *minhas contas* para ver a lista."
                else:
                    conta = conn_cm.execute(
                        "SELECT id, descricao FROM contas_mensais WHERE cliente_id=? AND ativo=1 AND LOWER(descricao) LIKE ? ORDER BY id DESC LIMIT 1",
                        (cliente["id"], f"%{desc_busca}%")
                    ).fetchone()
                    if conta:
                        conn_cm.execute("UPDATE contas_mensais SET ativo=0 WHERE id=?", (conta["id"],))
                        conn_cm.commit()
                        resposta = f"🗑️ Conta *{conta['descricao']}* removida das contas mensais."
                    else:
                        resposta = f"Não encontrei nenhuma conta com \"{desc_busca}\". Envie *minhas contas* para ver a lista."
            finally:
                try: conn_cm.close()
                except: pass

        elif acao == "marcar_conta_paga":
            import datetime as _dt
            desc_busca = resultado.get("descricao", "").strip().lower()
            mes_str = _dt.date.today().strftime("%Y-%m")
            USE_PG_mp = bool(os.environ.get("DATABASE_URL"))
            conn_mp = get_db()
            try:
                if USE_PG_mp:
                    conta = conn_mp.execute(
                        "SELECT id, descricao, valor FROM contas_mensais WHERE cliente_id=%s AND ativo=TRUE AND LOWER(descricao) LIKE %s ORDER BY id DESC LIMIT 1",
                        (cliente["id"], f"%{desc_busca}%")
                    ).fetchone()
                else:
                    conta = conn_mp.execute(
                        "SELECT id, descricao, valor FROM contas_mensais WHERE cliente_id=? AND ativo=1 AND LOWER(descricao) LIKE ? ORDER BY id DESC LIMIT 1",
                        (cliente["id"], f"%{desc_busca}%")
                    ).fetchone()
                if conta:
                    if USE_PG_mp:
                        conn_mp.execute(
                            "INSERT INTO contas_pagamentos (cliente_id, conta_id, descricao, mes) VALUES (%s,%s,%s,%s) ON CONFLICT (cliente_id,conta_id,mes) DO NOTHING",
                            (cliente["id"], conta["id"], conta["descricao"], mes_str)
                        )
                    else:
                        conn_mp.execute(
                            "INSERT OR IGNORE INTO contas_pagamentos (cliente_id, conta_id, descricao, mes) VALUES (?,?,?,?)",
                            (cliente["id"], conta["id"], conta["descricao"], mes_str)
                        )
                    conn_mp.commit()
                    valor_str = f" de R$ {float(conta['valor']):.2f}" if conta["valor"] else ""
                    resposta = (
                        f"✅ *{conta['descricao']}*{valor_str} marcada como paga em {mes_str[5:]}/{mes_str[:4]}!\n\n"
                        f"Envie *minhas contas* para ver o resumo atualizado."
                    )
                else:
                    resposta = (
                        f"Não encontrei conta com _\"{desc_busca}\"_ na sua lista.\n"
                        f"Envie *minhas contas* para ver todas as suas contas mensais."
                    )
            finally:
                try: conn_mp.close()
                except: pass

        elif acao == "marcar_todas_pagas":
            import datetime as _dt
            mes_str = _dt.date.today().strftime("%Y-%m")
            hoje_dia = _dt.date.today().day
            USE_PG_mp = bool(os.environ.get("DATABASE_URL"))
            conn_mp = get_db()
            try:
                # Busca contas vencidas (dia_vencimento < hoje) que ainda não foram pagas
                if USE_PG_mp:
                    contas_vencidas = conn_mp.execute(
                        """SELECT cm.id, cm.descricao, cm.valor FROM contas_mensais cm
                           WHERE cm.cliente_id=%s AND cm.ativo=TRUE AND cm.dia_vencimento < %s
                           AND cm.id NOT IN (
                               SELECT conta_id FROM contas_pagamentos
                               WHERE cliente_id=%s AND mes=%s AND conta_id IS NOT NULL
                           )""",
                        (cliente["id"], hoje_dia, cliente["id"], mes_str)
                    ).fetchall()
                    for c in contas_vencidas:
                        conn_mp.execute(
                            "INSERT INTO contas_pagamentos (cliente_id, conta_id, descricao, mes) VALUES (%s,%s,%s,%s) ON CONFLICT (cliente_id,conta_id,mes) DO NOTHING",
                            (cliente["id"], c["id"], c["descricao"], mes_str)
                        )
                else:
                    contas_vencidas = conn_mp.execute(
                        """SELECT cm.id, cm.descricao, cm.valor FROM contas_mensais cm
                           WHERE cm.cliente_id=? AND cm.ativo=1 AND cm.dia_vencimento < ?
                           AND cm.id NOT IN (
                               SELECT conta_id FROM contas_pagamentos
                               WHERE cliente_id=? AND mes=? AND conta_id IS NOT NULL
                           )""",
                        (cliente["id"], hoje_dia, cliente["id"], mes_str)
                    ).fetchall()
                    for c in contas_vencidas:
                        conn_mp.execute(
                            "INSERT OR IGNORE INTO contas_pagamentos (cliente_id, conta_id, descricao, mes) VALUES (?,?,?,?)",
                            (cliente["id"], c["id"], c["descricao"], mes_str)
                        )
                conn_mp.commit()
                if not contas_vencidas:
                    resposta = "Não há contas vencidas pendentes este mês. ✅"
                else:
                    total = sum(float(c["valor"]) for c in contas_vencidas if c["valor"])
                    nomes = "\n".join(f"✅ {c['descricao']}" for c in contas_vencidas)
                    total_str = f"\n\n💰 Total quitado: R$ {total:.2f}" if total > 0 else ""
                    resposta = (
                        f"✅ *{len(contas_vencidas)} conta(s) marcadas como pagas!*\n\n"
                        f"{nomes}{total_str}\n\n"
                        f"Envie *minhas contas* para ver o resumo atualizado."
                    )
            finally:
                try: conn_mp.close()
                except: pass

        elif acao == "compromissos_hoje":
            import datetime as _dt
            from datetime import timezone as _tz, timedelta as _td
            hoje_dt = _dt.date.today()
            hoje_str = hoje_dt.strftime("%d/%m/%Y")
            dias_semana = ["Segunda","Terça","Quarta","Quinta","Sexta","Sábado","Domingo"]
            dia_semana = dias_semana[hoje_dt.weekday()]
            USE_PG_loc = bool(os.environ.get("DATABASE_URL"))
            linhas = [f"📅 *Seus compromissos de hoje — {dia_semana}, {hoje_str}*", ""]

            # ── Lembretes de hoje ───────────────────────────────────────────
            conn_c = get_db()
            try:
                hoje_iso = hoje_dt.isoformat()
                dia_mes_hoje = int(hoje_dt.strftime("%d"))
                dia_semana_hoje = hoje_dt.weekday()  # 0=seg … 6=dom
                if USE_PG_loc:
                    lems = conn_c.execute("""
                        SELECT mensagem, hora FROM lembretes
                        WHERE cliente_id=%s AND ativo=TRUE
                          AND (
                            data = %s
                            OR recorrente = TRUE
                            OR dia_mes = %s
                          )
                        ORDER BY hora
                    """, (cliente["id"], hoje_iso, dia_mes_hoje)).fetchall()
                else:
                    lems = conn_c.execute("""
                        SELECT mensagem, hora FROM lembretes
                        WHERE cliente_id=? AND ativo=1
                          AND (data=? OR recorrente=1 OR dia_mes=?)
                        ORDER BY hora
                    """, (cliente["id"], hoje_iso, dia_mes_hoje)).fetchall()
            except Exception as _e_lem:
                import logging; logging.error(f"[COMPROMISSOS] lembretes: {_e_lem}")
                lems = []
            finally:
                try: conn_c.close()
                except: pass

            if lems:
                linhas.append("⏰ *Lembretes:*")
                for l in lems:
                    linhas.append(f"  • {l['mensagem']} — *{l['hora']}*")
                linhas.append("")

            # ── Eventos Google Calendar ─────────────────────────────────────
            eventos = listar_eventos_google_hoje(cliente["id"])
            if eventos is None:
                # Agenda não conectada
                if not lems:
                    linhas.append("Você não tem lembretes para hoje.")
                linhas.append("")
                linhas.append("📌 _Sua agenda Google não está conectada._")
                linhas.append(f"Conecte em: {gerar_link_agenda(cliente['id'])}")
            elif eventos:
                linhas.append("🗓️ *Eventos na agenda:*")
                for ev in eventos:
                    linhas.append(f"  • {ev['titulo']} — *{ev['hora']}*")
            else:
                if not lems:
                    linhas.append("Você não tem compromissos agendados para hoje. 😊")
                else:
                    linhas.append("🗓️ _Nenhum evento na agenda hoje._")

            resposta = "\n".join(linhas)

        else:
            resposta = resultado.get("texto", "Como posso te ajudar?")

    except Exception as e:
        import logging, traceback
        logging.error(f"Erro agente: {e}\n{traceback.format_exc()}")
        resposta = "Desculpe, não consegui processar sua mensagem. Tente novamente."

    # Salva a resposta do assistente no histórico
    if resposta:
        salvar_historico_conversa(cliente["id"], "assistant", resposta)

    enviar_whatsapp(fone, resposta)
    return resposta
