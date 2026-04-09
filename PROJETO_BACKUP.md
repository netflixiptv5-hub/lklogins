# LKLOGINS — Documentação Completa para Reconstrução

## O QUE É O PROJETO

Sistema que recebe um email (hotmail/outlook/gmail) e um serviço (ex: `password_reset`, `temp_code`), faz login automático na conta, abre a caixa de entrada e extrai o link ou código do email mais recente da Netflix, Amazon, Disney, Globo, etc.

**Deploy:** Railway (auto-deploy via push no branch `master`)
**URL produção:** `https://lklogins-production.up.railway.app`
**Repo:** `https://github.com/netflixiptv5-hub/lklogins`

---

## STACK

- **Frontend:** React + Vite + TypeScript
- **Backend API:** Node.js (Express) — `server.js`
- **Worker RPA:** Python 3 — `worker/rpa_worker.py`
- **Browser automation:** Playwright (Chromium headless) + undetected-chromedriver (fallback)
- **Deploy:** Docker no Railway
- **Display virtual:** Xvfb `:99` (Chrome precisa de display mesmo headless)

---

## ARQUITETURA

```
Cliente HTTP
    ↓
server.js (Node, porta 3000)
    ↓  POST /run
rpa_worker.py (Python, porta 8787)
    ↓
Playwright → Chrome → login MS/Google → caixa de entrada → extrai link/código
```

O Node recebe as requisições do front/cliente, cria um job, dispara pro worker Python, e fica em memória com o status. O Python faz todo o trabalho pesado.

---

## ENDPOINTS

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/extract` | Inicia extração. Body: `{"email":"...","service":"..."}` |
| GET | `/api/status/:jobId` | Status do job |
| GET | `/api/logs/:jobId` | Logs detalhados do job |
| GET | `/api/logs-recent` | Últimos jobs |
| GET | `/api/screenshot` | Screenshot debug do captcha |

**Serviços válidos:** `password_reset`, `household_update`, `temp_code`, `netflix_disconnect`, `prime_code`, `disney_code`, `globo_reset`

---

## FLUXO COMPLETO DE EXTRAÇÃO

### Ordem de tentativas (a que falha passa pra próxima):

**1. API login (sem browser)**
- Faz requisição HTTP direta simulando o app Outlook Lite
- Obtém access_token OAuth2 da Microsoft
- Usa Graph API pra buscar emails
- Mais rápido (~5s). Arquivo: `worker/api_login.py`
- Falha em contas com `abuse`, `identity/confirm`, `verification_needed`

**2. Cookie cache**
- Se já logou antes, salva cookies no banco (PostgreSQL)
- Tenta carregar cookies e abrir Outlook direto sem login
- Arquivo: `worker/cookie_cache.py`

**3. Browser Playwright**
- Abre Chrome real (headless), faz login em `login.live.com`
- Trata vários estados pós-login:
  - `identity/confirm` → completa verificação pelo email de recuperação (cinepremiu.com)
  - `abuse` → tenta resolver CAPTCHA de press-and-hold (PerimeterX)
  - Normal → vai direto pro Outlook
- Arquivo: `worker/rpa_worker.py` — função `process_job()`

**4. Code login (último fallback)**
- Pede pra Microsoft mandar código de acesso pro email de recuperação (cinepremiu.com)
- Lê o código via IMAP do servidor `webmail.amen.pt`
- Digita o código e entra na conta
- Arquivo: `worker/rpa_worker.py` — função `process_job_code_login()`

---

## CONTAS E CREDENCIAIS (CONFIG NO rpa_worker.py)

```python
HOTMAIL_PASSWORD = "02022013L"
HOTMAIL_PASSWORD_ALT = "A29b92c10@"
PASSWORDS = [HOTMAIL_PASSWORD, HOTMAIL_PASSWORD_ALT]

RECOVERY_DOMAIN = "cinepremiu.com"
RECOVERY_IMAP_SERVER = "webmail.amen.pt"
RECOVERY_EMAIL = "catchall@cinepremiu.com"
RECOVERY_PASSWORD = "02022013L@@@@"
```

**Email de recuperação:** Para contas que pedem `identity/confirm`, a Microsoft manda um código pro email `{usuario}@cinepremiu.com`. O sistema lê via IMAP.

**Domínio cinepremiu.com:** As contas têm como email de recuperação cadastrado `nomeconta@cinepremiu.com`. IMAP no servidor `webmail.amen.pt:993`.

---

## TRATAMENTO DE TIPOS DE CONTA

### Conta normal
Login direto, sem verificação → vai pro Outlook → busca emails.

### Conta `identity/confirm` (ex: Sabrinapereira16081970@hotmail.com)
Microsoft pede "confirme sua identidade" com código por email.
- Detecta página `identity/confirm` na URL
- Pega email mascarado da página (ex: `sa***@cinepremiu.com`)
- Resolve via IMAP: descobre qual é o email real (`sabrinapereira16081970@cinepremiu.com`)
- Digita o email, clica "Enviar código", espera chegar via IMAP
- Digita o código, passa a verificação
- Vai pro Outlook normalmente

### Conta `abuse` (ex: juliacardoso32587@outlook.com)
Microsoft bloqueou por atividade suspeita. Mostra CAPTCHA PerimeterX.
- CAPTCHA é um iframe `hsprotect.net` com botão "press and hold"
- Tenta resolver via CDP (mouse events) segurando o botão por ~15s
- Ícone de acessibilidade (wheelchair) existe mas é canvas/JS puro, não DOM → difícil de clicar
- Fallback: undetected-chromedriver (UC) — mas UC não consegue chegar na página de abuse (cai em identity verification)
- **Status atual:** parcialmente resolvido, às vezes passa, às vezes não

---

## BUSCA DE EMAILS (search_and_extract)

1. Navega pro `outlook.live.com/mail/0/`
2. Pesquisa `from:netflix` (ou amazon, disney, etc) na barra de busca
3. Pega lista de emails (até 15)
4. Dois passes: primeiro tenta emails cujo assunto bate com os patterns do serviço, depois qualquer email do remetente
5. Abre o email mais recente primeiro
6. Extrai link/código via regex do HTML do corpo
7. Calcula se expirado pela hora do email vs hora atual
8. Se não achar na inbox, tenta pasta Lixo Eletrônico (junkemail)

**Patterns de serviço** (`EMAIL_PATTERNS` no topo de `rpa_worker.py`):
- `password_reset`: "redefinir senha", "reset your password", etc.
- `temp_code`: "código de acesso temporário", "temporary access code", etc.
- `household_update`: "residência", "household", etc.

---

## EXTRAÇÃO DE LINKS/CÓDIGOS

Arquivo: `worker/rpa_worker.py` — função `extract_netflix_link(html, service)`

- Usa regex pra achar links `netflix.com/password`, `netflix.com/account/travel/verify`, etc.
- Pra códigos (temp_code, prime_code, disney_code): regex de 4-8 dígitos perto de palavras-chave
- Retorna `{"link": "...", "code": "..."}` ou None

---

## BANCO DE DADOS

PostgreSQL no Railway (variável `DATABASE_URL`).

Tabelas:
- `jobs`: status dos jobs (id, status, email, service, link, code, created_at, etc.)
- `cookie_cache`: cookies salvos por email
- `token_cache`: tokens OAuth2 por email

---

## WORKER PYTHON — ESTRUTURA

```
worker/
├── rpa_worker.py        # Principal — login, navegação, extração (3264 linhas)
├── api_login.py         # Login via HTTP (sem browser) + Graph API (474 linhas)
├── captcha_solver.py    # Solver do CAPTCHA PerimeterX (1418 linhas)
├── cookie_cache.py      # Salvar/carregar cookies no PostgreSQL (164 linhas)
├── job_logger.py        # Log por jobId acessível via /api/logs/:jobId (174 linhas)
└── token_cache.py       # Cache de tokens OAuth2 (214 linhas)
```

---

## DOCKER / DEPLOY

`Dockerfile`:
1. Stage 1: build do frontend React com Node
2. Stage 2: Node + Python + Chrome + Playwright + Xvfb
3. Instala deps Python: `httpx playwright playwright-stealth pytz undetected-chromedriver selenium psycopg2-binary`
4. `playwright install chromium`

`start.sh`:
1. Inicia Xvfb `:99` (display virtual pra Chrome)
2. Inicia `python3 rpa_worker.py` em background (porta 8787)
3. Aguarda worker estar pronto
4. Inicia `node server.js` em foreground (porta 3000)

`railway.json`: healthcheck em `/api/status/health`, restart on failure.

---

## VARIÁVEIS DE AMBIENTE (Railway)

| Var | Descrição |
|-----|-----------|
| `DATABASE_URL` | PostgreSQL connection string |
| `PORT` | Porta do Node (padrão 3000) |

---

## PONTOS CRÍTICOS / BUGS CONHECIDOS

1. **CAPTCHA abuse (PerimeterX):** O ícone de acessibilidade é renderizado por canvas/JS, não é DOM. Coordenadas de clique variam. Press-and-hold às vezes funciona, às vezes não detecta movimento suficiente.

2. **CDP Mouse Events:** Usar `page.context.new_cdp_session(page)` — NÃO `browser.new_browser_cdp_session()` (retorna "not found").

3. **identity/confirm timing:** Código chega via IMAP mas às vezes demora e expira antes de digitar. Fallback pro code login resolve.

4. **Cookie expiration:** Cookies do Outlook duram ~1-3 dias. Após expirar, faz login completo de novo.

5. **Marketing page redirect:** Quando sessão não é totalmente autenticada, `outlook.live.com/mail/0/` redireciona pra `microsoft.com/en-us/microsoft-365/...`. Detectado pelo URL e tratado como "Not in Outlook".

---

## COMO RECRIAR DO ZERO

1. Criar repo GitHub
2. Criar projeto no Railway com PostgreSQL
3. Criar as 3 tabelas (jobs, cookie_cache, token_cache) — ver início de `rpa_worker.py`
4. Copiar todos os arquivos conforme estrutura acima
5. Configurar `DATABASE_URL` no Railway
6. Push no master → auto-deploy

A lógica principal toda está em `worker/rpa_worker.py`. O resto é infraestrutura.
