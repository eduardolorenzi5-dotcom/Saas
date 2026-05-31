"""
Gerador de relatório financeiro em PDF — Controla Fácil
Usa matplotlib (gráficos 300dpi) + reportlab (composição PDF)
"""
import os, sys, io, calendar
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import get_db

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "relatorios")

BRAND_DARK    = "#15172b"
BRAND_GREEN   = "#16a34a"
BRAND_PRIMARY = "#16a34a"   # cor primária da marca (verde, igual ao dashboard)
BRAND_LIGHT   = "#f5f6fa"
BRAND_GRAY    = "#6b7280"

# Paleta do gráfico: começa no verde da marca e segue com cores bem contrastantes
CHART_COLORS = [
    "#16a34a", "#f59e0b", "#0ea5e9", "#ef4444",
    "#8b5cf6", "#14b8a6", "#ec4899", "#f97316",
    "#84cc16", "#64748b",
]

MESES_PT = {
    1:"Janeiro",2:"Fevereiro",3:"Março",4:"Abril",
    5:"Maio",6:"Junho",7:"Julho",8:"Agosto",
    9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro"
}


def _donut_chart(por_cat, total):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np

    # Filtra apenas valores positivos — matplotlib não aceita negativos/zero em pie
    dados = [(c["categoria"], float(c["total"])) for c in por_cat if float(c["total"]) > 0]
    if not dados:
        return None
    labels = [d[0] for d in dados]
    values = [d[1] for d in dados]
    colors = CHART_COLORS[:len(labels)]

    fig, ax = plt.subplots(figsize=(7, 4.5), facecolor="white")

    wedges, _ = ax.pie(
        values, colors=colors, startangle=90,
        wedgeprops=dict(width=0.55, edgecolor="white", linewidth=2.5),
        counterclock=False,
    )

    # Centro do donut
    ax.text(0, 0.08, "Total", ha="center", va="center",
            fontsize=10, color=BRAND_GRAY, fontweight="normal")
    ax.text(0, -0.18, f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            ha="center", va="center", fontsize=13, color=BRAND_DARK, fontweight="bold")

    # Legenda personalizada
    patches = [
        mpatches.Patch(color=colors[i],
                       label=f"{labels[i]}  R$ {values[i]:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        for i in range(len(labels))
    ]
    ax.legend(handles=patches, loc="center left", bbox_to_anchor=(0.88, 0.5),
              fontsize=9, frameon=False, labelspacing=0.7)

    ax.set_aspect("equal")
    plt.tight_layout(pad=1.2)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _bar_diario_chart(gastos, mes):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    import numpy as np

    ano, m = int(mes[:4]), int(mes[5:])
    dias_no_mes = calendar.monthrange(ano, m)[1]

    gastos_por_dia = {}
    for g in gastos:
        d = int(g["data"].split("-")[2])
        gastos_por_dia[d] = gastos_por_dia.get(d, 0) + float(g["valor"])

    dias = list(range(1, dias_no_mes + 1))
    valores = [gastos_por_dia.get(d, 0) for d in dias]

    fig, ax = plt.subplots(figsize=(9, 3), facecolor="white")
    bars = ax.bar(dias, valores, color=BRAND_PRIMARY, alpha=0.85, width=0.7, zorder=3)

    # Destaca barras com valores
    for bar, val in zip(bars, valores):
        if val > 0:
            bar.set_color(BRAND_GREEN)
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(valores) * 0.02,
                    f"{val:,.0f}".replace(",", "."),
                    ha="center", va="bottom", fontsize=6.5, color=BRAND_DARK, fontweight="600")

    ax.set_xlim(0.5, dias_no_mes + 0.5)
    ax.set_xticks(dias)
    ax.tick_params(axis="x", labelsize=7.5, colors=BRAND_GRAY)
    ax.tick_params(axis="y", labelsize=8, colors=BRAND_GRAY)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"R${x:,.0f}".replace(",", ".")))
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color="#f0f0f0", linewidth=0.8)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color("#e5e7eb")
    ax.set_facecolor("white")
    plt.tight_layout(pad=1.0)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _hbar_categorias_chart(por_cat, total):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Filtra apenas valores positivos para evitar barras negativas no gráfico
    dados = [(c["categoria"], float(c["total"])) for c in por_cat if float(c["total"]) > 0][:8]
    if not dados:
        return None
    labels = [d[0] for d in dados]
    values = [d[1] for d in dados]
    colors = CHART_COLORS[:len(labels)]

    labels_rev = labels[::-1]
    values_rev = values[::-1]
    colors_rev = colors[::-1]

    fig, ax = plt.subplots(figsize=(7, max(2.5, len(labels) * 0.55)), facecolor="white")
    bars = ax.barh(labels_rev, values_rev, color=colors_rev, alpha=0.9, height=0.6)

    for bar, val in zip(bars, values_rev):
        ax.text(bar.get_width() + max(values) * 0.02, bar.get_y() + bar.get_height() / 2,
                f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                va="center", fontsize=8.5, color=BRAND_DARK, fontweight="600")

    ax.set_xlim(0, max(values) * 1.28)
    ax.tick_params(axis="y", labelsize=9, colors=BRAND_DARK)
    ax.tick_params(axis="x", labelsize=7.5, colors=BRAND_GRAY)
    ax.xaxis.set_visible(False)
    ax.spines[["top", "right", "bottom"]].set_visible(False)
    ax.spines["left"].set_color("#e5e7eb")
    ax.set_facecolor("white")
    plt.tight_layout(pad=1.0)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def gerar_pdf(cliente_id, mes, conta_id=None):
    """
    Gera PDF do relatório financeiro.
    - conta_id=None  → relatório geral (todos os gastos do mês)
    - conta_id=<int> → relatório filtrado por conta bancária
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                     Paragraph, Spacer, Image, HRFlowable,
                                     PageBreak, KeepTogether)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate
    from reportlab.platypus.frames import Frame

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    conn = get_db()
    cliente = conn.execute("SELECT * FROM clientes WHERE id=%s", (cliente_id,)).fetchone()

    # Monta filtro de conta
    conta_nome = None
    if conta_id:
        c = conn.execute("SELECT nome FROM contas_bancarias WHERE id=%s AND cliente_id=%s",
                         (conta_id, cliente_id)).fetchone()
        conta_nome = c["nome"] if c else None
        conta_filtro_sql   = "AND conta_id=%s"
        conta_filtro_params_g = (cliente_id, f"{mes}%", conta_id)
        conta_filtro_params_s = (cliente_id, f"{mes}%", conta_id)
    else:
        conta_filtro_sql   = ""
        conta_filtro_params_g = (cliente_id, f"{mes}%")
        conta_filtro_params_s = (cliente_id, f"{mes}%")

    gastos  = conn.execute(
        f"SELECT * FROM gastos WHERE cliente_id=%s AND data LIKE %s {conta_filtro_sql} ORDER BY data, categoria",
        conta_filtro_params_g
    ).fetchall()
    por_cat = conn.execute(
        f"SELECT categoria, SUM(valor) as total, COUNT(*) as qtd FROM gastos "
        f"WHERE cliente_id=%s AND data LIKE %s {conta_filtro_sql} GROUP BY categoria ORDER BY total DESC",
        conta_filtro_params_g
    ).fetchall()
    total = float(conn.execute(
        f"SELECT COALESCE(SUM(valor),0) as t FROM gastos WHERE cliente_id=%s AND data LIKE %s {conta_filtro_sql}",
        conta_filtro_params_g
    ).fetchone()["t"])
    renda = float(cliente["renda_mensal"]) if cliente.get("renda_mensal") else None
    conn.close()

    ano, m_num = int(mes[:4]), int(mes[5:])
    mes_nome = f"{MESES_PT[m_num]} {ano}"
    if conta_id:
        nome_arquivo = f"relatorio_{cliente_id}_{mes}_conta{conta_id}.pdf"
    else:
        nome_arquivo = f"relatorio_{cliente_id}_{mes}.pdf"
    caminho = os.path.join(OUTPUT_DIR, nome_arquivo)

    # Estilos
    W, H = A4
    DARK  = colors.HexColor(BRAND_DARK)
    GREEN = colors.HexColor(BRAND_GREEN)
    PURP  = colors.HexColor(BRAND_PRIMARY)
    LIGHT = colors.HexColor(BRAND_LIGHT)
    GRAY  = colors.HexColor(BRAND_GRAY)

    def make_style(name, **kw):
        base = getSampleStyleSheet()["Normal"]
        return ParagraphStyle(name, parent=base, **kw)

    s_title    = make_style("title",    fontSize=22, textColor=colors.white, fontName="Helvetica-Bold", leading=26)
    s_subtitle = make_style("subtitle", fontSize=11, textColor=colors.HexColor("#86efac"), leading=14)
    s_client   = make_style("client",   fontSize=13, textColor=colors.white, leading=16)
    s_section  = make_style("section",  fontSize=13, textColor=DARK, fontName="Helvetica-Bold", spaceBefore=12, spaceAfter=6)
    s_body     = make_style("body",     fontSize=9,  textColor=GRAY, leading=13)
    s_center   = make_style("center",   fontSize=9,  textColor=GRAY, alignment=TA_CENTER)

    # Header frame builder
    def _header(canvas, doc):
        canvas.saveState()
        # Barra superior verde
        canvas.setFillColor(DARK)
        canvas.rect(0, H - 52, W, 52, fill=1, stroke=0)
        canvas.setFillColor(GREEN)
        canvas.rect(0, H - 52, 6, 52, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawString(22, H - 32, "Controla Fácil")
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.HexColor("#9ca3af"))
        _subtitulo = f"Relatório Financeiro — {mes_nome}  ·  {cliente['nome']}"
        if conta_nome:
            _subtitulo += f"  ·  Conta: {conta_nome}"
        canvas.drawString(22, H - 46, _subtitulo)
        # Rodapé
        canvas.setFillColor(colors.HexColor("#f3f4f6"))
        canvas.rect(0, 0, W, 32, fill=1, stroke=0)
        canvas.setFillColor(GRAY)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(2*cm, 12, "Controla Fácil — controlafacilai.com.br")
        canvas.drawRightString(W - 2*cm, 12, f"Página {doc.page}")
        canvas.restoreState()

    doc = BaseDocTemplate(
        caminho, pagesize=A4,
        rightMargin=1.8*cm, leftMargin=1.8*cm,
        topMargin=2.2*cm, bottomMargin=1.5*cm,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  doc.width, doc.height, id="main")
    doc.addPageTemplates([PageTemplate(id="main", frames=frame, onPage=_header)])

    story = []
    usable_w = W - 3.6*cm

    # ── CAPA ──────────────────────────────────────────────────────────
    _titulo_capa = "Relatório por Conta" if conta_nome else "Relatório Financeiro"
    capa_data = [[
        Paragraph(_titulo_capa, s_title),
    ]]
    capa_bg = Table(capa_data, colWidths=[usable_w])
    capa_bg.setStyle(TableStyle([
        ("BACKGROUND",     (0,0), (-1,-1), DARK),
        ("LEFTPADDING",    (0,0), (-1,-1), 20),
        ("RIGHTPADDING",   (0,0), (-1,-1), 20),
        ("TOPPADDING",     (0,0), (-1,-1), 22),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 8),
        ("ROUNDEDCORNERS", (0,0), (-1,-1), [8,8,8,8]),
    ]))
    story.append(capa_bg)

    _info_right = mes_nome
    if conta_nome:
        _info_right = f"{mes_nome}<br/><font size=9 color='#86efac'>Conta: {conta_nome}</font>"
    info_data = [[
        Paragraph(f"<b>{cliente['nome']}</b>", s_client),
        Paragraph(_info_right, make_style("mn", fontSize=11, textColor=GREEN, alignment=TA_RIGHT)),
    ]]
    info_tbl = Table(info_data, colWidths=[usable_w*0.6, usable_w*0.4])
    info_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), DARK),
        ("LEFTPADDING",   (0,0), (-1,-1), 20),
        ("RIGHTPADDING",  (0,0), (-1,-1), 20),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 18),
        ("VALIGN",        (0,0), (-1,-1), "BOTTOM"),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 0.4*cm))

    # ── CARDS DE RESUMO ───────────────────────────────────────────────
    def make_card(label, value, sub="", color=BRAND_DARK, bg="#ffffff", border=BRAND_PRIMARY, value_size=16):
        c_label = make_style(f"cl_{label}", fontSize=8, textColor=colors.HexColor("#9ca3af"),
                             fontName="Helvetica-Bold", leading=11)
        c_val   = make_style(f"cv_{label}", fontSize=value_size, textColor=colors.HexColor(color),
                             fontName="Helvetica-Bold", leading=value_size + 3)
        c_sub   = make_style(f"cs_{label}", fontSize=7.5, textColor=GRAY, leading=10)
        inner = [
            [Paragraph(label.upper(), c_label)],
            [Paragraph(value, c_val)],
            [Paragraph(sub or "&nbsp;", c_sub)],
        ]
        t = Table(inner, colWidths=[(usable_w - 0.5*cm) / 4 - 0.4*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND",     (0,0), (-1,-1), colors.HexColor(bg)),
            ("LEFTPADDING",    (0,0), (-1,-1), 11),
            ("RIGHTPADDING",   (0,0), (-1,-1), 11),
            ("TOPPADDING",     (0,0), (0,0), 12),
            ("TOPPADDING",     (0,1), (-1,-1), 4),
            ("BOTTOMPADDING",  (0,0), (-1,-2), 2),
            ("BOTTOMPADDING",  (0,-1), (-1,-1), 12),
            ("LINEBELOW",      (0,0), (-1,0), 3, colors.HexColor(border)),
            ("BOX",            (0,0), (-1,-1), 0.6, colors.HexColor("#e8eaf0")),
            ("ROUNDEDCORNERS", (0,0), (-1,-1), [7,7,7,7]),
        ]))
        return t

    fmt = lambda v: f"R$ {v:,.2f}".replace(",","X").replace(".",",").replace("X",".")
    pct = lambda: f"{total/renda*100:.0f}% da renda" if renda else ""

    card_total = make_card("Total gasto", fmt(total), f"{len(gastos)} transações", "#dc2626", "#ffffff", "#dc2626")
    if renda:
        card_renda  = make_card("Renda mensal", fmt(renda), "cadastrada no sistema", BRAND_GREEN, "#ffffff", BRAND_GREEN)
        saldo = renda - total
        card_saldo  = make_card("Saldo disponível", fmt(saldo),
                                f"{'dentro' if saldo >= 0 else 'acima'} do orçamento",
                                BRAND_GREEN if saldo >= 0 else "#dc2626", "#ffffff",
                                BRAND_GREEN if saldo >= 0 else "#dc2626")
    else:
        card_renda  = make_card("Renda mensal", "Não cadastrada", "envie 'meu salário é X'", BRAND_GRAY, "#f9fafb", BRAND_GRAY, value_size=12)
        card_saldo  = make_card("Categorias", str(len(por_cat)), "diferentes este mês", BRAND_PRIMARY, "#ffffff", BRAND_PRIMARY)

    top_cat = (por_cat[0]["categoria"] if por_cat else "—")[:18]
    top_val = fmt(float(por_cat[0]["total"])) if por_cat else ""
    card_top = make_card("Maior categoria", top_cat, top_val, BRAND_PRIMARY, "#ffffff", BRAND_PRIMARY, value_size=13)

    cards_row = Table([[card_total, card_renda, card_saldo, card_top]],
                      colWidths=[(usable_w - 0.45*cm) / 4] * 4,
                      hAlign="LEFT")
    cards_row.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("ALIGN",        (0,0), (-1,-1), "LEFT"),
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
        ("COLPADDING",   (0,0), (-1,-1), 6),
    ]))
    story.append(cards_row)
    story.append(Spacer(1, 0.5*cm))

    # ── GRÁFICO DONUT ─────────────────────────────────────────────────
    if por_cat:
        donut_buf = _donut_chart(por_cat, total)
        if donut_buf:
            story.append(Paragraph("Gastos por categoria", s_section))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e5e7eb"), spaceAfter=8))
            img_donut = Image(donut_buf, width=usable_w, height=usable_w * 0.48)
            story.append(img_donut)
            story.append(Spacer(1, 0.4*cm))

    # ── GRÁFICO DE BARRAS DIÁRIO ──────────────────────────────────────
    if gastos:
        story.append(Paragraph("Gastos por dia", s_section))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e5e7eb"), spaceAfter=8))

        bar_buf = _bar_diario_chart(gastos, mes)
        img_bar = Image(bar_buf, width=usable_w, height=usable_w * 0.3)
        story.append(img_bar)
        story.append(Spacer(1, 0.4*cm))

    # ── RANKING CATEGORIAS ────────────────────────────────────────────
    if len(por_cat) > 1:
        hbar_buf = _hbar_categorias_chart(por_cat, total)
        if hbar_buf:
            story.append(Paragraph("Ranking de categorias", s_section))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e5e7eb"), spaceAfter=8))
            h_ratio = max(2.5, len(por_cat) * 0.55) / 7
            img_hbar = Image(hbar_buf, width=usable_w, height=usable_w * h_ratio)
            story.append(img_hbar)
            story.append(Spacer(1, 0.4*cm))

    # ── BARRA DE ORÇAMENTO ────────────────────────────────────────────
    if renda and total > 0:
        pct_val = min(total / renda * 100, 100)
        bar_color = GREEN if total <= renda else colors.HexColor("#dc2626")
        orcamento_data = [
            [Paragraph(f"<b>Orçamento</b>: {fmt(total)} de {fmt(renda)} ({total/renda*100:.1f}% usado)",
                       make_style("orc", fontSize=9, textColor=DARK))],
        ]
        orcamento_tbl = Table(orcamento_data, colWidths=[usable_w])
        orcamento_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), colors.HexColor("#f9fafb")),
            ("LEFTPADDING",   (0,0), (-1,-1), 12),
            ("TOPPADDING",    (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]))
        story.append(orcamento_tbl)

        # Barra de progresso
        filled_w = usable_w * pct_val / 100
        prog_data = [[""]]
        prog_tbl = Table(prog_data, colWidths=[usable_w])
        prog_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), colors.HexColor("#e5e7eb")),
            ("ROWHEIGHT",     (0,0), (-1,-1), 8),
            ("LEFTPADDING",   (0,0), (-1,-1), 0),
            ("RIGHTPADDING",  (0,0), (-1,-1), 0),
            ("TOPPADDING",    (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ]))
        story.append(prog_tbl)
        story.append(Spacer(1, 0.5*cm))

    # ── TABELA DE TRANSAÇÕES ──────────────────────────────────────────
    if gastos:
        story.append(PageBreak())
        story.append(Paragraph("Todas as transações", s_section))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e5e7eb"), spaceAfter=8))

        th_style = make_style("th", fontSize=8.5, textColor=colors.white, fontName="Helvetica-Bold")
        td_style = make_style("td", fontSize=8.5, textColor=DARK, leading=12)
        td_gray  = make_style("tdg", fontSize=8, textColor=GRAY, leading=12)

        tx_data = [[
            Paragraph("Data", th_style),
            Paragraph("Descrição", th_style),
            Paragraph("Categoria", th_style),
            Paragraph("Fonte", th_style),
            Paragraph("Valor", make_style("thr", fontSize=8.5, textColor=colors.white,
                                          fontName="Helvetica-Bold", alignment=TA_RIGHT)),
        ]]
        for i, g in enumerate(gastos):
            data_fmt = "/".join(g["data"].split("-")[::-1])
            fonte = "WhatsApp" if g["fonte"] == "whatsapp" else g["fonte"].capitalize()
            tx_data.append([
                Paragraph(data_fmt, td_gray),
                Paragraph(g["descricao"][:45], td_style),
                Paragraph(g["categoria"], td_style),
                Paragraph(fonte, td_gray),
                Paragraph(fmt(float(g["valor"])),
                          make_style(f"val{i}", fontSize=8.5, textColor=DARK,
                                     fontName="Helvetica-Bold", alignment=TA_RIGHT)),
            ])
        # Linha de total
        tx_data.append([
            Paragraph("", td_style),
            Paragraph("", td_style),
            Paragraph("", td_style),
            Paragraph("TOTAL", make_style("tot", fontSize=9, textColor=DARK, fontName="Helvetica-Bold")),
            Paragraph(fmt(total), make_style("totv", fontSize=9, textColor=colors.HexColor(BRAND_GREEN),
                                             fontName="Helvetica-Bold", alignment=TA_RIGHT)),
        ])

        col_w = [1.8*cm, 7.5*cm, 3.2*cm, 2.2*cm, 2.8*cm]
        tx_tbl = Table(tx_data, colWidths=col_w, repeatRows=1)
        row_styles = [
            ("BACKGROUND",    (0,0), (-1,0), DARK),
            ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
            ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
            ("TOPPADDING",    (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING",   (0,0), (-1,-1), 8),
            ("RIGHTPADDING",  (0,0), (-1,-1), 8),
            ("GRID",          (0,0), (-1,-2), 0.4, colors.HexColor("#f0f0f0")),
            ("LINEABOVE",     (0,-1), (-1,-1), 1.2, colors.HexColor("#e5e7eb")),
            ("BACKGROUND",    (0,-1), (-1,-1), colors.HexColor("#f9fafb")),
        ]
        for i in range(1, len(tx_data) - 1):
            if i % 2 == 0:
                row_styles.append(("BACKGROUND", (0,i), (-1,i), colors.HexColor("#f9fafb")))
        tx_tbl.setStyle(TableStyle(row_styles))
        story.append(tx_tbl)

    doc.build(story)
    return caminho


def gerar_e_enviar_pdf_wpp(cliente_id, mes, whatsapp, conta_id=None):
    """Gera o PDF e envia pelo WhatsApp via Evolution API. Retorna True/False."""
    import base64, requests as _req, logging, os

    caminho = gerar_pdf(cliente_id, mes, conta_id=conta_id)
    ev_url  = os.environ.get("EVOLUTION_URL", "").rstrip("/")
    ev_inst = os.environ.get("EVOLUTION_INSTANCE", "")
    ev_key  = os.environ.get("EVOLUTION_KEY", "")
    if not ev_url or not ev_inst or not ev_key:
        logging.warning("[PDF] EVOLUTION_* não configurados")
        return False

    numero = "".join(c for c in (whatsapp or "") if c.isdigit())
    if not numero:
        return False

    ano, m_num = int(mes[:4]), int(mes[5:])
    mes_nome = f"{MESES_PT[m_num]} {ano}"

    # Descobre nome da conta se filtrado
    conta_label = ""
    if conta_id:
        try:
            from db import get_db as _get_db
            _conn = _get_db()
            _c = _conn.execute("SELECT nome FROM contas_bancarias WHERE id=%s", (conta_id,)).fetchone()
            _conn.close()
            if _c:
                conta_label = f" — {_c['nome']}"
        except Exception:
            pass

    with open(caminho, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    caption = f"📊 Seu relatório financeiro{conta_label} de *{mes_nome}* está pronto!"
    file_name = f"relatorio_{mes_nome}{conta_label}.pdf".replace(" ", "_")

    payload = {
        "number": numero,
        "mediatype": "document",
        "mimetype": "application/pdf",
        "caption": caption,
        "media": b64,
        "fileName": file_name,
    }
    try:
        r = _req.post(
            f"{ev_url}/message/sendMedia/{ev_inst}",
            headers={"apikey": ev_key, "Content-Type": "application/json"},
            json=payload, timeout=30,
        )
        logging.info(f"[PDF] Enviado para {numero} — status {r.status_code}")
        return r.status_code in (200, 201)
    except Exception as e:
        logging.error(f"[PDF] Falha ao enviar para {numero}: {e}")
        return False
