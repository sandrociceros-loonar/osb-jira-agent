"""Tests for Azure Functions KB endpoints: /api/confluence-webhook and /api/kb-refresh."""

import json
from unittest.mock import MagicMock, patch

import azure.functions as func

from src.function_app import confluence_webhook_trigger, kb_refresh_trigger


def test_confluence_webhook_trigger():
    req = func.HttpRequest(
        method="POST",
        body=json.dumps({"event": "page_updated", "space": {"key": "osbjiraage"}}).encode("utf-8"),
        url="/api/confluence-webhook",
        headers={},
    )

    with patch("src.function_app.get_rag_engine") as mock_get_rag:
        mock_rag = MagicMock()
        mock_rag.space_key = "osbjiraage"
        mock_rag.sync_cache.return_value = {"success": True, "pages_count": 3}
        mock_get_rag.return_value = mock_rag

        resp = confluence_webhook_trigger(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["status"] == "cache_updated"


def test_kb_refresh_trigger():
    req = func.HttpRequest(
        method="POST",
        body=b"",
        url="/api/kb-refresh",
        headers={},
    )

    with patch("src.function_app.get_rag_engine") as mock_get_rag:
        mock_rag = MagicMock()
        mock_rag.sync_cache.return_value = {"success": True, "pages_count": 4, "chunks_count": 16}
        mock_get_rag.return_value = mock_rag

        resp = kb_refresh_trigger(req)
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["success"] is True
        assert data["pages_count"] == 4
        mock_rag.sync_cache.assert_called_once_with(force=True)
