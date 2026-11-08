@echo off
title Configuration du reseau en mode Prive
echo Verification des droits administrateur...

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Demande d'elevation administrateur (UAC)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo.
echo Application du profil Prive sur l'interface Ethernet...
powershell -NoProfile -Command "Set-NetConnectionProfile -InterfaceAlias 'Ethernet' -NetworkCategory Private"

echo.
echo Verification de la nouvelle configuration :
powershell -NoProfile -Command "Get-NetConnectionProfile -InterfaceAlias 'Ethernet' | Select-Object InterfaceAlias, NetworkCategory"

echo.
echo ========================================================
echo Termine ! Votre reseau est maintenant en mode PRIVE.
echo La decouverte reseau et les connexions locales sont actives.
echo ========================================================
echo.
pause
