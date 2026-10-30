# Calculadora GLP x GN (Flask + Waitress) lendo a Gold do Databricks.
#
# O contexto do build é esta pasta: código, templates, estáticos e o mapa (mapa/).
# A imagem não leva dados nem credenciais; tudo vem de variáveis de ambiente
# (.env no docker compose; ConfigMap + Secret no Kubernetes).
#   docker build -t calculadora-gn .
#   docker build --target teste .        (roda o pytest)
#
# Estágios:  base (dependências) -> teste (pytest) -> final (imagem de execução)

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
FROM base AS teste
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY . ./
RUN python -m pytest -q


# ---------------------------------------------------------------- execução
FROM base AS final
ENV HOST=0.0.0.0 \
    PORTA=5000 \
    LANG=C.UTF-8 \
    MAPA_GN_DIR=/app/mapa \
    GN_CACHE_PATH=/tmp/gn_cache/tarifas.json \
    HOME=/tmp

# Usuário sem privilégio. A única escrita é a cópia local em /tmp (emptyDir no Kubernetes),
# o que permite readOnlyRootFilesystem.
RUN useradd --system --uid 10001 --no-create-home calculadora
COPY app.py ./
COPY calculadora/ ./calculadora/
COPY templates/ ./templates/
COPY static/ ./static/
COPY mapa/ ./mapa/
COPY scripts/ ./scripts/

USER 10001
EXPOSE 5000

# Usado pelo docker/compose; no Kubernetes valem as probes do Deployment (/saude e /saude/pronto).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORTA\",\"5000\")}/saude', timeout=4)"

CMD ["python", "app.py"]
