"""Logging utilities."""

import json
import logging
import os
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

SENSITIVE_HEADER_SUBSTRINGS = (
    "secret",
    "token",
    "authorization",
    "cookie",
    "signature",
    "password",
    "credential",
    "api-key",
    "api_key",
    "apikey",
)

_active_transaction_id: ContextVar[str | None] = ContextVar(
    "active_transaction_id",
    default=None,
)


@contextmanager
def transaction_log_context(transaction_id: str) -> Iterator[None]:
    """Attach a transaction ID to structured and regular logs in this context."""
    token = _active_transaction_id.set(transaction_id)
    try:
        yield
    finally:
        _active_transaction_id.reset(token)


class _TransactionIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.transaction_id = _active_transaction_id.get() or "-"
        return True


def setup_logger(name: str = "osb-jira-agent") -> logging.Logger:
    """Configura e retorna um logger formatado."""
    configured_level = os.getenv("LOG_LEVEL")
    if configured_level is None:
        from src.config import get_settings

        configured_level = get_settings().log_level
    log_level = configured_level.upper()
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] "
            "[transaction_id=%(transaction_id)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(formatter)
        handler.addFilter(_TransactionIdFilter())
        logger.addHandler(handler)

    logger.setLevel(getattr(logging, log_level, logging.INFO))
    return logger


def sanitize_webhook_headers(
    headers: Mapping[str, str] | None,
    extra_secret_headers: tuple[str, ...] = (),
) -> dict[str, str]:
    """Retorna cópia dos cabeçalhos HTTP mascarando segredos, tokens e assinaturas."""
    if not headers:
        return {}
    extra_lower = {h.lower() for h in extra_secret_headers if h}
    sanitized: dict[str, str] = {}
    for key, value in headers.items():
        key_lower = str(key).lower()
        if key_lower in extra_lower or any(sub in key_lower for sub in SENSITIVE_HEADER_SUBSTRINGS):
            sanitized[str(key)] = "***REDACTED***"
        else:
            sanitized[str(key)] = str(value)
    return sanitized


def format_structured_log(event_tag: str, **fields: Any) -> str:
    """Formata um evento estruturado em JSON compacto de linha única para stdout/App Insights."""
    transaction_id = _active_transaction_id.get()
    if transaction_id:
        fields.setdefault("transaction_id", transaction_id)
    payload = {"event_tag": event_tag, **fields}
    return f"[{event_tag}] {json.dumps(payload, ensure_ascii=False, default=str)}"


def _redact_debug_content(value: Any, key: str = "") -> Any:
    if key and any(part in key.lower() for part in SENSITIVE_HEADER_SUBSTRINGS):
        return "***REDACTED***"
    if isinstance(value, Mapping):
        return {
            str(item_key): _redact_debug_content(item, str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_debug_content(item) for item in value]
    return value


def log_debug_content(
    logger: logging.Logger,
    *,
    issue_key: str,
    stage: str,
    content: Any,
    enabled: bool,
    configured_issue_key: str,
    expires_at: datetime | None,
) -> bool:
    """Emite conteúdo sensível para a issue autorizada antes da expiração."""
    target_issue_key = configured_issue_key.strip()
    if (
        not enabled
        or not logger.isEnabledFor(logging.DEBUG)
        or not target_issue_key
        or (target_issue_key != "*" and issue_key.casefold() != target_issue_key.casefold())
        or expires_at is None
        or expires_at.tzinfo is None
        or expires_at.astimezone(UTC) <= datetime.now(UTC)
    ):
        return False

    logger.debug(
        format_structured_log(
            "AGENT_DEBUG_CONTENT",
            issue_key=issue_key,
            stage=stage,
            content=_redact_debug_content(content),
        )
    )
    return True
