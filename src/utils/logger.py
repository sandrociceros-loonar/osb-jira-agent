"""Logging utilities."""

import json
import logging
import os
import sys
from collections.abc import Mapping
from typing import Any

SENSITIVE_HEADER_SUBSTRINGS = (
    "secret",
    "token",
    "authorization",
    "cookie",
    "signature",
    "api-key",
    "apikey",
)


def setup_logger(name: str = "osb-jira-agent") -> logging.Logger:
    """Configura e retorna um logger formatado."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(formatter)
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
    payload = {"event_tag": event_tag, **fields}
    return f"[{event_tag}] {json.dumps(payload, ensure_ascii=False, default=str)}"
