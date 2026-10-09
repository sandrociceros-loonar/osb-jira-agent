"""Tests for Azure Functions entrypoint and HTTP trigger."""

import json
from unittest.mock import patch

import azure.functions as func

from src.agent.triage_agent import JiraTriageAgent
from src.function_app import health_check, jira_webhook_trigger
from src.models.agent_result import (
    AgentExecutionResult,
    TriageCategory,
    TriageDecision,
    TriagePriority,
)


def test_health_check_endpoint():
    """Testa se o endpoint /api/health responde 200 OK."""
    req = func.HttpRequest(
        method="GET",
        body=b"",
        url="/api/health",
        headers={},
    )
    resp = health_check(req)
    assert resp.status_code == 200
    data = json.loads(resp.get_body())
    assert data["status"] == "healthy"


def test_jira_webhook_unauthorized(monkeypatch):
    """Testa rejeição com 401 quando o segredo não confere."""
    monkeypatch.setenv("JIRA_WEBHOOK_SECRET", "expected-secret")
    monkeypatch.setenv("ENVIRONMENT", "production")

    req = func.HttpRequest(
        method="POST",
        body=b'{"webhookEvent": "jira:issue_created"}',
        url="/api/jira-webhook",
        headers={"X-Atlassian-Webhook-Secret": "wrong-secret"},
    )

    resp = jira_webhook_trigger(req)
    assert resp.status_code == 401
    data = json.loads(resp.get_body())
    assert data["error"] == "Unauthorized"


def test_jira_webhook_invalid_json():
    """Testa retorno 400 para corpo mal formatado."""
    req = func.HttpRequest(
        method="POST",
        body=b"{not valid json}",
        url="/api/jira-webhook",
        headers={"X-Atlassian-Webhook-Secret": "test-secret-12345"},
    )
    with patch("src.function_app.verify_jira_webhook", return_value=True):
        resp = jira_webhook_trigger(req)
    assert resp.status_code == 400


def test_jira_webhook_ignored_event():
    """Testa retorno 200 com status ignored para eventos fora do escopo."""
    payload = {
        "webhookEvent": "jira:issue_deleted",
        "issue": {
            "id": "1",
            "key": "ITSM-1",
            "fields": {"summary": "Exclusão"},
        },
    }
    req = func.HttpRequest(
        method="POST",
        body=json.dumps(payload).encode("utf-8"),
        url="/api/jira-webhook",
        headers={"X-Atlassian-Webhook-Secret": "test-secret-12345"},
    )
    with patch("src.function_app.verify_jira_webhook", return_value=True):
        resp = jira_webhook_trigger(req)

    assert resp.status_code == 200
    data = json.loads(resp.get_body())
    assert data["status"] == "ignored"


def test_jira_webhook_successful_triage(sample_outage_webhook_payload):
    """Testa processamento com sucesso de um webhook de criação de issue."""
    req = func.HttpRequest(
        method="POST",
        body=json.dumps(sample_outage_webhook_payload).encode("utf-8"),
        url="/api/jira-webhook",
        headers={"X-Atlassian-Webhook-Secret": "test-secret-12345"},
    )

    mock_result = AgentExecutionResult(
        issue_key="ITSM-101",
        success=True,
        decision=TriageDecision(
            category=TriageCategory.INFRASTRUCTURE,
            priority=TriagePriority.HIGHEST,
            assigned_team="Cloud-Platform",
            suggested_status="In Progress",
            should_auto_close=False,
            reasoning="Produção fora do ar",
            internal_comment="Incidente crítico encaminhado.",
        ),
        actions_taken=["Atribuído à Cloud-Platform"],
    )

    with patch("src.function_app.verify_jira_webhook", return_value=True):
        with patch.object(JiraTriageAgent, "process_ticket", return_value=mock_result):
            resp = jira_webhook_trigger(req)

    assert resp.status_code == 200
    data = json.loads(resp.get_body())
    assert data["success"] is True
    assert data["issue_key"] == "ITSM-101"
    assert data["decision"]["category"] == "Infrastructure & Cloud"
    assert data["decision"]["priority"] == "Highest"
