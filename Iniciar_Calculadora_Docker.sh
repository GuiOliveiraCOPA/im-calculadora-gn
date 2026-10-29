#!/usr/bin/env bash
# Calculadora GLP x GN em contêiner (Docker ou Podman) — servidor Linux.
#
# Uso:
#   ./Iniciar_Calculadora_Docker.sh             # constrói (com testes) e sobe em segundo plano na porta 5000
#   PORTA=8080 ./Iniciar_Calculadora_Docker.sh
#   ./Iniciar_Calculadora_Docker.sh --parar      # derruba o contêiner
#   ./Iniciar_Calculadora_Docker.sh --logs       # acompanha os logs
#
# O contêiner reinicia sozinho com o servidor (restart: unless-stopped).
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"
export PORTA="${PORTA:-5000}"

# Docker (docker compose) ou Podman (podman compose / podman-compose), o que houver.
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  MOTOR=docker; COMPOSE=(docker compose)
elif command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
  MOTOR=podman; COMPOSE=(podman compose)
elif command -v podman-compose >/dev/null 2>&1; then
  MOTOR=podman; COMPOSE=(podman-compose)
else
  echo "ERRO: instale o Docker (com o plugin compose) ou o Podman + podman-compose." >&2
  echo "  AlmaLinux: sudo dnf install -y podman podman-compose" >&2
  exit 1
fi

case "${1:-}" in
  --parar) exec "${COMPOSE[@]}" down ;;
  --logs)  exec "${COMPOSE[@]}" logs -f ;;
esac

if [ ! -f data/tarifas.json ]; then
  echo "ERRO: data/tarifas.json não encontrado. Rode antes o AtualizarDados.sh (1_Processo_Extracao_Dados/Comece_aqui)." >&2
  exit 1
fi

echo "========================================"
echo "Calculadora GLP x GN (contêiner, $MOTOR)"
echo "========================================"

echo "Rodando os testes na imagem..."
"$MOTOR" build -q -f Dockerfile --target teste . >/dev/null

echo "Construindo e subindo o contêiner..."
"${COMPOSE[@]}" up -d --build

echo -n "Aguardando a calculadora responder"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORTA}/saude" >/dev/null 2>&1; then
    echo
    curl -fsS "http://127.0.0.1:${PORTA}/saude"; echo
    ENDERECO="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
    echo "Acesse: http://${ENDERECO:-127.0.0.1}:${PORTA}/"
    exit 0
  fi
  echo -n "."; sleep 1
done
echo
echo "ERRO: a calculadora não respondeu. Veja: ${COMPOSE[*]} logs" >&2
exit 1
