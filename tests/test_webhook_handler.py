"""Tests for shared Jira webhook processing."""

import json
from unittest.mock import MagicMock, patch

from src.security.webhook_verifier import WebhookSecurityError
from src.webhook_handler import process_jira_webhook


def test_untrusted_webhook_requires_signature_by_default():
    """Keep Jira webhook authentication enabled for callers using the default."""
    with patch(
        "src.webhook_handler.verify_jira_webhook",
        side_effect=WebhookSecurityError("invalid signature"),
    ) as verify_webhook:
        status_code, response_body = process_jira_webhook(b"not-json", {})

    assert status_code == 401
    assert response_body["error"] == "Unauthorized"
    verify_webhook.assert_called_once()


def test_trusted_foundry_invocation_skips_jira_signature():
    """Allow Foundry-authenticated requests while still validating their payload."""
    with patch("src.webhook_handler.verify_jira_webhook") as verify_webhook:
        status_code, response_body = process_jira_webhook(
            b"not-json",
            {},
            require_webhook_signature=False,
        )

    assert status_code == 400
    assert response_body["error"] == "Invalid JSON body"
    verify_webhook.assert_not_called()


def test_comment_created_event_is_accepted_for_lead_follow_up():
    payload = {
        "webhookEvent": "comment_created",
        "issue": {
            "id": "10001",
            "key": "OP-101",
            "fields": {
                "summary": "Avaliar lead",
                "issuetype": {"id": "12716", "name": "Lead"},
            },
        },
        "comment": {
            "id": "comment-20",
            "body": "Prazo de pagamento: 30 dias.",
            "author": {"accountId": "customer-1", "displayName": "Solicitante"},
        },
    }

    with (
        patch("src.webhook_handler.verify_jira_webhook"),
        patch("src.webhook_handler.JiraTriageAgent") as agent_class,
    ):
        agent_class.return_value.process_ticket.return_value = MagicMock(
            success=True,
            model_dump=lambda mode: {"success": True},
        )
        status_code, response_body = process_jira_webhook(
            json.dumps(payload).encode(),
            {},
            require_webhook_signature=False,
        )

    assert status_code == 200
    assert response_body == {"success": True}
    agent_class.return_value.process_ticket.assert_called_once()
