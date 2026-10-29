@echo off
rem Calculadora GLP x GN em conteiner (Docker Desktop ou Podman) - Windows.
rem
rem Uso:
rem   Iniciar_Calculadora_Docker.bat            constroi (com testes) e sobe em segundo plano na porta 5000
rem   set PORTA=8080 ^& Iniciar_Calculadora_Docker.bat
rem   Iniciar_Calculadora_Docker.bat --parar    derruba o conteiner
rem   Iniciar_Calculadora_Docker.bat --logs     acompanha os logs
rem
rem O conteiner reinicia sozinho (restart: unless-stopped) e roda o ETL do IM
rem todo dia as 00:00. Execucao manual, log e agendamento: tela /interno/etl.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if "%PORTA%"=="" set "PORTA=5000"

rem Docker (docker compose) ou Podman (podman compose / podman-compose), o que houver.
docker compose version >nul 2>nul && (set "MOTOR=docker" & set "COMPOSE=docker compose" & goto :motor_ok)
podman compose version >nul 2>nul && (set "MOTOR=podman" & set "COMPOSE=podman compose" & goto :motor_ok)
where podman-compose >nul 2>nul && (set "MOTOR=podman" & set "COMPOSE=podman-compose" & goto :motor_ok)
echo ERRO: instale o Docker Desktop (com o plugin compose) ou o Podman + podman-compose.
goto :falha

:motor_ok
if /i "%~1"=="--parar" (%COMPOSE% down & exit /b %ERRORLEVEL%)
if /i "%~1"=="--logs" (%COMPOSE% logs -f & exit /b %ERRORLEVEL%)

if not exist "data\tarifas.json" (
  echo ERRO: data\tarifas.json nao encontrado ^(base inicial da imagem^).
  goto :falha
)

echo ========================================
echo Calculadora GLP x GN (conteiner, %MOTOR%)
echo ========================================

rem O daemon precisa estar no ar (Docker Desktop aberto).
%MOTOR% info >nul 2>nul || (
  echo ERRO: o %MOTOR% nao respondeu. Abra o Docker Desktop e aguarde ele iniciar.
  goto :falha
)

echo Rodando os testes na imagem...
%MOTOR% build -q -f Dockerfile --target teste . >nul || goto :falha

echo Construindo e subindo o conteiner...
%COMPOSE% up -d --build || goto :falha

<nul set /p "=Aguardando a calculadora responder"
for /l %%i in (1,1,30) do (
  curl.exe -fsS "http://127.0.0.1:%PORTA%/saude" >nul 2>nul && goto :no_ar
  <nul set /p "=."
  timeout /t 1 /nobreak >nul
)
echo.
echo ERRO: a calculadora nao respondeu. Veja: %COMPOSE% logs
goto :falha

:no_ar
echo.
curl.exe -fsS "http://127.0.0.1:%PORTA%/saude"
echo.
echo Acesse: http://127.0.0.1:%PORTA%/
echo ETL (tela interna): http://127.0.0.1:%PORTA%/interno/etl
start "" "http://127.0.0.1:%PORTA%/"
exit /b 0

:falha
echo.
pause
exit /b 1
