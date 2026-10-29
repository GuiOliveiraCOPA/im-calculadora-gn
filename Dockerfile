# Calculadora GLP x GN (Flask + Waitress) em contêiner.
#
# O contexto do build é a raiz do repositório (a imagem leva também o mapa, pasta mapa/):
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
RUN pip install -r requirements.txt


# ---------------------------------------------------------------- testes
# docker build --target teste .
FROM base AS teste
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY . ./
RUN python -m pytest -q


# ---------------------------------------------------------------- execução
FROM base AS final
ENV HOST=0.0.0.0 \
    PORTA=5000 \
    TZ=America/Sao_Paulo \
    MAPA_GN_DIR=/app/mapa \
    TARIFAS_GN_JSON=/app/data/tarifas.json

RUN useradd --system --uid 10001 --home-dir /app calculadora
COPY --chown=calculadora app.py ./
COPY --chown=calculadora calculadora/ ./calculadora/
COPY --chown=calculadora templates/ ./templates/
COPY --chown=calculadora static/ ./static/
# Base embutida: usada se nenhuma pasta data/ for montada. Em produção, monte data/ do servidor.
COPY --chown=calculadora data/ ./data/
COPY --chown=calculadora mapa/ ./mapa/

USER calculadora
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORTA\",\"5000\")}/saude', timeout=4)"

CMD ["python", "app.py"]
