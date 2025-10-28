@echo off
title AniMotion with Ngrok

echo Setting up environment...
set AUTH_PASS=animotion123
set SECRET_KEY=animotion-secret-key-2024
set NGROK_MODE=true

echo Starting Flask server...
start cmd /k "python app.py"

timeout /t 5

echo Starting Ngrok tunnel...
ngrok authtoken 2BCADofVjoyDj8ya7LAbVLrLbcG_KGyWRT2MGMwbim5WWUo1 
ngrok http 5000

echo.
echo ========================================
echo   AniMotion is now LIVE!
echo ========================================
echo Local:    http://127.0.0.1:5000
echo Network:  http://10.81.107.165:5000
echo Ngrok:    Check above for public URL
echo.
echo Login: admin / animotion123
echo ========================================
pause