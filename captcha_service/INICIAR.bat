@echo off
echo ============================================
echo   CAPTCHA SOLVER SERVICE
echo ============================================
echo.

REM Autenticar ngrok (so precisa 1 vez, mas nao faz mal repetir)
ngrok config add-authtoken 3C98P5RUaLDPxEA8CCCwKuDyJ0L_5hkXZouLwnsVGig8sRgp9

echo.
echo Iniciando servidor CAPTCHA na porta 5123...
echo Depois abra OUTRO terminal e execute:
echo.
echo   ngrok http 5123
echo.
echo Copie a URL https://xxxx.ngrok-free.app
echo e coloque no Railway como variavel:
echo   CAPTCHA_SERVICE_URL=https://xxxx.ngrok-free.app
echo.
echo ============================================
echo.
python captcha_service.py
pause
