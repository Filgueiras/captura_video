@echo off
rem Abre o aplicativo com duplo clique.
rem Usa pythonw quando existir: ele nao cria janela de console atras do app.
cd /d "%~dp0"

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw -m capturador
    exit /b 0
)

where python >nul 2>&1
if %errorlevel%==0 (
    start "" python -m capturador
    exit /b 0
)

echo Python nao foi encontrado no PATH.
echo Instale em https://python.org e marque "Add Python to PATH".
pause
