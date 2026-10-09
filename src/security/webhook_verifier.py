"""Webhook security verification module."""

import hashlib
import hmac
from collections.abc import Mapping

from src.config import get_settings
from src.utils.logger import setup_logger

logger = setup_logger("webhook-security")


class WebhookSecurityError(Exception):
    """Exceção levantada quando a validação do webhook falha."""

    pass


def verify_jira_webhook(
    headers: Mapping[str, str],
    raw_body: bytes,
    secret: str | None = None,
) -> bool:
    """Verifica a autenticidade da requisição de webhook do Jira.

    Suporta:
    1. Validação de token compartilhado via header (ex: X-Atlassian-Webhook-Secret).
    2. Validação de assinatura HMAC-SHA256 (ex: X-Hub-Signature ou sha256=...).

    Usa hmac.compare_digest para prevenir timing attacks.
    """
    settings = get_settings()
    configured_secret = secret or settings.jira_webhook_secret

    # Se não houver segredo configurado no ambiente e estivermos em dev, alerta mas permite
    if not configured_secret:
        if settings.environment.lower() in ("development", "dev", "local"):
            logger.warning(
                "JIRA_WEBHOOK_SECRET não configurado. Ignorando validação em ambiente de desenvolvimento."
            )
            return True
        logger.error("JIRA_WEBHOOK_SECRET não configurado em ambiente de produção.")
        raise WebhookSecurityError("Webhook secret is not configured on the server.")

    # Normalizar headers para busca case-insensitive
    normalized_headers = {k.lower(): v for k, v in headers.items()}
    secret_header_name = settings.jira_webhook_secret_header.lower()

    # 1. Checagem por Header de Segredo Compartilhado direto
    if secret_header_name in normalized_headers:
        provided_secret = normalized_headers[secret_header_name]
        if hmac.compare_digest(provided_secret.strip(), configured_secret.strip()):
            return True

    # 2. Checagem por Assinatura HMAC-SHA256 (X-Hub-Signature ou X-Signature)
    signature_headers = ["x-hub-signature-256", "x-hub-signature", "x-signature"]
    for sig_header in signature_headers:
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

    logger.warning(
        "Falha na validação de segurança do webhook do Jira: cabeçalho ou assinatura inválida."
    )
    raise WebhookSecurityError("Invalid webhook signature or secret header.")
