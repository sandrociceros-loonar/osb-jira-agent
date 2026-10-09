#!/usr/bin/env python3
"""Verify a local Ollama model and its OpenAI-compatible tool-calling endpoint."""

import argparse
import os
import sys
from urllib.parse import urlparse

from openai import OpenAI

DEFAULT_MODEL = "qwen3:4b"
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
PROBE_TOOL = "ollama_local_setup_probe"


def verify_model(model: str, base_url: str) -> None:
    endpoint = base_url.rstrip("/")
    parsed_endpoint = urlparse(endpoint)
    if parsed_endpoint.scheme not in ("http", "https") or not parsed_endpoint.netloc:
        raise ValueError("OLLAMA_BASE_URL deve ser uma URL HTTP(S) válida.")

    client = OpenAI(base_url=endpoint, api_key="ollama", timeout=300.0)
    print(f"Testando function calling com o modelo Ollama '{model}'", flush=True)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": (
                    f"You must call the tool `{PROBE_TOOL}` now. Do not answer in text."
                ),
            }
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": PROBE_TOOL,
                    "description": "Verify tool calling.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": PROBE_TOOL}},
        extra_body={"think": False},
        temperature=0,
        max_tokens=1024,
    )
    choice = response.choices[0]
    if not choice.message.tool_calls:
        raise RuntimeError(
            f"O modelo '{model}' não emitiu uma chamada de ferramenta estruturada "
            f"(finish_reason={choice.finish_reason}, resposta={choice.message.content!r})."
        )
    print(f"OK: Ollama respondeu com function calling em {endpoint}.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL_NAME", DEFAULT_MODEL),
        help="Nome do modelo instalado no Ollama.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL),
        help="Endpoint OpenAI-compatible do Ollama.",
    )
    args = parser.parse_args()

    try:
        verify_model(args.model, args.base_url)
    except Exception as exc:
        print(f"Falha na validação do Ollama: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
