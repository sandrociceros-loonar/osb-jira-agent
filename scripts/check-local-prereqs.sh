#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
UPDATE_TOOLS=false
CHECK_ONLY=false
PROVIDER="${MODEL_PROVIDER:-}"
LOCAL_MODEL_ALIAS="${FOUNDRY_LOCAL_MODEL_ALIAS:-phi-4-mini}"
OLLAMA_MODEL_NAME="${OLLAMA_MODEL_NAME:-}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-}"
CHANGE_PLAN=()
BLOCKERS=()
WARNINGS=()
UV_BIN=""
NODE_REQUIRED=false
CURL_REQUIRED=false
AZURE_CLI_MISSING=false
NEEDS_LOCAL_SETUP=false
LOCAL_SETUP_VERIFIED=false
OLLAMA_SETUP_VERIFIED=false
NEEDS_OLLAMA_SETUP=false

usage() {
  cat <<'EOF'
Uso: ./scripts/check-local-prereqs.sh [--provider azure|foundry-local|ollama] [--model ALIAS] [--check-only] [--update]

  --provider    Seleciona o backend a preparar (padrão: MODEL_PROVIDER ou azure).
  --model       Alias do modelo Foundry Local (padrão: FOUNDRY_LOCAL_MODEL_ALIAS ou phi-4-mini).
  --check-only  Apenas verifica os requisitos; não instala nem atualiza.
  --update      Inclui atualizações das ferramentas já instaladas no plano.
                A atualização só acontece após confirmação interativa.
EOF
}

read_setting() {
  local key="$1"
  local file line value

  for file in "${ROOT_DIR}/.env" "${ROOT_DIR}/local.settings.json"; do
    [[ -f "$file" ]] || continue
    if [[ "$file" == *.env ]]; then
      line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$file" | tail -n 1 || true)"
      [[ -n "$line" ]] || continue
      value="${line#*=}"
      value="${value#\"}"
      value="${value%\"}"
      value="${value#\'}"
      value="${value%\'}"
      printf '%s\n' "$value"
      return 0
    fi
    line="$(grep -E "\"${key}\"[[:space:]]*:" "$file" | tail -n 1 || true)"
    [[ -n "$line" ]] || continue
    printf '%s\n' "$line" |
      sed -E "s/.*\"${key}\"[[:space:]]*:[[:space:]]*\"([^\"]*)\".*/\\1/"
    return 0
  done
  return 1
}

if [[ -z "$PROVIDER" ]]; then
  PROVIDER="$(read_setting MODEL_PROVIDER || printf 'azure')"
fi
if [[ -z "${FOUNDRY_LOCAL_MODEL_ALIAS:-}" ]]; then
  LOCAL_MODEL_ALIAS="$(read_setting FOUNDRY_LOCAL_MODEL_ALIAS || printf 'phi-4-mini')"
fi
if [[ -z "${FOUNDRY_LOCAL_BASE_URL:-}" ]]; then
  FOUNDRY_LOCAL_BASE_URL="$(read_setting FOUNDRY_LOCAL_BASE_URL || printf 'http://127.0.0.1:5273/v1')"
  export FOUNDRY_LOCAL_BASE_URL
fi
if [[ -z "${OLLAMA_MODEL_NAME:-}" ]]; then
  OLLAMA_MODEL_NAME="$(read_setting OLLAMA_MODEL_NAME || printf 'qwen3:4b')"
fi
if [[ -z "${OLLAMA_BASE_URL:-}" ]]; then
  OLLAMA_BASE_URL="$(read_setting OLLAMA_BASE_URL || printf 'http://127.0.0.1:11434/v1')"
fi

while (($# > 0)); do
  case "$1" in
    --provider)
      (($# >= 2)) || { usage >&2; exit 2; }
      PROVIDER="$2"
      shift 2
      ;;
    --model)
      (($# >= 2)) || { usage >&2; exit 2; }
      LOCAL_MODEL_ALIAS="$2"
      OLLAMA_MODEL_NAME="$2"
      shift 2
      ;;
    --check-only)
      CHECK_ONLY=true
      shift
      ;;
    --update)
      UPDATE_TOOLS=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$PROVIDER" != "azure" && "$PROVIDER" != "foundry-local" && "$PROVIDER" != "ollama" ]]; then
  printf 'Provedor inválido: %s (use azure, foundry-local ou ollama).\n' "$PROVIDER" >&2
  exit 2
fi

say_status() {
  printf '%-10s %s\n' "$1" "$2"
}

is_supported_linux() {
  [[ -r /etc/os-release ]] || return 1
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" || "${ID:-}" == "debian" ]]
}

has_admin_access() {
  [[ "${EUID}" -eq 0 ]] || command -v sudo >/dev/null 2>&1
}

as_admin() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

get_uv() {
  if command -v uv >/dev/null 2>&1; then
    command -v uv
  elif [[ -x "${HOME}/.local/bin/uv" ]]; then
    printf '%s\n' "${HOME}/.local/bin/uv"
  else
    return 1
  fi
}

python_version_supported() {
  local executable="$1"
  local version

  version="$("$executable" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)" ||
    return 1
  [[ "$version" == "3.11" || "$version" == "3.12" || "$version" == "3.13" ]]
}

check_python_runtime() {
  local candidate

  if [[ -x "${ROOT_DIR}/.venv/bin/python" ]] &&
    python_version_supported "${ROOT_DIR}/.venv/bin/python"; then
    return 0
  fi

  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
      python_version_supported "$(command -v "$candidate")"; then
      return 0
    fi
  done
  return 1
}

check_project_python_dependencies() {
  local uv

  uv="$(get_uv)" || return 1
  local extras=(--extra dev)
  if [[ "$PROVIDER" == "foundry-local" ]]; then
    extras+=(--extra local-model)
  fi
  (
    cd "$ROOT_DIR"
    "$uv" run --locked --no-sync "${extras[@]}" python -c \
      'import azure.ai.agentserver.invocations, azure.ai.projects, azure.functions, azure.identity, debugpy, httpx, openai, pydantic, pydantic_settings, starlette'
    if [[ "$PROVIDER" == "foundry-local" ]]; then
      "$uv" run --locked --no-sync --extra local-model python -c \
        'import foundry_local_sdk'
    fi
  ) >/dev/null 2>&1
}

check_endpoint_configured() {
  local file

  for file in "${ROOT_DIR}/.env" "${ROOT_DIR}/local.settings.json"; do
    [[ -f "$file" ]] || continue
    if grep -E 'AZURE_AI_PROJECT_ENDPOINT' "$file" |
      grep -Eq 'https://[^<>"[:space:]]+' &&
      ! grep -E 'AZURE_AI_PROJECT_ENDPOINT' "$file" | grep -q '[<>]'; then
      return 0
    fi
  done
  return 1
}

check_local_storage_config() {
  [[ -f "${ROOT_DIR}/local.settings.json" ]] &&
    grep -q 'UseDevelopmentStorage=true' "${ROOT_DIR}/local.settings.json"
}

requires_azurite() {
  if [[ -f "${ROOT_DIR}/local.settings.json" ]]; then
    check_local_storage_config
  else
    grep -q 'UseDevelopmentStorage=true' "${ROOT_DIR}/local.settings.json.example"
  fi
}

preflight() {
  local node_major=""
  local needs_uv=false
  local needs_python=false
  local needs_functions_core_tools=false
  local needs_azurite=false
  local needs_project_sync=false

  printf 'Pré-flight: requisitos para desenvolvimento local\n'
  printf 'Projeto: %s\n\n' "$ROOT_DIR"
  say_status "MODO" "$PROVIDER"

  if check_python_runtime; then
    say_status "OK" "Python 3.11/3.12/3.13"
  else
    say_status "FALTA" "Python 3.11/3.12/3.13"
    needs_python=true
    CHANGE_PLAN+=("instalar Python 3.13 gerenciado por uv")
  fi

  if UV_BIN="$(get_uv)"; then
    say_status "OK" "$("$UV_BIN" --version)"
    if [[ "$UPDATE_TOOLS" == true ]]; then
      CHANGE_PLAN+=("atualizar uv")
    fi
  else
    say_status "FALTA" "uv"
    needs_uv=true
    CHANGE_PLAN+=("instalar uv")
  fi

  if command -v func >/dev/null 2>&1 && func --version >/dev/null 2>&1; then
    say_status "OK" "Azure Functions Core Tools $(func --version 2>/dev/null | head -n 1)"
    if [[ "$UPDATE_TOOLS" == true ]]; then
      needs_functions_core_tools=true
      CHANGE_PLAN+=("atualizar Azure Functions Core Tools v4")
    fi
  else
    say_status "FALTA" "Azure Functions Core Tools v4"
    needs_functions_core_tools=true
    CHANGE_PLAN+=("instalar Azure Functions Core Tools v4")
  fi

  if [[ "$PROVIDER" == "azure" ]]; then
    if command -v az >/dev/null 2>&1 && az version >/dev/null 2>&1; then
      say_status "OK" "Azure CLI disponível"
      if az account show >/dev/null 2>&1; then
        say_status "OK" "Azure CLI autenticada"
      else
        say_status "AÇÃO" "Azure CLI sem sessão; será necessário executar az login"
        WARNINGS+=("autenticar na Azure CLI com az login antes de chamar o Foundry")
      fi
      if [[ "$UPDATE_TOOLS" == true ]]; then
        CHANGE_PLAN+=("atualizar Azure CLI")
      fi
    else
      say_status "FALTA" "Azure CLI"
      AZURE_CLI_MISSING=true
      CHANGE_PLAN+=("instalar Azure CLI")
    fi
  elif [[ "$PROVIDER" == "foundry-local" ]]; then
    say_status "IGNORADO" "Azure CLI não é necessária para Foundry Local"
    NEEDS_LOCAL_SETUP=true
    needs_project_sync=true
    CHANGE_PLAN+=("sincronizar o SDK Foundry Local, baixar/carregar '${LOCAL_MODEL_ALIAS}' e testar function calling")
  else
    say_status "IGNORADO" "Azure CLI não é necessária para Ollama"
    if ! command -v ollama >/dev/null 2>&1; then
      say_status "FALTA" "Ollama CLI"
      BLOCKERS+=("instale o Ollama pelo instalador oficial: https://ollama.com/download")
    elif ! ollama list >/dev/null 2>&1; then
      say_status "FALTA" "Servidor Ollama em execução"
      BLOCKERS+=("inicie o serviço Ollama antes de preparar o modelo")
    elif ollama show "$OLLAMA_MODEL_NAME" >/dev/null 2>&1; then
      say_status "OK" "Ollama disponível; modelo '${OLLAMA_MODEL_NAME}' instalado"
    else
      say_status "AÇÃO" "Ollama disponível; modelo '${OLLAMA_MODEL_NAME}' ainda não instalado"
      NEEDS_OLLAMA_SETUP=true
      CHANGE_PLAN+=("baixar '${OLLAMA_MODEL_NAME}' pelo Ollama e validar function calling")
    fi
  fi

  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || true)"
    if [[ "$node_major" =~ ^[0-9]+$ ]] && (( node_major >= 20 )); then
      say_status "OK" "Node.js $(node --version), npm $(npm --version)"
    else
      say_status "FALTA" "Node.js 20+ e npm (necessários para Core Tools/Azurite)"
      NODE_REQUIRED=true
      CHANGE_PLAN+=("instalar ou atualizar Node.js e npm via apt")
    fi
    if [[ "$UPDATE_TOOLS" == true && "$NODE_REQUIRED" == false ]]; then
      NODE_REQUIRED=true
      CHANGE_PLAN+=("atualizar Node.js e npm via apt")
    fi
  else
    say_status "FALTA" "Node.js 20+ e npm (necessários para Core Tools/Azurite)"
    NODE_REQUIRED=true
    CHANGE_PLAN+=("instalar Node.js e npm via apt")
  fi

  if requires_azurite; then
    if command -v azurite >/dev/null 2>&1 && azurite --version >/dev/null 2>&1; then
      say_status "OK" "Azurite $(azurite --version 2>/dev/null | head -n 1)"
      if [[ "$UPDATE_TOOLS" == true ]]; then
        needs_azurite=true
        CHANGE_PLAN+=("atualizar Azurite")
      fi
    else
      say_status "FALTA" "Azurite (requerido por UseDevelopmentStorage=true)"
      needs_azurite=true
      CHANGE_PLAN+=("instalar Azurite")
    fi
  else
    say_status "IGNORADO" "Azurite (não requerido pela configuração atual de armazenamento)"
  fi

  if check_project_python_dependencies; then
    say_status "OK" "Dependências Python do projeto sincronizadas"
  else
    say_status "FALTA" "Dependências Python do projeto (uv sync --all-extras --locked)"
    needs_project_sync=true
    CHANGE_PLAN+=("sincronizar dependências Python conforme uv.lock")
  fi

  if requires_azurite; then
    if command -v curl >/dev/null 2>&1; then
      say_status "OK" "curl"
    else
      say_status "FALTA" "curl (necessário para a verificação HTTP do Azurite)"
      CURL_REQUIRED=true
      CHANGE_PLAN+=("instalar curl via apt")
    fi
  else
    say_status "IGNORADO" "curl (não necessário sem Azurite)"
  fi

  if [[ "$PROVIDER" == "azure" ]]; then
    if check_endpoint_configured; then
      say_status "OK" "Endpoint do Microsoft Foundry configurado"
    else
      say_status "AÇÃO" "Configure AZURE_AI_PROJECT_ENDPOINT em .env ou local.settings.json"
      WARNINGS+=("configurar o endpoint do projeto Foundry e o nome do deployment")
    fi
  elif [[ "$PROVIDER" == "foundry-local" ]]; then
    say_status "OK" "Modelo local configurado: ${LOCAL_MODEL_ALIAS}"
    say_status "AÇÃO" "O SDK local será preparado após confirmação; a checagem não baixa o modelo"
  else
    say_status "OK" "Endpoint Ollama: ${OLLAMA_BASE_URL}"
  fi

  if check_local_storage_config; then
    say_status "OK" "local.settings.json configura UseDevelopmentStorage=true"
  else
    say_status "AÇÃO" "Crie local.settings.json a partir de local.settings.json.example"
    WARNINGS+=("criar local.settings.json para iniciar o host local com Azurite")
  fi

  if [[ ! -f "${ROOT_DIR}/.env" && ! -f "${ROOT_DIR}/local.settings.json" ]]; then
    say_status "AÇÃO" "Arquivos locais de configuração ainda não foram criados"
  fi

  if ((${#CHANGE_PLAN[@]} > 0)); then
    printf '\nAlterações possíveis após confirmação:\n'
    printf '  - %s\n' "${CHANGE_PLAN[@]}"
  else
    printf '\nNenhuma instalação ou sincronização necessária.\n'
  fi

  if [[ "$NODE_REQUIRED" == true || "$AZURE_CLI_MISSING" == true || "$CURL_REQUIRED" == true ]]; then
    if ! is_supported_linux || ! command -v apt-get >/dev/null 2>&1; then
      BLOCKERS+=("instalador automático de pacotes de sistema disponível apenas em Ubuntu/Debian com apt")
    elif ! has_admin_access; then
      BLOCKERS+=("sudo ou privilégios de root necessários para instalar pacotes de sistema")
    fi
  fi

  if ((${#BLOCKERS[@]} > 0)); then
    printf '\nBloqueios para instalação automática:\n'
    printf '  - %s\n' "${BLOCKERS[@]}"
  fi

  # Keep these locals available to the install phase via shell globals.
  NEEDS_UV="$needs_uv"
  NEEDS_PYTHON="$needs_python"
  NEEDS_FUNCTIONS_CORE_TOOLS="$needs_functions_core_tools"
  NEEDS_AZURITE="$needs_azurite"
  NEEDS_PROJECT_SYNC="$needs_project_sync"
}

install_system_packages() {
  local packages=(ca-certificates)
  if [[ "$NODE_REQUIRED" == true ]]; then
    packages+=(nodejs npm)
  fi
  if [[ "$CURL_REQUIRED" == true ]] || ! command -v curl >/dev/null 2>&1; then
    packages+=(curl)
  fi
  as_admin apt-get update
  as_admin apt-get install -y "${packages[@]}"
}

install_uv() {
  if [[ "$NEEDS_UV" == true ]]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    UV_BIN="$(get_uv)"
  elif [[ "$UPDATE_TOOLS" == true ]]; then
    "$UV_BIN" self update
  fi

  if [[ "$NEEDS_PYTHON" == true ]]; then
    "$UV_BIN" python install 3.13
  fi
}

install_azure_cli() {
  local installer

  if [[ "$AZURE_CLI_MISSING" != true ]] && command -v az >/dev/null 2>&1; then
    [[ "$UPDATE_TOOLS" != true ]] || az upgrade --yes
    return
  fi

  installer="$(mktemp)"
  curl -fsSL https://aka.ms/InstallAzureCLIDeb -o "$installer"
  if ! as_admin bash "$installer"; then
    rm -f -- "$installer"
    return 1
  fi
  rm -f -- "$installer"
}

npm_global_install() {
  local prefix
  prefix="$(npm config get prefix)"
  if [[ -w "$prefix" ]]; then
    npm install --global "$@"
  else
    as_admin npm install --global "$@"
  fi

  if [[ -d "${prefix}/bin" && ":${PATH}:" != *":${prefix}/bin:"* ]]; then
    PATH="${prefix}/bin:${PATH}"
    export PATH
  fi
}

install_node_tools() {
  if [[ "$NEEDS_FUNCTIONS_CORE_TOOLS" == true ]]; then
    npm_global_install azure-functions-core-tools@4 --unsafe-perm true
  elif [[ "$UPDATE_TOOLS" == true ]]; then
    npm_global_install azure-functions-core-tools@4 --unsafe-perm true
  fi

  if [[ "$NEEDS_AZURITE" == true || "$UPDATE_TOOLS" == true ]]; then
    npm_global_install azurite
  fi
}

run_project_sync() {
  if [[ "$NEEDS_PROJECT_SYNC" == true || "$UPDATE_TOOLS" == true ]]; then
    local extras=(--extra dev)
    if [[ "$PROVIDER" == "foundry-local" ]]; then
      extras+=(--extra local-model)
    fi
    (
      cd "$ROOT_DIR"
      "$UV_BIN" sync --locked "${extras[@]}"
    )
  fi
}

test_azurite() {
  local temp_dir blob_port queue_port table_port pid http_code attempt
  temp_dir="$(mktemp -d)"
  blob_port=$((20000 + ($$ % 10000)))
  queue_port=$((blob_port + 1))
  table_port=$((blob_port + 2))

  azurite --silent --location "$temp_dir" \
    --blobHost 127.0.0.1 --blobPort "$blob_port" \
    --queueHost 127.0.0.1 --queuePort "$queue_port" \
    --tableHost 127.0.0.1 --tablePort "$table_port" \
    >"${temp_dir}/azurite.log" 2>&1 &
  pid=$!

  for attempt in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      printf 'Azurite encerrou durante o teste. Log: %s\n' "${temp_dir}/azurite.log" >&2
      cat "${temp_dir}/azurite.log" >&2
      rm -rf -- "$temp_dir"
      return 1
    fi
    http_code="$(curl -sS --max-time 1 -o /dev/null -w '%{http_code}' \
      "http://127.0.0.1:${blob_port}/devstoreaccount1?comp=list" 2>/dev/null || true)"
    if [[ "$http_code" =~ ^[2-4][0-9][0-9]$ ]]; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      rm -rf -- "$temp_dir"
      return 0
    fi
    sleep 0.25
  done

  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  printf 'Azurite não respondeu no teste local. Log: %s\n' "${temp_dir}/azurite.log" >&2
  cat "${temp_dir}/azurite.log" >&2
  rm -rf -- "$temp_dir"
  return 1
}

verify_components() {
  local failed=false

  printf '\nVerificação funcional pós-pré-flight/instalação\n'

  if ! check_python_runtime; then
    say_status "FALHA" "Python suportado (3.11/3.12/3.13)"
    failed=true
  else
    say_status "OK" "Python suportado"
  fi

  if ! UV_BIN="$(get_uv)" || ! "$UV_BIN" --version; then
    say_status "FALHA" "uv"
    failed=true
  else
    say_status "OK" "uv executável"
  fi

  if ! command -v func >/dev/null 2>&1 ||
    ! func --version >/dev/null 2>&1 ||
    ! func start --help >/dev/null 2>&1; then
    say_status "FALHA" "Azure Functions Core Tools"
    failed=true
  else
    say_status "OK" "Azure Functions Core Tools executável"
  fi

  if [[ "$PROVIDER" == "azure" ]]; then
    if ! command -v az >/dev/null 2>&1 || ! az version >/dev/null 2>&1; then
      say_status "FALHA" "Azure CLI"
      failed=true
    else
      say_status "OK" "Azure CLI executável"
    fi
  elif [[ "$PROVIDER" == "foundry-local" ]]; then
    if [[ "$LOCAL_SETUP_VERIFIED" == true ]]; then
      say_status "OK" "Foundry Local, modelo e function calling verificados durante a preparação"
    elif ! "$UV_BIN" run --locked --no-sync --extra local-model \
      python scripts/setup_foundry_local.py --model "$LOCAL_MODEL_ALIAS" \
      --base-url "$FOUNDRY_LOCAL_BASE_URL" --verify-only; then
      say_status "FALHA" "Foundry Local, modelo, servidor e function calling"
      failed=true
    else
      say_status "OK" "Foundry Local, modelo, servidor e function calling"
    fi
  else
    if [[ "$OLLAMA_SETUP_VERIFIED" == true ]]; then
      say_status "OK" "Ollama, modelo e function calling verificados durante a preparação"
    elif ! command -v ollama >/dev/null 2>&1 ||
      ! ollama show "$OLLAMA_MODEL_NAME" >/dev/null 2>&1 ||
      ! "$UV_BIN" run --locked --no-sync python scripts/setup_ollama.py \
        --model "$OLLAMA_MODEL_NAME" --base-url "$OLLAMA_BASE_URL"; then
      say_status "FALHA" "Ollama, modelo ou function calling"
      failed=true
    else
      say_status "OK" "Ollama, modelo, endpoint e function calling"
    fi
  fi

  if requires_azurite; then
    if ! command -v azurite >/dev/null 2>&1 || ! azurite --version; then
      say_status "FALHA" "Azurite"
      failed=true
    elif ! command -v curl >/dev/null 2>&1 || ! test_azurite; then
      say_status "FALHA" "Azurite não iniciou ou não respondeu ao teste HTTP"
      failed=true
    else
      say_status "OK" "Azurite iniciou e respondeu via HTTP"
    fi
  else
    say_status "IGNORADO" "Azurite"
  fi

  if check_project_python_dependencies; then
    say_status "OK" "Importação das dependências da aplicação"
  else
    say_status "FALHA" "Dependências Python; execute uv sync --all-extras --locked"
    failed=true
  fi

  if [[ "$failed" == true ]]; then
    return 1
  fi
}

main() {
  local response
  preflight

  if [[ "$CHECK_ONLY" == true ]]; then
    printf '\nModo de verificação: nenhuma alteração foi feita.\n'
    ((${#CHANGE_PLAN[@]} == 0 && ${#WARNINGS[@]} == 0))
    return
  fi

  if ((${#BLOCKERS[@]} > 0)); then
    printf '\nNão é possível executar todas as instalações automaticamente neste sistema.\n' >&2
    return 1
  fi

  if ((${#CHANGE_PLAN[@]} > 0)); then
    if [[ ! -t 0 ]]; then
      printf '\nSem terminal interativo: nenhuma alteração foi feita. Execute novamente em um terminal para confirmar.\n' >&2
      return 2
    fi

    printf '\nNenhuma instalação ou atualização será feita sem confirmação explícita.\n'
    read -r -p "Confirmar as alterações listadas acima? [s/N] " response
    case "$response" in
      s|S|sim|SIM|Sim) ;;
      *)
        printf 'Operação cancelada; nenhuma instalação ou atualização foi feita.\n'
        return 1
        ;;
    esac

    if [[ "$NODE_REQUIRED" == true || "$AZURE_CLI_MISSING" == true || "$CURL_REQUIRED" == true ]]; then
      install_system_packages
    fi
    install_uv
    if [[ "$PROVIDER" == "azure" ]]; then
      install_azure_cli
    fi
    install_node_tools
    if [[ "$NEEDS_LOCAL_SETUP" == true ]]; then
      printf '\nPreparando ambiente Foundry Local\n'
      printf '  1. Sincronizando dependências do SDK Foundry Local\n'
    fi
    run_project_sync
    if [[ "$NEEDS_LOCAL_SETUP" == true ]]; then
      printf '  2. Execution providers necessários\n'
      printf '  3. Modelo %s (download, se necessário) e carregamento\n' \
        "$LOCAL_MODEL_ALIAS"
      printf '  4. Servidor local e teste de function calling\n\n'
      if (
        cd "$ROOT_DIR"
        "$UV_BIN" run --locked --extra local-model \
          python -X faulthandler scripts/setup_foundry_local.py --model "$LOCAL_MODEL_ALIAS" \
          --base-url "$FOUNDRY_LOCAL_BASE_URL"
      ); then
        LOCAL_SETUP_VERIFIED=true
      else
        local_setup_status=$?
        say_status "FALHA" "Preparação do Foundry Local (código de saída ${local_setup_status})"
        return "$local_setup_status"
      fi
    fi
    if [[ "$NEEDS_OLLAMA_SETUP" == true ]]; then
      printf '\nPreparando modelo Ollama\n'
      printf '  1. Baixando o modelo %s (o Ollama pode ocupar vários GB)\n' \
        "$OLLAMA_MODEL_NAME"
      ollama pull "$OLLAMA_MODEL_NAME"
      printf '  2. Validando endpoint local e function calling\n\n'
      (
        cd "$ROOT_DIR"
        "$UV_BIN" run --locked --no-sync python scripts/setup_ollama.py \
          --model "$OLLAMA_MODEL_NAME" --base-url "$OLLAMA_BASE_URL"
      )
      OLLAMA_SETUP_VERIFIED=true
    fi
  fi

  verify_components

  if ((${#WARNINGS[@]} > 0)); then
    printf '\nAinda requer configuração manual:\n'
    printf '  - %s\n' "${WARNINGS[@]}"
  fi

  if [[ "$PROVIDER" == "azure" ]] && ! check_endpoint_configured; then
    return 1
  fi
}

main "$@"
