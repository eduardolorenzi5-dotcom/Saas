# Migração Railway → Render + WhatsApp Cloud API (Meta)

Contexto: conta do Railway banida em 06/07/2026 (falso positivo de "phishing", appeal enviado).
Este guia sobe tudo no Render e troca a Evolution API pela API oficial da Meta.

## 0. Dados (fazer antes de tudo)

- [ ] Procurar no Gmail: **"Backup Controla Fácil"** — baixar o ZIP mais recente (clientes + gastos).
- [ ] Se o appeal do Railway for aceito, mesmo que temporariamente: exportar TUDO na hora
      (`pg_dump` completo — inclui lembretes, contas recorrentes, rendas, tokens Google, que
      NÃO estão no backup CSV).

## 1. Render — criar os serviços

1. [ ] Login em https://dashboard.render.com (conta já existe, era do banco antigo).
2. [ ] **New + → Blueprint** → conectar o repo `eduardolorenzi5-dotcom/Saas` → o `render.yaml`
       cria o web service `controla-facil` (Starter) + Postgres `controla-facil-db`.
3. [ ] Preencher as variáveis marcadas `sync: false` no dashboard (ver `.env.example` para a
       lista completa e onde obter cada chave). Todas são recuperáveis nos painéis:
       - `ANTHROPIC_API_KEY` → console.anthropic.com
       - `GROQ_API_KEY` → console.groq.com
       - `MP_ACCESS_TOKEN` → mercadopago.com.br → Suas integrações
       - `BREVO_API_KEY` / `BREVO_FROM_EMAIL` → app.brevo.com
       - `GOOGLE_CLIENT_ID` / `SECRET` → console.cloud.google.com → Credentials
       - `WHATSAPP_*` → passo 2 abaixo
       - `ADMIN_KEY`, `CRON_SECRET`, `BACKUP_EMAIL` → você define
       - `APP_URL` / `BASE_URL` = `https://controlafacilai.com.br`
4. [ ] Primeiro deploy sobe e o `init_db()` cria as tabelas sozinho.
5. [ ] Restaurar o backup (do Mac):
       `DATABASE_URL="<External Database URL do Render>" python3 scripts/restaurar_backup_csv.py ~/Downloads/backup_XXXX.zip`
       (clientes restaurados precisarão de "Esqueci minha senha".)

## 2. WhatsApp Cloud API (Meta)

1. [ ] developers.facebook.com → app do tipo Business → adicionar produto **WhatsApp**.
2. [ ] Registrar/verificar o número comercial (se o número estava na Evolution, primeiro
       desconectá-lo do WhatsApp normal — a Cloud API exige o número exclusivo).
3. [ ] Business Settings → System User → gerar **token permanente** com escopo
       `whatsapp_business_messaging` → `WHATSAPP_TOKEN`.
4. [ ] Copiar o **Phone number ID** → `WHATSAPP_PHONE_ID`.
5. [ ] Configurar webhook: URL `https://controlafacilai.com.br/webhook/whatsapp`,
       verify token = o valor que você puser em `WHATSAPP_VERIFY_TOKEN`,
       assinar o campo **messages**.
6. [ ] Conferir `WPP_PROVIDER=meta` no Render (o render.yaml já define).
7. [ ] Teste ponta a ponta: mandar "gastei 10 reais no mercado" e ver o gasto no banco.

## 3. Reapontar integrações para o novo host

- [ ] **DNS**: em quem gerencia controlafacilai.com.br, trocar o CNAME/A do Railway pelo
      do Render (Settings → Custom Domain no web service). O Render emite TLS sozinho.
- [ ] **Mercado Pago**: atualizar a URL de notificação para
      `https://controlafacilai.com.br/webhook/mercadopago` (se estava com URL *.railway.app).
- [ ] **Kiwify**: idem → `/webhook/kiwify`.
- [ ] **Google OAuth**: em console.cloud.google.com → Credentials, garantir a redirect URI
      `https://controlafacilai.com.br/auth/google/callback`.
- [ ] **Cron de backup**: agendar GET diário em
      `https://controlafacilai.com.br/cron/backup?key=<CRON_SECRET>`
      (cron-job.org ou Render Cron Job). Conferir o e-mail de backup chegando.

## 4. Pós-migração

- [ ] Avisar os clientes (broadcast pelo próprio bot) que o serviço voltou e que o acesso
      ao painel pede redefinição de senha.
- [ ] Tokens do Google Agenda dos clientes se perderam com o banco → cada um reconecta
      em /agenda/conectar.
- [ ] Apagar o serviço/segredos do Railway das anotações; rotacionar qualquer chave que
      tenha aparecido em prints.
- [ ] Se o appeal do Railway for aceito depois: NÃO religar lá; só exportar os dados
      completos e mesclar (lembretes/recorrentes/rendas).
