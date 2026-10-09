"""Microsoft Foundry Invocations adapter for Jira webhook processing."""

import asyncio
import logging

from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.webhook_handler import process_jira_webhook

logger = logging.getLogger(__name__)
app = InvocationAgentServerHost()


@app.invoke_handler
async def handle_invocation(request: Request) -> JSONResponse:
    """Process a raw Jira webhook request through the Foundry Invocations protocol."""
    raw_body = await request.body()
    status_code, response_body = await asyncio.to_thread(
        process_jira_webhook,
        raw_body,
        request.headers,
    )
    logger.info("Foundry invocation completed with status %s", status_code)
    return JSONResponse(status_code=status_code, content=response_body)


if __name__ == "__main__":
    app.run()
