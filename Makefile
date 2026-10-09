.PHONY: help install test lint format requirements run tf-init tf-plan tf-apply clean

help:
	@echo "OSB Jira Agent - Comandos de Automação:"
	@echo "  make install       - Instala dependências locais com uv"
	@echo "  make test          - Executa suite de testes com pytest"
	@echo "  make lint          - Executa checagem de código com ruff"
	@echo "  make format        - Formata o código com ruff"
	@echo "  make requirements  - Gera requirements.txt para o Azure Functions"
	@echo "  make run           - Inicia a Azure Function localmente (func start)"
	@echo "  make tf-init       - Inicializa os módulos Terraform"
	@echo "  make tf-plan       - Executa terraform plan"
	@echo "  make tf-apply      - Executa terraform apply"
	@echo "  make clean         - Remove caches e arquivos temporários"

install:
	uv sync --all-extras

test:
	uv run pytest --verbose

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

requirements:
	uv export --format requirements-txt --no-dev --no-hashes --no-emit-project -o requirements.txt

run:
	func start

tf-init:
	terraform -chdir=terraform init

tf-plan:
	terraform -chdir=terraform plan

tf-apply:
	terraform -chdir=terraform apply

clean:
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} +
