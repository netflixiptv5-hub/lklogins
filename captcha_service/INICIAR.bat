@echo off
echo ============================================
echo   CAPTCHA SOLVER SERVICE
echo ============================================
echo.
echo PASSO 1: Iniciando servidor na porta 5123...
echo PASSO 2: Abra OUTRO terminal e execute:
echo          ngrok http 5123
echo PASSO 3: Copie a URL do ngrok (ex: https://abc123.ngrok-free.app)
echo PASSO 4: No Railway, adicione a variavel:
echo          CAPTCHA_SERVICE_URL=https://abc123.ngrok-free.app
echo.
echo ============================================
echo.
python captcha_service.py
pause
