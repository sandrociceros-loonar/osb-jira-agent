"""Azure Functions Python v2 entrypoint for Jira Service Management Webhooks."""

import json

import azure.functions as func

from src.kb import get_rag_engine
from src.kb.webhook_handler import process_confluence_webhook
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


@app.route(route="confluence-webhook", methods=["POST"])
def confluence_webhook_trigger(req: func.HttpRequest) -> func.HttpResponse:
    """Recebe e processa eventos de webhook disparados pelo Confluence para atualização do cache RAG."""
    logger.info("Recebida requisição no endpoint /api/confluence-webhook")
    rag_engine = get_rag_engine()
    status_code, response_body = process_confluence_webhook(
        raw_body=req.get_body(),
        headers=req.headers,
        rag_engine=rag_engine,
    )
    return func.HttpResponse(
        body=json.dumps(response_body, indent=2),
        status_code=status_code,
        mimetype="application/json",
    )


@app.route(route="kb-refresh", methods=["POST", "GET"])
def kb_refresh_trigger(req: func.HttpRequest) -> func.HttpResponse:
    """Dispara a sincronização e atualização manual do cache da base de conhecimento."""
    logger.info("Recebida requisição no endpoint /api/kb-refresh")
    rag_engine = get_rag_engine()
    sync_result = rag_engine.sync_cache(force=True)
    status_code = 200 if sync_result.get("success") else 500
    return func.HttpResponse(
        body=json.dumps(sync_result, indent=2),
        status_code=status_code,
        mimetype="application/json",
    )
