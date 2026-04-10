# 🔒 CAPTCHA Solver Service

Serviço que roda na sua **máquina Windows** (com display real) e resolve o CAPTCHA PerimeterX "Press and Hold" das contas Microsoft bloqueadas (abuse).

O LKLogins no Railway detecta abuse → chama este serviço → Chrome real abre, faz login, resolve CAPTCHA → Railway continua o fluxo.

## Pré-requisitos

- Python 3.9+
- Google Chrome instalado
- ngrok (grátis): https://ngrok.com/download

## Setup (1 vez)

```
1. Clique em INSTALAR.bat
   (ou: pip install flask undetected-chromedriver selenium)

2. Baixe ngrok: https://ngrok.com/download
   Extraia e coloque na pasta ou no PATH
```

## Uso diário

### Terminal 1 — Servidor:
```
Clique em INICIAR.bat
(ou: python captcha_service.py)
```

### Terminal 2 — Ngrok:
```
ngrok http 5123
```
Vai mostrar algo como:
```
Forwarding   https://a1b2c3d4.ngrok-free.app -> http://localhost:5123
```

### Railway — Variável de ambiente:
```
CAPTCHA_SERVICE_URL=https://a1b2c3d4.ngrok-free.app
```

**PRONTO!** Quando o LKLogins detectar abuse, vai chamar sua máquina pra resolver.

## API

| Endpoint | Método | Body | Resposta |
|----------|--------|------|----------|
| `/health` | GET | - | `{"ok": true, "workers_busy": 0, "workers_max": 3}` |
| `/solve` | POST | `{"email": "...", "password": "...", "job_id": "..."}` | `{"solved": true/false, "message": "..."}` |

## Notas

- Suporta até 3 CAPTCHAs simultâneos (3 janelas Chrome)
- Cada resolução demora ~30-60s
- Se o ngrok cair, o LKLogins faz fallback pro UC local (que pode falhar no Railway)
- A URL do ngrok muda cada vez que reinicia (versão grátis). Pra URL fixa, use ngrok com conta (grátis também)
