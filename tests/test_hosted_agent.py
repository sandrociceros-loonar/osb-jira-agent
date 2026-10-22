"""Tests for the Microsoft Foundry hosted-agent adapter."""

import asyncio
import json
import logging
import time
from unittest.mock import patch

from starlette.requests import Request
from starlette.responses import StreamingResponse

from src.config import Settings
from src.hosted_agent.main import app, handle_invocation


def test_foundry_project_endpoint_alias():
    """Accept the project endpoint name injected by the hosted-agent runtime."""
    settings = Settings(FOUNDRY_PROJECT_ENDPOINT="https://example.services.ai.azure.com/project")

    assert settings.azure_ai_project_endpoint == "https://example.services.ai.azure.com/project"


def test_invocation_streams_shared_webhook_result(caplog):
    """Keep long-running Foundry invocations alive and return the shared handler result."""
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
            "headers": [],
        },
        receive,
    )

    def process_webhook(*args, **kwargs):
        time.sleep(0.05)
        return 202, {"status": "accepted"}

    with (
        caplog.at_level(logging.INFO, logger="hosted-agent"),
        patch(
            "src.hosted_agent.main.process_jira_webhook",
            side_effect=process_webhook,
        ) as process_webhook,
        patch("src.hosted_agent.main.configure_jira_runtime_secrets") as configure_secrets,
    ):
        response = asyncio.run(handle_invocation(request))

        previous_interval = app.config.sse_keepalive_interval
        app.config.sse_keepalive_interval = 0.01

        async def read_response():
            chunks = [chunk async for chunk in response.body_iterator]
            return b"".join(chunk.encode() if isinstance(chunk, str) else chunk for chunk in chunks)

        try:
            response = app._wrap_streaming_response(response, "invocation-test", "session-test")
            response_body = asyncio.run(read_response())
        finally:
            app.config.sse_keepalive_interval = previous_interval

    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"
    assert b": keep-alive\n\n" in response_body
    assert json.loads(response_body.splitlines()[-1]) == {"status": "accepted"}
    configure_secrets.assert_called_once()
    process_webhook.assert_called_once()
    forwarded_body, forwarded_headers = process_webhook.call_args.args
    assert forwarded_body == raw_body
    assert not forwarded_headers
    assert process_webhook.call_args.kwargs["require_webhook_signature"] is False
    transaction_id = process_webhook.call_args.kwargs["transaction_id"]
    assert transaction_id
    assert f'"transaction_id": "{transaction_id}"' in caplog.text
