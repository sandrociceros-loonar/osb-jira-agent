"""Tests for Confluence Webhook security verification and cache sync processing."""

import hashlib
import hmac
import json
from unittest.mock import MagicMock

import pytest

from src.kb.webhook_handler import (
    ConfluenceWebhookSecurityError,
    process_confluence_webhook,
    verify_confluence_webhook,
)


def test_verify_confluence_webhook_shared_secret():
    secret = "my-secret-key"
    headers = {"X-Atlassian-Webhook-Secret": secret}
    assert verify_confluence_webhook(headers=headers, raw_body=b"body", secret=secret) is True

    with pytest.raises(ConfluenceWebhookSecurityError):
        verify_confluence_webhook(
            headers={"X-Atlassian-Webhook-Secret": "wrong"},
            raw_body=b"body",
            secret=secret,
        )


def test_verify_confluence_webhook_hmac_signature():
    secret = "my-secret-key"
    raw_body = b'{"event": "page_updated"}'
    signature = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    headers = {"X-Hub-Signature-256": f"sha256={signature}"}
    assert verify_confluence_webhook(headers=headers, raw_body=raw_body, secret=secret) is True

    with pytest.raises(ConfluenceWebhookSecurityError):
        verify_confluence_webhook(
            headers={"X-Hub-Signature-256": "sha256=invalid"},
            raw_body=raw_body,
            secret=secret,
        )


def test_process_confluence_webhook_triggers_sync():
    mock_rag = MagicMock()
    mock_rag.space_key = "osbjiraage"
    mock_rag.sync_cache.return_value = {"success": True, "pages_count": 5, "chunks_count": 20}

    body = json.dumps(
        {
            "event": "page_updated",
            "space": {"key": "osbjiraage"},
            "page": {"id": "123", "title": "Atualização de Regras"},
        }
    ).encode("utf-8")

    status, response = process_confluence_webhook(
        raw_body=body,
        headers={},
        rag_engine=mock_rag,
        require_signature=False,
    )

    assert status == 200
    assert response["status"] == "cache_updated"
    mock_rag.sync_cache.assert_called_once()


def test_process_confluence_webhook_ignores_other_spaces():
    mock_rag = MagicMock()
    mock_rag.space_key = "osbjiraage"

    body = json.dumps(
        {
            "event": "page_updated",
            "space": {"key": "other_space"},
        }
    ).encode("utf-8")

    status, response = process_confluence_webhook(
        raw_body=body,
        headers={},
        rag_engine=mock_rag,
        require_signature=False,
    )

    assert status == 200
    assert response["status"] == "ignored"
    mock_rag.sync_cache.assert_not_called()
