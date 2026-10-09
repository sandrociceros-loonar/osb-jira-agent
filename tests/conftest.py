"""Pytest fixtures for OSB Jira Agent tests."""

import pytest

from src.config import Settings


@pytest.fixture
def test_settings(monkeypatch):
    """Configurações mockadas para testes."""
    monkeypatch.setenv("AZURE_AI_PROJECT_CONNECTION_STRING", "mock.api.azureml.ms;000;rg;proj")
    monkeypatch.setenv("JIRA_WEBHOOK_SECRET", "test-secret-12345")
    monkeypatch.setenv("JIRA_WEBHOOK_SECRET_HEADER", "X-Atlassian-Webhook-Secret")
    monkeypatch.setenv("ENVIRONMENT", "test")
    return Settings(
        AZURE_AI_PROJECT_CONNECTION_STRING="mock.api.azureml.ms;000;rg;proj",
        JIRA_WEBHOOK_SECRET="test-secret-12345",
        JIRA_WEBHOOK_SECRET_HEADER="X-Atlassian-Webhook-Secret",
        ENVIRONMENT="test",
    )


@pytest.fixture
def sample_outage_webhook_payload() -> dict:
    """Payload de exemplo para incidente crítico de infraestrutura (Outage)."""
    return {
        "webhookEvent": "jira:issue_created",
        "timestamp": 1717200000000,
        "issue": {
            "id": "10001",
            "key": "ITSM-101",
            "fields": {
                "summary": "Servidor de Produção do Checkout fora do ar (Erro 502)",
                "description": "Todos os clientes estão recebendo Bad Gateway ao finalizar compra no portal de checkout.",
                "priority": {"id": "1", "name": "Highest"},
                "status": {"id": "1", "name": "Open"},
                "issuetype": {"id": "1", "name": "Incident"},
                "labels": ["production", "checkout"],
                "reporter": {
                    "accountId": "user-123",
                    "displayName": "Maria Silva",
                    "emailAddress": "maria.silva@empresa.com",
                },
            },
        },
    }


@pytest.fixture
def sample_access_request_webhook_payload() -> dict:
    """Payload de exemplo para solicitação de acesso."""
    return {
        "webhookEvent": "jira:issue_created",
        "timestamp": 1717200000000,
        "issue": {
            "id": "10002",
            "key": "ITSM-102",
            "fields": {
                "summary": "Solicitação de acesso à VPN corporativa e AWS Staging",
                "description": "Novo desenvolvedor contratado precisa de liberação no grupo VPN-Devs e perfil Developer na AWS.",
                "priority": {"id": "3", "name": "Medium"},
                "status": {"id": "1", "name": "Open"},
                "issuetype": {"id": "2", "name": "Service Request"},
                "labels": ["onboarding", "vpn"],
                "reporter": {
                    "accountId": "user-456",
                    "displayName": "João Santos",
                    "emailAddress": "joao.santos@empresa.com",
                },
            },
        },
    }
