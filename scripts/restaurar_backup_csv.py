"""Restaura o backup CSV (clientes.csv + gastos.csv) no banco apontado por DATABASE_URL.

Uso:
    DATABASE_URL=postgresql://... python3 scripts/restaurar_backup_csv.py /caminho/da/pasta_ou_zip

- A pasta (ou ZIP do e-mail "Backup Controla Fácil") deve conter clientes.csv e gastos.csv.
- Rode DEPOIS do primeiro deploy (o init_db do app cria as tabelas no boot).
- Os CSVs não têm senha: cada cliente entra com uma senha aleatória irrecuperável
  e precisará usar "Esqueci minha senha" no site.
- Idempotente: cliente com e-mail já existente é pulado (e seus gastos também).
"""
import csv
import hashlib
import os
import sys
import tempfile
import uuid
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from db import get_db, USE_PG


def carregar_csvs(origem):
    if origem.lower().endswith(".zip"):
        tmp = tempfile.mkdtemp(prefix="backup_restore_")
        with zipfile.ZipFile(origem) as zf:
            zf.extractall(tmp)
        origem = tmp
    clientes_path = os.path.join(origem, "clientes.csv")
    gastos_path = os.path.join(origem, "gastos.csv")
    for p in (clientes_path, gastos_path):
        if not os.path.exists(p):
            sys.exit(f"ERRO: não achei {p}")
    with open(clientes_path, newline="", encoding="utf-8") as f:
        clientes = list(csv.DictReader(f))
    with open(gastos_path, newline="", encoding="utf-8") as f:
        gastos = list(csv.DictReader(f))
    return clientes, gastos


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    if not os.environ.get("DATABASE_URL"):
        print("AVISO: DATABASE_URL não definido — restaurando no SQLite local gastos.db")

    clientes, gastos = carregar_csvs(sys.argv[1])
    print(f"Backup lido: {len(clientes)} clientes, {len(gastos)} gastos")

    conn = get_db()
    ins_cli = pul_cli = 0
    ids_inseridos = set()
    for c in clientes:
        existe = conn.execute(
            "SELECT id FROM clientes WHERE email = %s", (c["email"],)
        ).fetchone()
        if existe:
            pul_cli += 1
            continue
        senha_irrecuperavel = hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest()
        conn.execute(
            """INSERT INTO clientes (id, nome, email, senha_hash, whatsapp, status, criado_em)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (c["id"], c["nome"], c["email"], senha_irrecuperavel,
             c["whatsapp"], c["status"], c["criado_em"]),
        )
        ids_inseridos.add(str(c["id"]))
        ins_cli += 1

    ins_g = pul_g = 0
    for g in gastos:
        if str(g["cliente_id"]) not in ids_inseridos:
            pul_g += 1
            continue
        conn.execute(
            """INSERT INTO gastos (id, cliente_id, descricao, valor, categoria, data, fonte, criado_em)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (g["id"], g["cliente_id"], g["descricao"], g["valor"],
             g["categoria"], g["data"], g["fonte"], g["criado_em"]),
        )
        ins_g += 1

    if USE_PG:
        # ids vieram explícitos: realinha as sequences para os próximos INSERTs
        conn.execute("SELECT setval('clientes_id_seq', (SELECT COALESCE(MAX(id),1) FROM clientes))")
        conn.execute("SELECT setval('gastos_id_seq', (SELECT COALESCE(MAX(id),1) FROM gastos))")

    conn.commit()
    conn.close()
    print(f"Clientes: {ins_cli} inseridos, {pul_cli} já existiam (pulados)")
    print(f"Gastos:   {ins_g} inseridos, {pul_g} pulados (cliente já existia ou ausente)")
    print("Lembre: clientes restaurados precisam de 'Esqueci minha senha' para entrar no painel.")


if __name__ == "__main__":
    main()
