"""Azure Functions Python v2 entrypoint for Jira Service Management Webhooks."""

import json

import azure.functions as func
from pydantic import ValidationError

from src.agent.triage_agent import JiraTriageAgent
from src.models.jira_webhook import JiraWebhookPayload
from src.security.webhook_verifier import WebhookSecurityError, verify_jira_webhook
from src.utils.logger import setup_logger

logger = setup_logger("function-app")

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """Endpoint de checagem de integridade do serviço."""
    return func.HttpResponse(
        body=json.dumps({"status": "healthy", "service": "osb-jira-agent"}),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="jira-webhook", methods=["POST"])
def jira_webhook_trigger(req: func.HttpRequest) -> func.HttpResponse:
    """Recebe e processa eventos de webhook disparados pelo Jira Service Management."""
    logger.info("Recebida requisição no endpoint /api/jira-webhook")

    # 1. Validação de Segurança do Webhook
    try:
        raw_body = req.get_body()
        verify_jira_webhook(headers=req.headers, raw_body=raw_body)
    except WebhookSecurityError as sec_err:
        logger.warning("Falha de autenticação do webhook: %s", sec_err)
        return func.HttpResponse(
            body=json.dumps({"error": "Unauthorized", "details": str(sec_err)}),
            status_code=401,
            mimetype="application/json",
        )
    except Exception as exc:
        logger.error("Erro inesperado durante validação de segurança: %s", exc)
        return func.HttpResponse(
            body=json.dumps({"error": "Internal server error during verification"}),
            status_code=500,
            mimetype="application/json",
        )

    # 2. Parse e Validação do Payload
    try:
        json_data = req.get_json()
        payload = JiraWebhookPayload.model_validate(json_data)
        logger.info(
            "Webhook parseado com sucesso. Evento: %s, Issue: %s",
            payload.webhook_event,
            payload.issue_key,
        )
    except ValidationError as val_err:
        logger.warning("Payload do Jira inválido: %s", val_err)
        return func.HttpResponse(
            body=json.dumps({"error": "Invalid Jira webhook payload", "details": val_err.errors()}),
            status_code=400,
            mimetype="application/json",
        )
    except Exception as exc:
        logger.error("Falha ao ler JSON do corpo da requisição: %s", exc)
        return func.HttpResponse(
            body=json.dumps({"error": "Invalid JSON body"}),
            status_code=400,
            mimetype="application/json",
        )

    # 3. Filtrar eventos relevantes (apenas criação ou atualização de chamados)
    accepted_events = [
        "jira:issue_created",
        "jira:issue_updated",
        "issue_created",
        "issue_updated",
    ]
    if payload.webhook_event not in accepted_events:
        logger.info("Evento ignorado (fora do escopo): %s", payload.webhook_event)
        return func.HttpResponse(
            body=json.dumps(
                {
                    "status": "ignored",
                    "message": f"Event '{payload.webhook_event}' not configured for automatic triage",
                }
            ),
            status_code=200,
            mimetype="application/json",
        )

    # 4. Execução do Agente no Azure AI Foundry
    try:
        agent_orchestrator = JiraTriageAgent()
        result = agent_orchestrator.process_ticket(payload)

        status_code = 200 if result.success else 500
        return func.HttpResponse(
            body=json.dumps(result.model_dump(), indent=2),
            status_code=status_code,
            mimetype="application/json",
        )
    except Exception as exc:
        logger.error("Erro catastrófico ao executar triagem com o agente: %s", exc, exc_info=True)
        return func.HttpResponse(
            body=json.dumps(
                {
                    "error": "Failed to process issue triage",
                    "details": str(exc),
                    "issue_key": payload.issue_key,
                }
            ),
            status_code=500,
            mimetype="application/json",
        )
