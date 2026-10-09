"""Shared Jira webhook processing for Azure Functions and Foundry hosted agents."""

import json
from collections.abc import Mapping

from pydantic import ValidationError

from src.agent.triage_agent import JiraTriageAgent
from src.models.jira_webhook import JiraWebhookPayload
from src.security.webhook_verifier import WebhookSecurityError, verify_jira_webhook
from src.utils.logger import setup_logger

logger = setup_logger("jira-webhook-handler")

ACCEPTED_EVENTS = {
    "jira:issue_created",
    "jira:issue_updated",
    "issue_created",
    "issue_updated",
}


def process_jira_webhook(
    raw_body: bytes,
    headers: Mapping[str, str],
) -> tuple[int, dict[str, object]]:
    """Authenticate, validate, and process a Jira webhook payload."""
    try:
        verify_jira_webhook(headers=headers, raw_body=raw_body)
    except WebhookSecurityError as exc:
        logger.warning("Falha de autenticação do webhook: %s", exc)
        return 401, {"error": "Unauthorized", "details": str(exc)}
    except Exception as exc:
        logger.error("Erro inesperado durante validação de segurança: %s", exc)
        return 500, {"error": "Internal server error during verification"}

    try:
        payload = JiraWebhookPayload.model_validate(json.loads(raw_body))
        logger.info(
            "Webhook parseado com sucesso. Evento: %s, Issue: %s",
            payload.webhook_event,
            payload.issue_key,
        )
    except ValidationError as exc:
        logger.warning("Payload do Jira inválido: %s", exc)
        return 400, {"error": "Invalid Jira webhook payload", "details": exc.errors()}
    except Exception as exc:
        logger.error("Falha ao ler JSON do corpo da requisição: %s", exc)
        return 400, {"error": "Invalid JSON body"}

    if payload.webhook_event not in ACCEPTED_EVENTS:
        logger.info("Evento ignorado (fora do escopo): %s", payload.webhook_event)
        return 200, {
            "status": "ignored",
            "message": (f"Event '{payload.webhook_event}' not configured for automatic triage"),
        }

    try:
        result = JiraTriageAgent().process_ticket(payload)
        return (200 if result.success else 500), result.model_dump(mode="json")
    except Exception as exc:
        logger.error(
            "Erro catastrófico ao executar triagem para %s: %s",
            payload.issue_key,
            exc,
            exc_info=True,
        )
        return 500, {
            "error": "Failed to process issue triage",
            "details": str(exc),
            "issue_key": payload.issue_key,
        }
