# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é este projeto

GastosAI / "Controla Fácil" — um SaaS de finanças pessoais em português do Brasil. O usuário se cadastra, paga e controla os gastos inteiramente por um **agente de WhatsApp com IA** (movido a Claude). Há também um painel web, um relatório mensal em PDF e integração com o Google Agenda. Todo texto de interface, prompts e conteúdo do banco estão em pt-BR. Datas usam o horário de Brasília (UTC-3) via `hoje_brasil()`.

## Comandos

```bash
pip3 install -r requirements.txt          # instala dependências
python3 app.py                            # roda o servidor de dev (porta padrão 8080)
gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120   # produção (Procfile)
```

- Não existe suíte de testes. Não há etapa de lint nem de build.
- Copie `.env.example` → `.env` e preencha as chaves antes de rodar. Sem `DATABASE_URL`, usa um arquivo SQLite local `gastos.db`.
- `init_db()` roda automaticamente na importação (nível de módulo, dentro de `app.app_context()`), então as tabelas são criadas/migradas a cada boot.
- Hospedado no Railway; domínio de produção `controlafacilai.com.br`. Mantenha `--workers 1` — as threads agendadoras em background (abaixo) assumem um único processo.

## Arquitetura

Este é um **monolito Flask**. O `app.py` tem ~3800 linhas e concentra quase todas as rotas, o schema do banco, os webhooks de pagamento e as threads em background. Dois pacotes de apoio: `agente/` (IA do WhatsApp) e `relatorio/` (PDF).

### Abstração de banco (`db.py`) — leia isto antes de escrever qualquer query

O app roda em **SQLite localmente** e **PostgreSQL em produção**, alternados pela variável de ambiente `DATABASE_URL` (flag `USE_PG`). O `db.py` encapsula os dois atrás de uma API `conn.execute(sql, params)`.

- **Sempre escreva SQL com placeholders `%s`.** O wrapper do SQLite reescreve `%s` → `?` automaticamente. Alguns trechos mais antigos fazem `ph = "%s" if USE_PG else "?"` — os dois estilos coexistem; prefira o `%s` puro.
- No Postgres as linhas voltam como `RealDictRow` (acesso por dict), no SQLite como `sqlite3.Row` — ambos aceitam `row["coluna"]`, então use chaves de string, nunca índices inteiros.
- **O `init_db()` no `app.py` tem dois blocos de schema paralelos** — um ramo `if USE_PG:` e um `else:` (SQLite). Ao adicionar uma tabela ou coluna, **edite os dois ramos** ou funcionará em apenas um ambiente. Migrações são feitas ad-hoc dentro do `init_db` com `try/except ALTER TABLE`.
- Pegue uma conexão com `get_db()` e sempre faça `conn.commit()` e depois `conn.close()`.

### Agente de WhatsApp (`agente/agente.py`)

O núcleo do produto. Fluxo de entrada: Evolution/Meta envia POST para `/webhook/whatsapp` (no `app.py`) → deduplicação via tabela `webhook_msgs` (atômico `INSERT … ON CONFLICT DO NOTHING`) → `processar_mensagem` / `processar_imagem` / `processar_audio`.

- `chamar_claude()` manda a mensagem para o **`claude-sonnet-4-6`** com um system prompt grande em pt-BR que classifica a mensagem em ~22 intenções (registrar gasto, excluir, consultar resumo, análise, lembrete, parcelamento, conta recorrente, renda, etc.) e devolve **ações em JSON** que o código executa no banco. Ao mudar o comportamento do agente, edite esse system prompt e adicione um handler de ação correspondente.
- Áudio é transcrito via Groq (`whisper-large-v3`) com fallback para o Whisper da OpenAI; imagens de comprovante são lidas com Claude vision (`analisar_comprovante_claude`).
- Trabalho pesado (áudio/imagem) é despachado para `threading.Thread(daemon=True)` para o webhook responder rápido.

### Abstração de provedor de WhatsApp (`agente/wpp_provider.py`)

O envio é agnóstico de provedor via a variável `WPP_PROVIDER` (`evolution` padrão, ou `meta` para a API oficial do WhatsApp Cloud). Sempre envie através de `send_text` / `send_image_b64` daqui, em vez de chamar a Evolution/Meta diretamente. Se `EVOLUTION_KEY` não estiver definida, o texto "enviado" sai no stdout (modo dev).

### Threads agendadoras em background (`app.py`, threads daemon em nível de módulo)

- `_verificar_lembretes()` — loop a cada 60s: dispara lembretes vencidos pelo WhatsApp e roda os débitos automáticos diários (`_executar_debitos_automaticos`) / créditos de renda recorrente.
- `_verificar_trials()` — loop a cada hora: avisa/expira contas em trial.

Elas rodam dentro do processo e são o motivo de o deploy usar um único worker do gunicorn.

### Relatório em PDF (`relatorio/gerador.py`)

`gerar_pdf` / `gerar_e_enviar_pdf_wpp` montam um relatório mensal com gráficos do matplotlib (rosca/barra, backend Agg) compostos num PDF via reportlab, e depois enviam pelo WhatsApp. Disparado pelo agente, pelo painel, pelo admin e por `GET /relatorio/gerar/<cliente_id>?mes=YYYY-MM`.

### Outras integrações

- **Pagamentos:** Asaas é o gateway principal para assinaturas novas (`/pagamento/checkout-asaas/<id>` cria customer + assinatura mensal via API e redireciona para a fatura; `/webhook/asaas` ativa/suspende contas — valida o header `asaas-access-token` contra `ASAAS_WEBHOOK_TOKEN`). Kiwify (`/webhook/kiwify`) é **legado mas segue ativo** — assinantes antigos continuam sendo cobrados lá; não remover. Mercado Pago (`/webhook/mercadopago`) também é legado. Eventos da Conversions API (CAPI) da Meta + pixel disparam na compra.
- **Google Agenda:** OAuth em `/auth/google` e `/agenda/conectar/...`; o agente cria eventos e lista a agenda do dia.
- **E-mail:** Brevo (`_brevo_post`) para boas-vindas / redefinição de senha.
- **Painel admin** em `/admin` (login separado, `admin_required`) gerencia clientes, ativação manual e backups (CSV por e-mail).

### Autenticação

Sessões de cliente usam `login_required`; o admin usa `admin_required`. Senhas são hasheadas em `hash_senha`. As rotas web renderizam templates Jinja em `templates/`; a lógica do SPA do painel está em `static/js/dashboard.js` e conversa com os endpoints JSON `/api/*`.

## Convenções

- Mantenha as novas strings de interface e os prompts do Claude em português do Brasil.
- Números de telefone são normalizados com `normalizar_whatsapp` antes de busca/armazenamento.
- A maioria dos endpoints `/api/*` filtra todas as queries pelo `cliente_id` logado na sessão — preserve esse isolamento entre clientes em qualquer query nova.
