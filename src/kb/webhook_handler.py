"""Webhook processing for Confluence Knowledge Base cache updates."""

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

from src.config import Settings, get_settings
from src.kb.rag_engine import RAGEngine
from src.utils.logger import setup_logger

logger = setup_logger("confluence-webhook")


class ConfluenceWebhookSecurityError(Exception):
    """Exceção levantada quando a validação do webhook do Confluence falha."""


def verify_confluence_webhook(
    headers: Mapping[str, str],
    raw_body: bytes,
    secret: str | None = None,
    secret_header_name: str | None = None,
    environment: str | None = None,
) -> bool:
    """Valida a autenticidade da requisição de webhook do Confluence."""
    settings = get_settings()
    configured_secret = secret if secret is not None else settings.confluence_webhook_secret
    header_name = (secret_header_name or settings.confluence_webhook_secret_header).lower()
    env = environment or settings.environment

    if not configured_secret:
        if env.lower() in ("development", "dev", "local"):
            logger.warning(
                "CONFLUENCE_WEBHOOK_SECRET não configurado. Ignorando validação em ambiente dev."
            )
            return True
        logger.error("CONFLUENCE_WEBHOOK_SECRET não configurado em produção.")
        raise ConfluenceWebhookSecurityError("Confluence webhook secret is not configured.")

    normalized_headers = {k.lower(): v for k, v in headers.items()}

    # 1. Checagem direta por header de segredo compartilhado
    if header_name in normalized_headers:
        provided_secret = normalized_headers[header_name]
        if hmac.compare_digest(provided_secret.strip(), configured_secret.strip()):
            return True

    # 2. Checagem por assinatura HMAC-SHA256
    for sig_header in ("x-hub-signature-256", "x-signature", "x-atlassian-signature"):
        if sig_header in normalized_headers:
            sig_value = normalized_headers[sig_header]
            prefix = "sha256="
            if sig_value.startswith(prefix):
                sig_value = sig_value[len(prefix) :]

            expected_sig = hmac.new(
                configured_secret.encode("utf-8"),
                raw_body,
                hashlib.sha256,
            ).hexdigest()

            if hmac.compare_digest(sig_value.strip(), expected_sig):
                return True

    raise ConfluenceWebhookSecurityError("Assinatura ou cabeçalho inválido no webhook Confluence.")


def process_confluence_webhook(
    raw_body: bytes,
    headers: Mapping[str, str],
    rag_engine: RAGEngine,
    require_signature: bool = True,
    settings: Settings | None = None,
) -> tuple[int, dict[str, Any]]:
    """Processa eventos de webhook do Confluence para atualização do cache RAG."""
    app_settings = settings or get_settings()

    if require_signature:
        try:
            verify_confluence_webhook(
                headers=headers,
                raw_body=raw_body,
                secret=app_settings.confluence_webhook_secret,
                secret_header_name=app_settings.confluence_webhook_secret_header,
                environment=app_settings.environment,
            )
        except ConfluenceWebhookSecurityError as exc:
            logger.warning("Falha de autenticação no webhook Confluence: %s", exc)
            return 401, {"error": "Unauthorized", "details": str(exc)}
        except Exception as exc:
            logger.error("Erro inesperado na autenticação Confluence: %s", exc)
            return 500, {"error": "Internal server error during verification"}

    try:
        data = json.loads(raw_body) if raw_body else {}
    except Exception as exc:
        logger.error("JSON inválido no corpo do webhook Confluence: %s", exc)
        return 400, {"error": "Invalid JSON body"}

    # Extrair evento e espaço
    event = data.get("event") or data.get("webhookEvent") or data.get("action")
    space_data = data.get("space") or data.get("page", {}).get("space", {})
    space_key = (
        space_data.get("key")
        if isinstance(space_data, dict)
        else data.get("space_key") or data.get("spaceKey")
    )

    logger.info("Webhook Confluence recebido. Evento: %s, Espaço: %s", event, space_key)

    # Se um espaço foi indicado e não for o configurado, podemos ignorar
    if space_key and space_key.strip().lower() != rag_engine.space_key.lower():
        return 200, {
            "status": "ignored",
            "message": f"Evento para espaço '{space_key}' ignorado (espaço alvo: '{rag_engine.space_key}').",
        }

    # Executar atualização do cache
    try:
        sync_result = rag_engine.sync_cache()
        status_code = 200 if sync_result.get("success") else 500
        return status_code, {
            "status": "cache_updated" if sync_result.get("success") else "cache_update_failed",
            "event": event,
            "details": sync_result,
        }
    except Exception as exc:
        logger.error("Erro ao sincronizar cache via webhook: %s", exc, exc_info=True)
        return 500, {"error": "Failed to sync cache", "details": str(exc)}
