@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
if "%PORTA%"=="" set "PORTA=5000"

echo ========================================
echo Calculadora GLP x GN (Python / Flask)
echo ========================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo Preparando o ambiente Python pela primeira vez...
  set "PYTHON_CMD=python"
  where python >nul 2>nul || set "PYTHON_CMD=py -3"
  call %%PYTHON_CMD%% -m venv .venv || goto :erro
)
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :erro
rem Bibliotecas do processo de coleta do IM (usadas pela tela /interno/etl).
".venv\Scripts\python.exe" -m pip install -q -r "processo_im\1_Processo_Extracao_Dados\Comece_aqui\Fonte_Dados\requirements.txt" || goto :erro

start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:%PORTA%/"
".venv\Scripts\python.exe" app.py
exit /b %ERRORLEVEL%

:erro
echo.
echo Nao foi possivel preparar o ambiente Python. Verifique se o Python 3 esta instalado.
pause
exit /b 1
