@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"

set "FONTE_DADOS_DIR=FontedeDados_códigos"
set "CODIGO=%FONTE_DADOS_DIR%\codigo_central.py"
set "REQ=%FONTE_DADOS_DIR%\requirements.txt"
set "LOG_DIR=Execucoes_CMD"
set "RESULTADO_DIR=PlanilhaResultado"
set "UF_DIR=PlanilhasUF"
set "PORTABLE_PY=AmbientePython\python.exe"

set "NOME_RESPONSAVEL=%USERNAME%"
echo.
echo Para registrar quem fez a atualizacao, informe seu nome.
echo Se quiser usar o usuario do Windows, apenas pressione ENTER.
set /p "NOME_DIGITADO=Nome do responsavel: "
if not "%NOME_DIGITADO%"=="" set "NOME_RESPONSAVEL=%NOME_DIGITADO%"

if not exist "%CODIGO%" (
    echo ERRO: nao encontrei %CODIGO%.
    echo Confira se a pasta %FONTE_DADOS_DIR% esta junto deste arquivo.
    echo.
    pause
    exit /b 1
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "%RESULTADO_DIR%" mkdir "%RESULTADO_DIR%"
if not exist "%UF_DIR%" mkdir "%UF_DIR%"

set "GN_EXEC_USER=%USERDOMAIN%\%USERNAME%"
set "GN_EXEC_COMPUTER=%COMPUTERNAME%"
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set "GN_EXEC_STARTED_AT=%%i"
for /f "delims=" %%i in ('powershell -NoProfile -Command "$dir=$env:LOG_DIR; $date=Get-Date -Format 'yyyy-MM-dd'; $user=($env:NOME_RESPONSAVEL -replace '[^A-Za-z0-9._-]','_' ); if([string]::IsNullOrWhiteSpace($user)){ $user=$env:USERNAME }; $count=(Get-ChildItem -Path $dir -Filter ('Execucao_*_' + $date + '_*.log') -ErrorAction SilentlyContinue | Measure-Object).Count + 1; 'Execucao_{0:D3}_{1}_{2}.log' -f $count,$date,$user"') do set "LOG_NAME=%%i"
set "LOG=%LOG_DIR%\%LOG_NAME%"

echo ========================================
echo Atualizacao automatica de tarifas GN
echo ========================================
echo.
echo Esta janela pode ficar aberta por alguns minutos.
echo Responsavel: %NOME_RESPONSAVEL%
echo Usuario Windows: %GN_EXEC_USER%
echo Computador: %GN_EXEC_COMPUTER%
echo Ao final, a planilha central sera:
echo %RESULTADO_DIR%\Planilha_GN_Atualizada.xlsx
echo Log desta execucao:
echo %LOG%
echo.

(
    echo Execucao: %LOG_NAME%
    echo Responsavel: %NOME_RESPONSAVEL%
    echo Usuario Windows: %GN_EXEC_USER%
    echo Computador: %GN_EXEC_COMPUTER%
    echo Inicio: %GN_EXEC_STARTED_AT%
    echo Pasta: %CD%
    echo.
    echo ===== PREPARACAO DO AMBIENTE =====
) > "%LOG%"

set "USANDO_AMBIENTE_PORTATIL=0"
if exist "%PORTABLE_PY%" (
    set "PYTHON_CMD=%PORTABLE_PY%"
    set "USANDO_AMBIENTE_PORTATIL=1"
    echo Usando AmbientePython portatil. >> "%LOG%"
) else (
    echo AmbientePython nao encontrado. Tentando usar Python instalado na maquina. >> "%LOG%"
    where python >nul 2>nul
    if errorlevel 1 (
        set "PYTHON_CMD=py -3"
    ) else (
        set "PYTHON_CMD=python"
    )
)

%PYTHON_CMD% -c "import openpyxl, pandas, requests, bs4, pdfplumber, fitz, selenium" >> "%LOG%" 2>&1
if errorlevel 1 (
    if "%USANDO_AMBIENTE_PORTATIL%"=="1" (
        echo ERRO: encontrei a pasta AmbientePython, mas ela esta incompleta ou nao sincronizou totalmente.
        echo ERRO: AmbientePython incompleto ou bibliotecas ausentes. >> "%LOG%"
        echo Aguarde a sincronizacao da pasta e tente novamente. >> "%LOG%"
        set "STATUS=1"
        goto FIM
    )
    echo Bibliotecas ausentes. Instalando dependencias, aguarde...
    echo Bibliotecas ausentes. Iniciando instalacao pelo pip... >> "%LOG%"
    %PYTHON_CMD% -m pip --version >> "%LOG%" 2>&1
    if errorlevel 1 %PYTHON_CMD% -m ensurepip --upgrade >> "%LOG%" 2>&1
    %PYTHON_CMD% -m pip install --user -r "%REQ%" >> "%LOG%" 2>&1
    if errorlevel 1 (
        echo ERRO: nao consegui instalar as dependencias. Veja o log.
        echo ERRO: instalacao de dependencias falhou. >> "%LOG%"
        set "STATUS=1"
        goto FIM
    )
) else (
    echo Dependencias carregadas com sucesso. >> "%LOG%"
)

(
    echo.
    echo ===== SAIDA DO CODIGO =====
) >> "%LOG%"

%PYTHON_CMD% "%CODIGO%" %* >> "%LOG%" 2>&1
set "STATUS=%ERRORLEVEL%"

:FIM
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set "GN_EXEC_FINISHED_AT=%%i"
(
    echo.
    echo ===== FIM DA EXECUCAO =====
    echo Termino: %GN_EXEC_FINISHED_AT%
    echo Status: %STATUS%
) >> "%LOG%"

type "%LOG%"
echo.
if "%STATUS%"=="0" (
    echo ========================================
    echo Concluido com sucesso.
    echo Confira o arquivo Planilha_GN_Atualizada.xlsx em %RESULTADO_DIR%.
    echo ========================================
    explorer "%CD%\%RESULTADO_DIR%"
) else (
    echo ========================================
    echo Ocorreu um erro na atualizacao.
    echo Envie o arquivo de log abaixo para suporte:
    echo %CD%\%LOG%
    echo ========================================
)
echo.
pause
exit /b %STATUS%

