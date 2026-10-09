#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Uso: ./scripts/dev.sh [test|lint|format|requirements|sync]"
  exit 1
}

CMD=${1:-"help"}

case "$CMD" in
  test)
    uv run pytest --verbose
    ;;
  lint)
    uv run ruff check .
    uv run ruff format --check .
    ;;
  format)
    uv run ruff format .
    uv run ruff check --fix .
    ;;
  requirements)
    uv export --format requirements-txt --no-dev --no-hashes --no-emit-project -o requirements.txt
    ;;
  sync|install)
    uv sync --all-extras
    ;;
  *)
    usage
    ;;
esac
