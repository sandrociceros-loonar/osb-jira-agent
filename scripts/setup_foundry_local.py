#!/usr/bin/env python3
"""Prepare and functionally verify a Foundry Local model for this application."""

import argparse
import os
import sys
import traceback

from foundry_local_sdk import Configuration, FoundryLocalManager
from openai import OpenAI

DEFAULT_MODEL_ALIAS = "phi-4-mini"
DEFAULT_BASE_URL = "http://127.0.0.1:5273/v1"


def prepare_model(alias: str, base_url: str, verify_only: bool) -> None:
    endpoint = base_url.rstrip("/")
    if not endpoint.startswith(("http://", "https://")):
        raise ValueError("FOUNDRY_LOCAL_BASE_URL deve começar com http:// ou https://.")
    service_url = endpoint.removesuffix("/v1")
    configuration = Configuration(
        app_name="osb-jira-agent",
        web=Configuration.WebService(urls=service_url),
    )
    FoundryLocalManager.initialize(configuration)
    manager = FoundryLocalManager.instance
    if manager is None:
        raise RuntimeError("O SDK não inicializou o Foundry Local.")

    try:
        model = manager.catalog.get_model(alias)
        if model is None:
            raise RuntimeError(f"Modelo '{alias}' não foi encontrado no catálogo Foundry Local.")

        missing_eps = [ep.name for ep in manager.discover_eps() if not ep.is_registered]
        if missing_eps:
            if verify_only:
                raise RuntimeError(
                    "Execution providers necessários ainda não foram registrados: "
                    + ", ".join(missing_eps)
                )
            print("Baixando execution providers: " + ", ".join(missing_eps), flush=True)
            result = manager.download_and_register_eps(missing_eps)
            if not result.success:
                raise RuntimeError(
                    "Falha ao registrar execution providers: " + ", ".join(result.failed_eps)
                )

        if not model.is_cached:
            if verify_only:
                raise RuntimeError(
                    f"Modelo '{alias}' não está em cache. Execute novamente sem --verify-only."
                )
            print(f"Baixando modelo Foundry Local: {alias}", flush=True)
            model.download()
        if not model.is_loaded:
            print(f"Carregando modelo Foundry Local: {alias}", flush=True)
            model.load()
        if not model.is_loaded:
            raise RuntimeError(f"O Foundry Local não carregou o modelo '{alias}'.")

        if manager.urls is None:
            print("Iniciando servidor local Foundry Local", flush=True)
            manager.start_web_service()
        if not manager.urls:
            raise RuntimeError("O serviço web Foundry Local não publicou um endpoint.")

        print("Testando function calling com o modelo local", flush=True)
        client = OpenAI(base_url=endpoint, api_key="foundry-local")
        response = client.chat.completions.create(
            model=alias,
            messages=[{"role": "user", "content": "Call the requested test function."}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "foundry_local_setup_probe",
                        "description": "Local setup smoke test.",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            tool_choice={
                "type": "function",
                "function": {"name": "foundry_local_setup_probe"},
            },
            max_tokens=32,
        )
        if not response.choices[0].message.tool_calls:
            raise RuntimeError(
                f"O modelo '{alias}' respondeu, mas não passou no teste de function calling."
            )
        print(
            f"OK: modelo '{alias}' carregado, servidor ativo e function calling verificado "
            f"em {base_url}.",
            flush=True,
        )
    finally:
        manager.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.environ.get("FOUNDRY_LOCAL_MODEL_ALIAS", DEFAULT_MODEL_ALIAS),
        help="Alias do modelo Foundry Local.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("FOUNDRY_LOCAL_BASE_URL", DEFAULT_BASE_URL),
        help="Base URL OpenAI-compatible do Foundry Local.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verifica modelo em cache e runtime sem baixar componentes.",
    )
    args = parser.parse_args()

    try:
        prepare_model(args.model, args.base_url, args.verify_only)
    except Exception as exc:
        print(f"Falha na preparação do Foundry Local: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
