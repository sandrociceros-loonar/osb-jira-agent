"""Azure Functions Python v2 entrypoint for Jira Service Management Webhooks."""

import json

import azure.functions as func

from src.utils.logger import setup_logger
from src.webhook_handler import process_jira_webhook

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
    status_code, response_body = process_jira_webhook(req.get_body(), req.headers)
    return func.HttpResponse(
        body=json.dumps(response_body, indent=2),
        status_code=status_code,
        mimetype="application/json",
    )
