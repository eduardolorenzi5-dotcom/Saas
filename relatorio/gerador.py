"""
Gerador de relatório mensal em PDF.
Usa reportlab para gerar PDF com tabela de gastos e resumo por categoria.
"""
import os, sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import get_db

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "relatorios")

def gerar_pdf(cliente_id, mes):
    """Gera PDF do relatório mensal e retorna o caminho do arquivo."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    conn = get_db()
    cliente = conn.execute("SELECT * FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
    gastos  = conn.execute(
        "SELECT * FROM gastos WHERE cliente_id=%s AND data LIKE %s ORDER BY data, categoria",
        (cliente_id, f"{mes}%")
    ).fetchall()
    por_cat = conn.execute(
        "SELECT categoria, SUM(valor) as total, COUNT(*) as qtd FROM gastos WHERE cliente_id=%s AND data LIKE %s GROUP BY categoria ORDER BY total DESC",
        (cliente_id, f"{mes}%")
    ).fetchall()
    total = conn.execute(
        "SELECT COALESCE(SUM(valor),0) as t FROM gastos WHERE cliente_id=%s AND data LIKE %s",
        (cliente_id, f"{mes}%")
    ).fetchone()["t"]
    conn.close()

    nome_arquivo = f"relatorio_{cliente_id}_{mes}.pdf"
    caminho = os.path.join(OUTPUT_DIR, nome_arquivo)

    doc = SimpleDocTemplate(caminho, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    titulo_style = ParagraphStyle("titulo", parent=styles["Heading1"], fontSize=18, spaceAfter=6)
    sub_style    = ParagraphStyle("sub", parent=styles["Normal"], fontSize=11, textColor=colors.HexColor("#666666"), spaceAfter=20)
    sec_style    = ParagraphStyle("sec", parent=styles["Heading2"], fontSize=13, spaceBefore=16, spaceAfter=8)

    mes_fmt = datetime.strptime(mes, "%Y-%m").strftime("%B de %Y").capitalize()
    story = [
        Paragraph("GastosAI", titulo_style),
        Paragraph(f"Relatório financeiro — {mes_fmt}", sub_style),
        Paragraph(f"Cliente: {cliente['nome']}", styles["Normal"]),
        Spacer(1, 0.5*cm),
    ]

    # Resumo por categoria
    story.append(Paragraph("Resumo por categoria", sec_style))
    cat_data = [["Categoria", "Qtd. registros", "Total (R$)"]]
    for c in por_cat:
        cat_data.append([c["categoria"], str(c["qtd"]), f"R$ {c['total']:.2f}"])
    cat_data.append(["TOTAL", str(len(gastos)), f"R$ {total:.2f}"])

    t = Table(cat_data, colWidths=[7*cm, 4*cm, 5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1a1a1a")),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 10),
        ("ROWBACKGROUNDS", (0,1), (-1,-2), [colors.HexColor("#f9f9f7"), colors.white]),
        ("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#f0f0ee")),
        ("FONTNAME",   (0,-1), (-1,-1), "Helvetica-Bold"),
        ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#e5e5e3")),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(t)

    # Lista completa de gastos
    story.append(Paragraph("Todos os gastos", sec_style))
    g_data = [["Data", "Descrição", "Categoria", "Valor (R$)", "Fonte"]]
    for g in gastos:
        g_data.append([
            g["data"],
            g["descricao"][:35],
            g["categoria"],
            f"R$ {g['valor']:.2f}",
            g["fonte"]
        ])

    tg = Table(g_data, colWidths=[2.5*cm, 6*cm, 3.5*cm, 3*cm, 2*cm])
    tg.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1a1a1a")),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 9),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#f9f9f7"), colors.white]),
        ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#e5e5e3")),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(tg)

    doc.build(story)
    return caminho
