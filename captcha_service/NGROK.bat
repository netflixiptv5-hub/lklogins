@echo off
echo ============================================
echo   ABRINDO TUNEL NGROK
echo ============================================
echo.
echo A URL que aparecer abaixo (https://xxxx.ngrok-free.app)
echo eh a que voce coloca no Railway como:
echo   CAPTCHA_SERVICE_URL=https://xxxx.ngrok-free.app
echo.
echo ============================================
echo.
ngrok http 5123
pause
