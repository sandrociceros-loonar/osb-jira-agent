#!/usr/bin/env bash
set -euo pipefail

# Script para consultar o endpoint real do webhook Jira e validar a integridade da Function App.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TERRAFORM_DIR="$REPO_ROOT/terraform"

RAW_URL_ONLY=false
SKIP_CHECK=false

for arg in "$@"; do
  case "$arg" in
    --url-only|-u)
      RAW_URL_ONLY=true
      ;;
    --skip-check)
      SKIP_CHECK=true
      ;;
    --help|-h)
      echo "Uso: $0 [OPÇÕES]"
      echo ""
      echo "Opções:"
      echo "  -u, --url-only    Retorna apenas a URL do webhook (útil para scripts e clipboard)"
      echo "  --skip-check      Não realiza a chamada de verificação de integridade (/api/health)"
      echo "  -h, --help        Exibe esta mensagem de ajuda"
      exit 0
      ;;
  esac
done

WEBHOOK_URL=""
FUNCTION_APP_NAME=""

# 1. Tenta recuperar do estado local do Terraform
if command -v terraform >/dev/null 2>&1 && [ -d "$TERRAFORM_DIR" ]; then
  WEBHOOK_URL=$(terraform -chdir="$TERRAFORM_DIR" output -raw webhook_endpoint_url 2>/dev/null || true)
  FUNCTION_APP_NAME=$(terraform -chdir="$TERRAFORM_DIR" output -raw function_app_name 2>/dev/null || true)
fi

# 2. Fallback: tenta recuperar via Azure CLI se logado
if [ -z "$WEBHOOK_URL" ] && command -v az >/dev/null 2>&1; then
  if az account show >/dev/null 2>&1; then
    APP_NAME=$(az functionapp list --query "[?contains(name, 'osbjira') && state=='Running'].name | [0]" -o tsv 2>/dev/null || true)
    if [ -n "$APP_NAME" ]; then
      FUNCTION_APP_NAME="$APP_NAME"
      DEFAULT_HOST=$(az functionapp show --name "$APP_NAME" --query defaultHostName -o tsv 2>/dev/null || true)
      if [ -n "$DEFAULT_HOST" ]; then
        WEBHOOK_URL="https://${DEFAULT_HOST}/api/jira-webhook"
      fi
    fi
  fi
fi

if [ -z "$WEBHOOK_URL" ]; then
  echo "Erro: Não foi possível obter o endpoint do webhook." >&2
  echo "Certifique-se de que o Terraform foi aplicado ('terraform -chdir=terraform apply') ou que a Azure CLI está autenticada." >&2
  exit 1
fi

if [ "$RAW_URL_ONLY" = true ]; then
  echo "$WEBHOOK_URL"
  exit 0
fi

# Extrai o host e o endpoint de health check
BASE_HOST="$(echo "$WEBHOOK_URL" | sed -E 's|^(https?://[^/]+).*|\1|')"
HEALTH_URL="${BASE_HOST}/api/health"

echo "=================================================="
echo "          OSB Jira Agent - Webhook Endpoint       "
echo "=================================================="
[ -n "$FUNCTION_APP_NAME" ] && echo "Function App : $FUNCTION_APP_NAME"
echo "Webhook URL  : $WEBHOOK_URL"
echo "Health Check : $HEALTH_URL"
echo "--------------------------------------------------"

if [ "$SKIP_CHECK" = false ]; then
  echo -n "Testando conectividade em /api/health... "
  HTTP_RESPONSE=$(curl --silent --show-error --max-time 10 --write-out "\nHTTP_STATUS:%{http_code}" "$HEALTH_URL" 2>&1 || true)
  HTTP_STATUS=$(echo "$HTTP_RESPONSE" | grep "HTTP_STATUS:" | cut -d':' -f2 || true)
  HTTP_BODY=$(echo "$HTTP_RESPONSE" | grep -v "HTTP_STATUS:" || true)

  if [ "$HTTP_STATUS" = "200" ]; then
    echo "ONLINE (HTTP 200)"
    echo "Resposta: $HTTP_BODY"
  else
    echo "FALHA / INACESSÍVEL (Status: ${HTTP_STATUS:-desconhecido})"
    [ -n "$HTTP_BODY" ] && echo "Detalhes: $HTTP_BODY"
  fi
  echo "--------------------------------------------------"
fi

echo "Para configurar no Jira Service Management:"
echo "1. URL do Webhook: $WEBHOOK_URL"
echo "2. Header Secret : X-Atlassian-Webhook-Secret"
echo "=================================================="
