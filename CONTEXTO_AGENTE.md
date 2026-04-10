# LKLOGINS — Contexto Completo para o Agente

> Leia este arquivo inteiro antes de tocar em qualquer código.
> Ele explica o que o sistema faz, como funciona por dentro, o estado atual e o que ainda falta.

---

## O QUE É O SISTEMA

Serviço chamado **LKLOGINS** hospedado no Railway.
O cliente acessa o site, informa email + senha de uma conta Hotmail/Outlook, escolhe o serviço (Netflix, Prime, Disney, Globo) e o sistema faz login automaticamente naquela conta e extrai o link/código do email.

**URL produção:** `https://lklogins-production.up.railway.app`
**Repo GitHub:** `https://github.com/netflixiptv5-hub/lklogins`
**Token GitHub:** `ghp_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`
**Deploy:** automático a cada push na branch `master` via Railway (Dockerfile)

---

## ARQUITETURA

```
Cliente (browser)
    ↕ HTTP/REST
server.js  (Node.js/Express, porta $PORT)
    ↕ HTTP interno
rpa_worker.py  (Python, porta 8787)
    ↕
PostgreSQL (Railway interno)
```

### server.js
- Serve o frontend React (build estático em `dist/`)
- Endpoints:
  - `POST /api/extract` → dispara job no worker
  - `GET /api/status/:jobId` → polling de status pelo frontend
  - `GET /api/logs/:jobId` → logs completos de um job
  - `GET /api/logs-recent` → últimos jobs (usado para debug)
  - `GET /api/screenshot/:jobId` → screenshot ao vivo (debug)
  - `GET /api/captcha-live/:jobId` → screenshot ao vivo para CAPTCHA interativo
  - `GET /api/captcha-status/:jobId` → verifica se cliente clicou
  - `POST /api/captcha-click/:jobId` → recebe coordenadas do clique do cliente
  - `POST /api/update` → worker atualiza status de um job

### rpa_worker.py
- Servidor HTTP simples (BaseHTTPRequestHandler, porta 8787)
- Recebe jobs do server.js via `POST /run`
- Roda cada job em thread separada
- Tem um dict global `jobs = {}` com status de cada job
- Tem `_captcha_waiting = {}` para o fluxo CAPTCHA interativo

---

## FLUXO DE LOGIN (ordem de tentativas)

Função principal: `process_job(job_id, email_addr, service)`

```
1. IMAP DIRECT (emails @cinepremiu.com, netflixiptv+*@gmail.com, etc.)
   → vai direto pro IMAP sem login MS
   → função: process_job_imap_direct()

2. GMAIL (ck100k2+*@gmail.com)
   → login Gmail via IMAP app password ou browser
   → funções: process_job_gmail_imap(), process_job_gmail()

3. IMAP XOAUTH2 CACHE (~1s) ← MAIS RÁPIDO
   → usa access_token + refresh_token salvos no PostgreSQL
   → token_cache.py: get_imap_connection()
   → se token expirado: renova via refresh_token automaticamente
   → função: process_job_imap_cached()
   → só tem token se: api_login() funcionou antes OU extract_token_from_playwright_cookies() funcionou

4. API LOGIN (2-5s)
   → OAuth flow HTTP puro (sem browser), baseado no app Outlook Lite Android
   → api_login.py: CLIENT_ID = "e9b154d0-7658-433b-bb25-6b8e0a8a7c59"
   → se OK: salva token no token_cache, busca emails via REST API
   → se erro "proofs_needed": cai no browser (conta exige senha que não temos)
   → se erro "abuse": pula direto pro browser (conta bloqueada por bot detection)
   → função: process_job_api()

5. BROWSER PLAYWRIGHT (~19-25s)
   → lança Chromium headless com stealth
   → tenta cookie cache primeiro (cookies salvos de login anterior)
   → se cookie cache OK: vai direto pro Outlook, busca email
   → se cookie cache miss/expirado: faz login normal com senha
   → senhas testadas: HOTMAIL_PASSWORD = "02022013L", HOTMAIL_PASSWORD_ALT = "A29b92c10@"
   → após login com sucesso: salva cookies + tenta extrair token OAuth
   → função principal do browser: dentro de process_job()

6. CODE LOGIN (fallback, ~60s+)
   → se browser falhou por senha errada
   → clica "enviar código" no login MS
   → busca o código no email @cinepremiu.com via IMAP
   → função: process_job_code_login()
```

---

## CACHES (aceleradores de velocidade)

### token_cache.py — PostgreSQL
- Tabela: `lklogins_token_cache`
- Salva: `access_token`, `refresh_token`, `cid` por email
- Usado por: passo 3 (IMAP XOAUTH2 ~1s)
- Salvo quando: `api_login()` funciona (passo 4) OU `extract_token_from_playwright_cookies()` funciona (após browser)
- Renovação: automática via `refresh_token` se access_token expirar
- **Sem expiração configurada** (tokens MS duram ~1h, refresh dura muito mais)

### cookie_cache.py — PostgreSQL
- Tabela: `lklogins_cookie_cache`
- Salva: todos os cookies do Playwright após login bem-sucedido
- Expira: 7 dias (`MAX_AGE_SECONDS = 7 * 24 * 3600`)
- Usado por: passo 5 dentro do browser (evita relogar, vai direto pro Outlook)
- **Ainda demora ~19s** porque ainda precisa lançar browser e navegar

### Por que o token cache é muito mais rápido que o cookie cache
- Token cache → IMAP direto, sem browser, sem navegação → ~1s
- Cookie cache → ainda precisa lançar Playwright + navegar pro Outlook → ~19s

---

## CAPTCHA (PerimeterX / px-captcha)

Quando a conta está marcada como "abuse" pela Microsoft, o login cai numa página com CAPTCHA PerimeterX.

### Abordagem automática (captcha_solver.py)
- Detecta o CAPTCHA na página
- Tenta clicar no ícone de acessibilidade (boneco azul) via CDP
- Coordenadas aproximadas: (840, 700) na viewport 1920x1080
- Usa `Input.dispatchMouseEvent` via CDP para penetrar iframes
- Usa hover gradual antes do clique para parecer humano
- **Sucesso inconsistente** — às vezes passa, às vezes fica em loop

### Abordagem interativa (modal na tela)
- Se o automático não resolver após N tentativas → `update_job(job_id, "captcha_waiting")`
- Frontend detecta status `captcha_waiting` e abre modal com screenshot ao vivo
- Cliente vê a tela do browser em tempo real (polling a cada 800ms via `/api/captcha-live/:jobId`)
- Cliente clica na imagem onde está o ícone
- Frontend escala coordenadas do clique (tamanho exibido → 1920x1080)
- Envia para `/api/captcha-click/:jobId`
- Worker recebe, faz CDP click nas coordenadas reais, continua o login
- Timeout de 3 minutos para o cliente resolver

---

## FRONTEND (React + Vite)

- `src/web/pages/index.tsx` — página principal (única página)
- Estados do job: `idle | connecting | logged_in | searching | found | not_found | not_found_waiting | error | expired_waiting | captcha_waiting`
- Polling de status a cada 2s via `/api/status/:jobId`
- Modal de CAPTCHA: aparece quando `jobStatus === "captcha_waiting"`
- Build: `bun run build` → gera `dist/` servido pelo server.js

---

## SERVIÇOS SUPORTADOS

| Código | O que busca |
|--------|-------------|
| `password_reset` | Link redefinição de senha Netflix |
| `household_update` | Link atualização de residência Netflix |
| `temp_code` | Código temporário de acesso Netflix |
| `netflix_disconnect` | Código confirmação de alteração Netflix |
| `prime_code` | Código verificação Amazon Prime |
| `disney_code` | Código verificação Disney+ |
| `globo_reset` | Link redefinição Globoplay |

---

## BANCO DE DADOS (PostgreSQL Railway)

```
Host interno: postgres.railway.internal:5432
DB: trocasdolk
User: lkadmin
Pass: lkstore2026pg
```

Tabelas criadas automaticamente pelo código:
- `lklogins_token_cache` — tokens OAuth por email
- `lklogins_cookie_cache` — cookies Playwright por email
- `lklogins_jobs_log` — histórico de todos os jobs (criado pelo job_logger.py)

---

## VARIÁVEIS DE AMBIENTE (Railway)

| Var | Valor |
|-----|-------|
| `PORT` | definido pelo Railway automaticamente |
| `DATABASE_URL` | postgresql://lkadmin:lkstore2026pg@postgres.railway.internal:5432/trocasdolk |
| `WORKER_PORT` | 8787 (padrão, pode não estar definida) |
| `API_BASE` | http://localhost:$PORT (padrão) |
| `DISPLAY` | :99 (Xvfb para Chrome headless) |

---

## ARQUIVOS PRINCIPAIS

```
/
├── server.js              # Backend Node.js (API + serve frontend)
├── Dockerfile             # Build: instala Node, Python, Chrome, deps
├── start.sh               # Inicia Xvfb + worker Python + server Node
├── railway.json           # Config deploy Railway
├── package.json           # Deps Node (express, node-fetch)
├── vite.config.ts         # Config build frontend
├── src/web/pages/index.tsx  # Frontend React (toda a UI)
└── worker/
    ├── rpa_worker.py       # Worker principal (toda a lógica RPA)
    ├── api_login.py        # OAuth flow HTTP puro + extract_token_from_playwright_cookies()
    ├── cookie_cache.py     # Salva/carrega cookies Playwright no PostgreSQL
    ├── token_cache.py      # Salva/carrega access+refresh token no PostgreSQL
    ├── captcha_solver.py   # Solver automático do CAPTCHA PerimeterX
    └── job_logger.py       # Salva logs de cada job no PostgreSQL
```

---

## TAG DE CHECKPOINT ESTÁVEL

```
git tag: v-salvando-cookies-e-token-cache
commit:  bfeed4a
```

Para voltar a esse estado:
```bash
git checkout bfeed4a -- worker/rpa_worker.py worker/api_login.py worker/cookie_cache.py worker/token_cache.py
git commit -m "rollback: v-salvando-cookies-e-token-cache"
git push
```

---

## ESTADO ATUAL (último commit: bfeed4a)

### O que está funcionando bem
- Contas que já passaram pelo API login → **~1s** (token cache)
- Contas com cookie salvo (já logaram pelo browser) → **~19s** (cookie cache)
- Primeira vez / sem cache → **~20-25s** (browser completo)
- Cookie e token salvos automaticamente após cada login bem-sucedido
- Após login via browser: tenta extrair token OAuth silencioso → próxima vai ~1s

### O que ainda tem problema
- Contas `abuse` (CAPTCHA): solver automático inconsistente
- CAPTCHA interativo: modal aparece mas clique nem sempre passa
- Tempo de ~19s no cookie cache ainda é alto (browser + Outlook ainda demora)

### Próximas melhorias possíveis
1. Quando cookie cache hit → tentar extrair token via cookies HTTP (sem browser) → seria ~2s
2. Melhorar solver CAPTCHA automático (coordenadas mais precisas)
3. Limpar token_cache quando IMAP retorna "auth failed" (token revogado)

---

## COMO TESTAR

```bash
# Disparar job
curl -X POST https://lklogins-production.up.railway.app/api/extract \
  -H "Content-Type: application/json" \
  -d '{"email":"SEU_EMAIL@hotmail.com","password":"SENHA","service":"temp_code"}'
# Retorna: {"ok":true,"jobId":"abc123"}

# Ver status
curl https://lklogins-production.up.railway.app/api/status/abc123

# Ver logs recentes (todos os jobs)
curl https://lklogins-production.up.railway.app/api/logs-recent

# Ver logs de um job específico
curl https://lklogins-production.up.railway.app/api/logs/abc123
```

---

## DEPLOY

Qualquer push na branch `master` faz deploy automático no Railway (~2 min).

```bash
git add -A
git commit -m "descrição"
git push
```

O Railway usa o `Dockerfile` para build e `start.sh` para iniciar.
`start.sh` inicia: Xvfb (display virtual) + rpa_worker.py + server.js
