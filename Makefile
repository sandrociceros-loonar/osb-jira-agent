# ==============================================================================
# Makefile - OSB Jira Commercial CRM Agent
# Gerencia ciclo de desenvolvimento, pré-requisitos, testes, compilação, package
# e deploy no Microsoft Foundry (Hosted Agent com tools hospedadas) e Azure Functions.
# ==============================================================================

SHELL := /usr/bin/env bash
AZURE_USER_AGENT := AZURE_DEV_USER_AGENT=microsoft_foundry_skill
AGENT_SERVICE := osb-jira-agent

.PHONY: help setup prereqs prereqs-update config install test lint format compile package \
        run run-ollama run-foundry run-foundry-no-client deploy deploy-foundry deploy-function \
        status-foundry tf-init tf-validate tf-plan tf-apply clean

help:
	@echo "=============================================================================="
	@echo "OSB Jira Commercial CRM Agent - Comandos de Automação"
	@echo "=============================================================================="
	@echo "Configuração & Pré-requisitos de Desenvolvimento:"
	@echo "  make setup               - Orquestra a preparação completa: config + prereqs + install"
	@echo "  make prereqs             - Diagnostica pré-requisitos de dev local (--check-only)"
	@echo "  make prereqs-update      - Executa pré-requisitos com opção de atualização interativa"
	@echo "  make config              - Inicializa .env e local.settings.json se não existirem"
	@echo "  make install             - Instala/sincroniza dependências do projeto com uv"
	@echo ""
	@echo "Desenvolvimento & Qualidade:"
	@echo "  make test                - Executa suíte de testes com pytest"
	@echo "  make lint                - Checagem estática de código com ruff"
	@echo "  make format              - Formatação e auto-fix com ruff"
	@echo "  make compile             - Valida sintaxe e compila bytecode dos módulos Python"
	@echo "  make package             - Gera requirements.txt atualizado e valida integridade"
	@echo ""
	@echo "Execução Local & Testes no Foundry:"
	@echo "  make run-foundry         - Executa o Hosted Agent localmente com o Agent Inspector"
	@echo "  make run-foundry-no-client - Inicia o servidor local do Foundry sem abrir UI"
	@echo "  make run                 - Inicia a Azure Function localmente (func start)"
	@echo "  make run-ollama          - Inicia localmente com modelo Ollama"
	@echo ""
	@echo "Implantação em Produção (Tools hospedadas no Foundry):"
	@echo "  make deploy              - Pipeline completo de produção (test -> lint -> compile -> package -> deploy-foundry)"
	@echo "  make deploy-foundry      - Publica o Hosted Agent (com tools) no Microsoft Foundry"
	@echo "  make deploy-function     - Publica a Azure Function no Azure (remote build)"
	@echo "  make status-foundry      - Exibe status e versão ativa do agente no Foundry"
	@echo ""
	@echo "Infraestrutura (Terraform):"
	@echo "  make tf-init             - Inicializa os módulos Terraform"
	@echo "  make tf-validate         - Valida a sintaxe Terraform"
	@echo "  make tf-plan             - Executa terraform plan"
	@echo "  make tf-apply            - Aplica alterações de infraestrutura"
	@echo ""
	@echo "Manutenção:"
	@echo "  make clean               - Remove caches de testes, compilação e temporários"
	@echo "=============================================================================="

# ------------------------------------------------------------------------------
# Configuração & Pré-requisitos de Desenvolvimento
# ------------------------------------------------------------------------------
setup: config prereqs install
	@echo "==> Ambiente de desenvolvimento configurado e pronto!"

config:
	@echo "==> Verificando arquivos de configuração locais..."
	@test -f .env || (cp .env.example .env && echo "Criado .env a partir de .env.example")
	@test -f local.settings.json || (cp local.settings.json.example local.settings.json && echo "Criado local.settings.json a partir de local.settings.json.example")
	@echo "==> Arquivos de configuração prontos."

prereqs:
	@echo "==> Diagnosticando pré-requisitos do ambiente local..."
	@./scripts/check-local-prereqs.sh --check-only

prereqs-update:
	@echo "==> Verificando e atualizando pré-requisitos locais..."
	@./scripts/check-local-prereqs.sh --update

install:
	uv sync --all-extras --group dev

# ------------------------------------------------------------------------------
# Desenvolvimento & Qualidade
# ------------------------------------------------------------------------------
test:
	uv run pytest --verbose

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

format:
	uv run ruff format src tests
	uv run ruff check --fix src tests

compile:
	@echo "==> Verificando sintaxe e compilando bytecode Python..."
	uv run python -m compileall src/ tests/
	@echo "==> Verificação de sintaxe concluída com sucesso."

package:
	@echo "==> Sincronizando requirements.txt com lockfile..."
	uv export --format requirements-txt --no-dev --no-hashes --no-emit-project -o requirements.txt
	@echo "==> Validando integridade do repositório..."
	@git diff --check || (echo "ERRO: Espaços ou conflitos detectados no git diff" && exit 1)
	@echo "==> Pacote pronto para build remoto no Microsoft Foundry e Azure."

# ------------------------------------------------------------------------------
# Execução Local & Testes no Foundry
# ------------------------------------------------------------------------------
run-foundry:
	@echo "==> Iniciando Hosted Agent localmente no Microsoft Foundry com Agent Inspector..."
	$(AZURE_USER_AGENT) azd ai agent run $(AGENT_SERVICE)

run-foundry-no-client:
	@echo "==> Iniciando Hosted Agent localmente (sem abrir navegador)..."
	$(AZURE_USER_AGENT) azd ai agent run $(AGENT_SERVICE) --no-client

run:
	func start

run-ollama:
	MODEL_PROVIDER=ollama OLLAMA_MODEL_NAME="$${OLLAMA_MODEL_NAME:-qwen3:4b}" \
		OLLAMA_BASE_URL="$${OLLAMA_BASE_URL:-http://127.0.0.1:11434/v1}" func start

# ------------------------------------------------------------------------------
# Implantação em Produção (Tools hospedadas no Foundry)
# ------------------------------------------------------------------------------
deploy: test lint compile package deploy-foundry status-foundry
	@echo "==> Deploy em produção no Microsoft Foundry concluído com sucesso!"

deploy-foundry:
	@echo "==> Publicando Hosted Agent no Microsoft Foundry..."
	$(AZURE_USER_AGENT) azd deploy $(AGENT_SERVICE) --no-prompt

status-foundry:
	@echo "==> Verificando status do Hosted Agent no Foundry..."
	$(AZURE_USER_AGENT) azd ai agent show $(AGENT_SERVICE) --output json

deploy-function:
	@echo "==> Publicando Azure Function com build remoto..."
	@APP_NAME=$$(terraform -chdir=terraform output -raw function_app_name 2>/dev/null || echo ""); \
	if [ -z "$$APP_NAME" ]; then \
		echo "Informe o nome da Function App com: func azure functionapp publish <nome> --build remote"; \
		exit 1; \
	fi; \
	func azure functionapp publish $$APP_NAME --build remote

# ------------------------------------------------------------------------------
# Infraestrutura (Terraform)
# ------------------------------------------------------------------------------
tf-init:
	terraform -chdir=terraform init

tf-validate:
	terraform -chdir=terraform validate

tf-plan:
	terraform -chdir=terraform plan

tf-apply:
	terraform -chdir=terraform apply

# ------------------------------------------------------------------------------
# Limpeza
# ------------------------------------------------------------------------------
clean:
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
