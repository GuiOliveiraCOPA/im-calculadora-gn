# Calculadora GLP x GN (Flask + Waitress) em contêiner.
#
# O contexto do build é a RAIZ do projeto, porque a imagem leva também o mapa (4_Mapa_GN):
#   docker build -f 6_Calculadora_Flask/Dockerfile -t calculadora-gn .
# Ou, mais simples:  cd 6_Calculadora_Flask && ./Iniciar_Calculadora_Docker.sh
#
# Estágios:  base (dependências) -> teste (roda o pytest) -> final (imagem de execução)

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY 6_Calculadora_Flask/requirements.txt ./
RUN pip install -r requirements.txt


# ---------------------------------------------------------------- testes
# docker build -f 6_Calculadora_Flask/Dockerfile --target teste .
FROM base AS teste
COPY 6_Calculadora_Flask/requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY 6_Calculadora_Flask/ ./
RUN python -m pytest -q


# ---------------------------------------------------------------- execução
FROM base AS final
ENV HOST=0.0.0.0 \
    PORTA=5000 \
    TZ=America/Sao_Paulo \
    MAPA_GN_DIR=/app/mapa \
    TARIFAS_GN_JSON=/app/data/tarifas.json

RUN useradd --system --uid 10001 --home-dir /app calculadora
COPY --chown=calculadora 6_Calculadora_Flask/app.py ./
COPY --chown=calculadora 6_Calculadora_Flask/calculadora/ ./calculadora/
COPY --chown=calculadora 6_Calculadora_Flask/templates/ ./templates/
COPY --chown=calculadora 6_Calculadora_Flask/static/ ./static/
# Base embutida: usada se nenhuma pasta data/ for montada. Em produção, monte data/ do servidor.
COPY --chown=calculadora 6_Calculadora_Flask/data/ ./data/
COPY --chown=calculadora 4_Mapa_GN/ ./mapa/

USER calculadora
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORTA\",\"5000\")}/saude', timeout=4)"

CMD ["python", "app.py"]
