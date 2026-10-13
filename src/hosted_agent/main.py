"""Microsoft Foundry Invocations adapter for Jira webhook processing."""

import asyncio
import json
import logging

from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.requests import Request
from starlette.responses import StreamingResponse

from src.security.key_vault_secrets import configure_jira_runtime_secrets
from src.webhook_handler import process_jira_webhook

logger = logging.getLogger(__name__)
app = InvocationAgentServerHost()
app.config.sse_keepalive_interval = 15


@app.invoke_handler
async def handle_invocation(request: Request) -> StreamingResponse:
    """Stream a Jira webhook result, keeping long Foundry invocations alive."""
    raw_body = await request.body()

    async def stream_result():
        await asyncio.to_thread(configure_jira_runtime_secrets)
        # Foundry authenticates callers with Microsoft Entra before forwarding invocations.
        status_code, response_body = await asyncio.to_thread(
            process_jira_webhook,
            raw_body,
            request.headers,
            require_webhook_signature=False,
        )
        logger.info("Foundry invocation completed with status %s", status_code)
        yield (json.dumps(response_body, ensure_ascii=False) + "\n").encode("utf-8")

    return StreamingResponse(stream_result(), media_type="text/event-stream")


if __name__ == "__main__":
    app.run()
