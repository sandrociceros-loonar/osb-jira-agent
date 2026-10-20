"""Shared Jira webhook processing for Azure Functions and Foundry hosted agents."""

import json
import threading
import time
from collections.abc import Mapping

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import ValidationError

from src.agent.triage_agent import JiraTriageAgent
from src.config import get_settings
from src.models.jira_webhook import JiraWebhookPayload
from src.security.webhook_verifier import WebhookSecurityError, verify_jira_webhook
from src.utils.logger import (
    format_structured_log,
    sanitize_webhook_headers,
    setup_logger,
)

logger = setup_logger("jira-webhook-handler")
tracer = trace.get_tracer(__name__)

ACCEPTED_EVENTS = {
    "jira:issue_created",
    "jira:issue_updated",
    "issue_created",
    "issue_updated",
    "comment_created",
    "jira:issue_comment_created",
}


def _resolve_wait_timeout(
    headers: Mapping[str, str],
    wait_timeout_seconds: float | None,
) -> float | None:
    """Resolve effective wait timeout from HTTP headers or function argument."""
    lower_headers = {str(k).lower(): str(v).strip().lower() for k, v in headers.items()}
    if lower_headers.get("x-webhook-wait") in {"true", "1", "yes"}:
        return None
    if lower_headers.get("x-webhook-async") in {"true", "1", "yes"}:
        return 0.0
    return wait_timeout_seconds


def _execute_triage(
    payload: JiraWebhookPayload,
    source: str,
    start_time: float,
) -> tuple[int, dict[str, object]]:
    """Run JiraTriageAgent.process_ticket and emit structured WEBHOOK_RESULT log."""
    try:
        result = JiraTriageAgent().process_ticket(payload)
        status_code = 200 if result.success else 500
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        decision_category = (
            result.decision.category.value
            if getattr(result, "decision", None) and result.decision.category
            else None
        )
        decision_reasoning = (
            result.decision.reasoning
            if getattr(result, "decision", None) and result.decision.reasoning
            else None
        )
        logger.info(
            format_structured_log(
                "WEBHOOK_RESULT",
                source=source,
                status="processed" if result.success else "failed",
                status_code=status_code,
                webhook_event=payload.webhook_event,
                issue_key=payload.issue_key,
                success=result.success,
                category=decision_category,
                reasoning=decision_reasoning,
                actions_taken=getattr(result, "actions_taken", []),
                run_id=getattr(result, "run_id", None),
                error_message=getattr(result, "error_message", None),
                duration_ms=duration_ms,
            )
        )
        return status_code, result.model_dump(mode="json")
    except Exception as exc:
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
        logger.error(
            format_structured_log(
                "WEBHOOK_RESULT",
                source=source,
                status="exception",
                status_code=500,
                webhook_event=payload.webhook_event,
                issue_key=payload.issue_key,
                reason=str(exc),
                duration_ms=duration_ms,
            ),
            exc_info=True,
        )
        return 500, {
            "error": "Failed to process issue triage",
            "details": str(exc),
            "issue_key": payload.issue_key,
        }


def process_jira_webhook(
    raw_body: bytes,
    headers: Mapping[str, str],
    require_webhook_signature: bool = True,
    wait_timeout_seconds: float | None = None,
) -> tuple[int, dict[str, object]]:
    """Authenticate, validate, and process a Jira webhook payload."""
    start_time = time.monotonic()
    settings = get_settings()
    source = "azure_function" if require_webhook_signature else "foundry_hosted_agent"
    safe_headers = sanitize_webhook_headers(
        headers,
        extra_secret_headers=(settings.jira_webhook_secret_header,),
    )
    body_size = len(raw_body) if raw_body else 0
    effective_timeout = _resolve_wait_timeout(headers, wait_timeout_seconds)

    with tracer.start_as_current_span(
        "jira.process_webhook",
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        span.set_attribute("webhook.source", source)
        span.set_attribute("webhook.body_size_bytes", body_size)

        if require_webhook_signature:
            try:
                verify_jira_webhook(headers=headers, raw_body=raw_body)
            except WebhookSecurityError as exc:
                duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                span.set_attribute("http.response.status_code", 401)
                span.set_status(Status(StatusCode.ERROR))
                logger.warning(
                    format_structured_log(
                        "WEBHOOK_RESULT",
                        source=source,
                        status="unauthorized",
                        status_code=401,
                        body_size_bytes=body_size,
                        headers=safe_headers,
                        reason=str(exc),
                        duration_ms=duration_ms,
                    )
                )
                return 401, {"error": "Unauthorized", "details": str(exc)}
            except Exception as exc:
                duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                span.set_attribute("http.response.status_code", 500)
                span.set_status(Status(StatusCode.ERROR))
                logger.error(
                    format_structured_log(
                        "WEBHOOK_RESULT",
                        source=source,
                        status="verification_error",
                        status_code=500,
                        body_size_bytes=body_size,
                        headers=safe_headers,
                        reason=str(exc),
                        duration_ms=duration_ms,
                    )
                )
                return 500, {"error": "Internal server error during verification"}

        try:
            raw_json = json.loads(raw_body)
        except Exception as exc:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            span.set_attribute("http.response.status_code", 400)
            span.set_status(Status(StatusCode.ERROR))
            logger.error(
                format_structured_log(
                    "WEBHOOK_RESULT",
                    source=source,
                    status="invalid_json",
                    status_code=400,
                    body_size_bytes=body_size,
                    headers=safe_headers,
                    reason=str(exc),
                    duration_ms=duration_ms,
                )
            )
            return 400, {"error": "Invalid JSON body"}

        try:
            payload = JiraWebhookPayload.model_validate(raw_json)
        except ValidationError as exc:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            span.set_attribute("http.response.status_code", 400)
            span.set_status(Status(StatusCode.ERROR))
            logger.warning(
                format_structured_log(
                    "WEBHOOK_RESULT",
                    source=source,
                    status="invalid_payload",
                    status_code=400,
                    body_size_bytes=body_size,
                    headers=safe_headers,
                    validation_errors=exc.errors(),
                    duration_ms=duration_ms,
                )
            )
            return 400, {"error": "Invalid Jira webhook payload", "details": exc.errors()}

        issue = payload.issue
        issue_type = issue.fields.issuetype.name if issue.fields.issuetype else None
        issue_status = issue.fields.status.name if issue.fields.status else None
        issue_priority = issue.fields.priority.name if issue.fields.priority else None
        reporter = issue.fields.reporter.display_name if issue.fields.reporter else None
        comment_author = (
            payload.comment.author.display_name
            if payload.comment and payload.comment.author
            else None
        )
        comment_text = payload.comment.get_body_text() if payload.comment else None
        comment_preview = (
            (comment_text[:200] + "...")
            if comment_text and len(comment_text) > 200
            else comment_text
        )

        span.set_attribute("webhook.event", payload.webhook_event or "unspecified")
        span.set_attribute("jira.issue.key", payload.issue_key)
        if issue_type:
            span.set_attribute("jira.issue.type", issue_type)
        if issue_status:
            span.set_attribute("jira.issue.status", issue_status)

        logger.info(
            format_structured_log(
                "WEBHOOK_RECEIVED",
                source=source,
                webhook_event=payload.webhook_event,
                issue_key=payload.issue_key,
                issue_id=issue.id,
                issue_type=issue_type,
                status=issue_status,
                priority=issue_priority,
                summary=issue.fields.summary,
                reporter=reporter,
                has_comment=payload.comment is not None,
                comment_author=comment_author,
                comment_preview=comment_preview,
                body_size_bytes=body_size,
                headers=safe_headers,
            )
        )
        logger.debug(
            format_structured_log(
                "WEBHOOK_RAW_PAYLOAD",
                source=source,
                issue_key=payload.issue_key,
                payload=raw_json,
            )
        )

        if payload.webhook_event is not None and payload.webhook_event not in ACCEPTED_EVENTS:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            span.set_attribute("http.response.status_code", 200)
            logger.info(
                format_structured_log(
                    "WEBHOOK_RESULT",
                    source=source,
                    status="ignored",
                    status_code=200,
                    webhook_event=payload.webhook_event,
                    issue_key=payload.issue_key,
                    reason=f"Event '{payload.webhook_event}' not configured for automatic triage",
                    duration_ms=duration_ms,
                )
            )
            return 200, {
                "status": "ignored",
                "message": (f"Event '{payload.webhook_event}' not configured for automatic triage"),
            }

        if effective_timeout is None:
            status_code, response_body = _execute_triage(payload, source, start_time)
            span.set_attribute("http.response.status_code", status_code)
            if status_code >= 400:
                span.set_status(Status(StatusCode.ERROR))
            return status_code, response_body

        outcome: list[tuple[int, dict[str, object]]] = []
        done_event = threading.Event()

        def _worker() -> None:
            try:
                outcome.append(_execute_triage(payload, source, start_time))
            finally:
                done_event.set()

        worker_thread = threading.Thread(
            target=_worker,
            name=f"jira-triage-{payload.issue_key}",
            daemon=False,
        )
        worker_thread.start()

        if effective_timeout > 0:
            done_event.wait(timeout=effective_timeout)

        if done_event.is_set() and outcome:
            status_code, response_body = outcome[0]
            span.set_attribute("http.response.status_code", status_code)
            if status_code >= 400:
                span.set_status(Status(StatusCode.ERROR))
            return status_code, response_body

        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
        span.set_attribute("http.response.status_code", 200)
        span.set_attribute("webhook.async_dispatched", True)
        logger.info(
            format_structured_log(
                "WEBHOOK_ACCEPTED_ASYNC",
                source=source,
                status="processing",
                status_code=200,
                webhook_event=payload.webhook_event,
                issue_key=payload.issue_key,
                wait_timeout_seconds=effective_timeout,
                duration_ms=duration_ms,
            )
        )
        return 200, {
            "issue_key": payload.issue_key,
            "success": True,
            "status": "processing",
            "message": "Webhook aceito; processamento comercial em andamento em background.",
        }
