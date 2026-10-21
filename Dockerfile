# Calculadora GLP x GN (Flask + Waitress) + ETL do IM em contêiner.
#
# O contexto do build é esta pasta (6_Calculadora_Flask): o processo de coleta e tratamento
# do IM (processo_im/) e o mapa (processo_im/4_Mapa_GN) já estão dentro dela.
#   docker build -t calculadora-gn .
# Ou, mais simples:  ./Iniciar_Calculadora_Docker.sh
#
# Estágios:  base (dependências) -> teste (roda o pytest) -> final (imagem de execução)

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
# Bibliotecas do processo do IM (extratores e consolidação), com o requirements.txt original dele.
COPY processo_im/1_Processo_Extracao_Dados/Comece_aqui/Fonte_Dados/requirements.txt ./requirements-etl.txt
RUN pip install -r requirements.txt -r requirements-etl.txt


# ---------------------------------------------------------------- testes
# docker build --target teste .
FROM base AS teste
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY . ./
RUN python -m pytest -q


# ---------------------------------------------------------------- execução
FROM base AS final
# Navegador headless para os extratores que usam Selenium (Cegás, Copergás, MSGás e MTGás).
RUN apt-get update \
 && apt-get install -y --no-install-recommends chromium chromium-driver \
 && rm -rf /var/lib/apt/lists/*

ENV HOST=0.0.0.0 \
    PORTA=5000 \
    TZ=America/Sao_Paulo \
    LANG=C.UTF-8 \
    MAPA_GN_DIR=/app/processo_im/4_Mapa_GN \
    TARIFAS_GN_JSON=/app/data/tarifas.json \
    ETL_PROCESSO_DIR=/app/processo_im \
    ETL_ESTADO_DIR=/app/data/etl \
    ETL_AGENDADOR=1 \
    GN_CHROME_BINARY=/usr/bin/chromium \
    HOME=/home/calculadora

RUN useradd --system --uid 10001 --create-home --home-dir /home/calculadora calculadora
COPY --chown=calculadora app.py ./
COPY --chown=calculadora calculadora/ ./calculadora/
COPY --chown=calculadora etl/ ./etl/
COPY --chown=calculadora templates/ ./templates/
COPY --chown=calculadora static/ ./static/
# Base embutida: semente do volume de dados na primeira subida. Depois o ETL a mantém atualizada.
COPY --chown=calculadora data/ ./data/
# Processo do IM. Os extratores gravam na própria pasta Fonte_Dados, por isso o dono é o usuário do app.
COPY --chown=calculadora processo_im/ ./processo_im/
# Pontos de montagem dos volumes do docker-compose. Execucoes_CMD e PlanilhasUf não vêm no git
# (só têm arquivos gerados); sem criá-los aqui, o Docker os cria como root e o ETL não grava.
RUN mkdir -p /app/data/etl \
             /app/processo_im/1_Processo_Extracao_Dados/Comece_aqui/Execucoes_CMD \
             /app/processo_im/1_Processo_Extracao_Dados/Comece_aqui/Fonte_Dados/PlanilhasUf \
             /app/processo_im/1_Processo_Extracao_Dados/Comece_aqui/PassadoTarifas \
             /app/processo_im/1_Processo_Extracao_Dados/Comece_aqui/Planilha_Final \
 && chown calculadora /app/data /app/data/etl \
             /app/processo_im/1_Processo_Extracao_Dados/Comece_aqui/Execucoes_CMD \
             /app/processo_im/1_Processo_Extracao_Dados/Comece_aqui/Fonte_Dados/PlanilhasUf \
             /app/processo_im/1_Processo_Extracao_Dados/Comece_aqui/PassadoTarifas \
             /app/processo_im/1_Processo_Extracao_Dados/Comece_aqui/Planilha_Final

USER calculadora
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORTA\",\"5000\")}/saude', timeout=4)"

CMD ["python", "app.py"]
