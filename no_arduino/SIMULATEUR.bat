@echo off
chcp 65001 > nul
title GNL — Simulateur Arduino

:MENU
cls
echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║         GNL — SIMULATEUR ARDUINO                         ║
echo  ║         Remplace l'Arduino quand il est absent           ║
echo  ╠══════════════════════════════════════════════════════════╣
echo  ║                                                          ║
echo  ║   [1]  Normal        — fonctionnement classique          ║
echo  ║   [2]  Fuite de gaz  — teste l'alarme ESD               ║
echo  ║   [3]  Debordement   — teste la vanne + pompe            ║
echo  ║   [4]  Capteurs HS   — teste les erreurs capteurs        ║
echo  ║                                                          ║
echo  ║   [Q]  Quitter                                           ║
echo  ║                                                          ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

set /p choix="  Ton choix (1/2/3/4/Q) : "

if /i "%choix%"=="1" goto NORMAL
if /i "%choix%"=="2" goto GAZ
if /i "%choix%"=="3" goto OVERFLOW
if /i "%choix%"=="4" goto CAPTEURS
if /i "%choix%"=="q" goto FIN
if /i "%choix%"=="Q" goto FIN

echo  Choix invalide, recommence...
timeout /t 2 > nul
goto MENU

REM ── Verifier Python ──────────────────────────────────────────────────────────
:CHECK_PYTHON
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  ERREUR : Python non installe.
    echo  Telecharge Python sur https://python.org
    pause
    exit /b 1
)

REM ── Installer paho-mqtt si absent ────────────────────────────────────────────
python -c "import paho" >nul 2>&1
if errorlevel 1 (
    echo  Installation de paho-mqtt...
    pip install paho-mqtt --quiet
)
goto :EOF

REM ════════════════════════════════════════════════════════════════════════════
:NORMAL
call :CHECK_PYTHON
cls
echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║  MODE : Fonctionnement normal                            ║
echo  ║  Les niveaux montent et descendent normalement           ║
echo  ║  La pompe et la vanne s'activent automatiquement         ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.
echo  Ctrl+C pour arreter et revenir au menu
echo.
python "%~dp0gnl_sim_publisher.py" --host broker.hivemq.com --public --scenario normal
echo.
pause
goto MENU

REM ════════════════════════════════════════════════════════════════════════════
:GAZ
call :CHECK_PYTHON
cls
echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║  MODE : Fuite de gaz                                     ║
echo  ║  Le gaz monte progressivement jusqu'a declencher ESD     ║
echo  ║  Tu verras l'alarme rouge sur le Dashboard               ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.
echo  Ctrl+C pour arreter et revenir au menu
echo.
python "%~dp0gnl_sim_publisher.py" --host broker.hivemq.com --public --scenario gas_leak
echo.
pause
goto MENU

REM ════════════════════════════════════════════════════════════════════════════
:OVERFLOW
call :CHECK_PYTHON
cls
echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║  MODE : Debordement R2                                   ║
echo  ║  R2 monte vite vers 95%                                  ║
echo  ║  Tu verras la vanne se fermer et la pompe s'arreter      ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.
echo  Ctrl+C pour arreter et revenir au menu
echo.
python "%~dp0gnl_sim_publisher.py" --host broker.hivemq.com --public --scenario overflow
echo.
pause
goto MENU

REM ════════════════════════════════════════════════════════════════════════════
:CAPTEURS
call :CHECK_PYTHON
cls
echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║  MODE : Capteurs en panne                                ║
echo  ║  HC-SR04 R1 et R2 tombent en panne apres 20 secondes    ║
echo  ║  Tu verras les erreurs err=0x03 sur le Dashboard         ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.
echo  Ctrl+C pour arreter et revenir au menu
echo.
python "%~dp0gnl_sim_publisher.py" --host broker.hivemq.com --public --scenario sensor_fail
echo.
pause
goto MENU

REM ════════════════════════════════════════════════════════════════════════════
:FIN
cls
echo.
echo  Au revoir !
echo.
timeout /t 2 > nul
exit
