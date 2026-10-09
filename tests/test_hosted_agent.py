"""Tests for the Microsoft Foundry hosted-agent adapter."""

import asyncio
from unittest.mock import patch

from starlette.requests import Request

from src.config import Settings
from src.hosted_agent.main import handle_invocation


def test_foundry_project_endpoint_alias():
    """Accept the project endpoint name injected by the hosted-agent runtime."""
    settings = Settings(FOUNDRY_PROJECT_ENDPOINT="https://example.services.ai.azure.com/project")

    assert settings.azure_ai_project_endpoint == "https://example.services.ai.azure.com/project"


def test_invocation_delegates_to_shared_webhook_handler():
    """Forward the raw payload and headers to the shared Jira webhook processor."""
    raw_body = b'{"webhookEvent":"jira:issue_created"}'
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": raw_body, "more_body": False}
        return {"type": "http.disconnect"}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/invocations",
            "headers": [(b"x-atlassian-webhook-secret", b"shared-secret")],
        },
        receive,
    )

    with patch(
        "src.hosted_agent.main.process_jira_webhook",
        return_value=(202, {"status": "accepted"}),
    ) as process_webhook:
        response = asyncio.run(handle_invocation(request))

    assert response.status_code == 202
    assert response.body == b'{"status":"accepted"}'
    process_webhook.assert_called_once()
    forwarded_body, forwarded_headers = process_webhook.call_args.args
    assert forwarded_body == raw_body
    assert forwarded_headers["x-atlassian-webhook-secret"] == "shared-secret"
