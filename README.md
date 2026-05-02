# GastosAI — Sistema completo de controle de gastos

Sistema SaaS com site de vendas, agente de WhatsApp com IA e relatório mensal em PDF.

## Estrutura do projeto

```
gastos-saas/
├── app.py                  # Back-end Flask principal
├── requirements.txt        # Dependências Python
├── .env.example            # Variáveis de ambiente (copie para .env)
├── agente/
│   └── agente.py           # Agente de WhatsApp com Claude AI
├── relatorio/
│   └── gerador.py          # Gerador de PDF mensal
├── templates/              # Páginas HTML
│   ├── index.html          # Site de vendas
│   ├── cadastro.html       # Formulário de cadastro
│   ├── login.html          # Login
│   ├── pagamento.html      # Tela de pagamento
│   ├── sucesso.html        # Conta ativada
│   └── dashboard.html      # Painel do cliente
└── static/
    ├── css/site.css        # Estilos
    └── js/dashboard.js     # JavaScript do painel
```

## Como rodar localmente

### 1. Instale as dependências
```bash
pip3 install -r requirements.txt
```

### 2. Configure as variáveis de ambiente
```bash
cp .env.example .env
# Edite o arquivo .env com suas chaves
```

### 3. Rode o servidor
```bash
source .venv/bin/activate  # se usar venv
python3 app.py
```

### 4. Acesse
```
http://localhost:5000
```

## Módulos do sistema

### Módulo 1 — Site de vendas
- Página inicial com planos e preços
- Cadastro com nome, e-mail, WhatsApp e plano
- Tela de pagamento (integração Stripe em produção)
- Ativação automática após pagamento

### Módulo 2 — Agente de WhatsApp
Requer a **Evolution API** rodando.

**Instalar Evolution API:**
```bash
docker run -d \
  --name evolution-api \
  -p 8080:8080 \
  -e AUTHENTICATION_API_KEY=sua-chave \
  atendai/evolution-api:latest
```

Após instalar, configure no `.env`:
- `EVOLUTION_URL`: URL da Evolution API
- `EVOLUTION_KEY`: sua chave de acesso
- `EVOLUTION_INSTANCE`: nome da instância

O webhook deve apontar para:
```
http://seu-servidor:5000/webhook/whatsapp
```

**Mensagens que o agente entende:**
- "gastei 50 reais no mercado" → registra gasto
- "comprei remédio por 35 reais" → registra gasto
- "resumo dos meus gastos" → retorna total do mês
- "quanto gastei esse mês?" → retorna resumo

### Módulo 3 — Relatório mensal
Gerar relatório manualmente:
```
GET /relatorio/gerar/1?mes=2025-04
```

Para envio automático no dia 1 de cada mês, configure um cron job:
```bash
# Crontab — roda às 8h do dia 1 de cada mês
0 8 1 * * python3 /caminho/do/projeto/cron_relatorio.py
```

## Hospedagem gratuita (Railway)

1. Suba o projeto no GitHub
2. Acesse railway.app e crie um novo projeto
3. Conecte o repositório do GitHub
4. Adicione as variáveis de ambiente no painel do Railway
5. Railway detecta Flask automaticamente e faz o deploy

## Integrações de pagamento (produção)

Para receber pagamentos reais, integre:
- **Stripe**: stripe.com (cartão internacional)
- **Mercado Pago**: developers.mercadopago.com (Pix + cartão BR)
- **Asaas**: asaas.com (Pix + boleto + cartão)
