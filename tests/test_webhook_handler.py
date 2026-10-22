"""Tests for shared Jira webhook processing."""

import json
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from src.config import Settings
from src.security.webhook_verifier import WebhookSecurityError
from src.utils.logger import log_debug_content
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


def test_payload_without_event_and_with_numeric_ids_is_accepted():
    payload = {
        "timestamp": 1717200000000,
        "user": {"accountId": "customer-1"},
        "issue": {
            "id": 651497,
            "key": "OP-8517",
            "fields": {
                "summary": "Avaliar lead",
                "priority": {"id": 3, "name": "Medium"},
                "status": {"id": 10001, "name": "Open"},
                "issuetype": {"id": 12716, "name": "Lead"},
            },
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
    validated_payload = agent_class.return_value.process_ticket.call_args.args[0]
    assert validated_payload.webhook_event is None
    assert validated_payload.issue.id == "651497"
    assert validated_payload.issue.fields.priority.id == "3"
    assert validated_payload.issue.fields.status.id == "10001"
    assert validated_payload.issue.fields.issuetype.id == "12716"


def test_comment_webhook_accepts_numeric_comment_id_and_created_timestamp():
    payload = {
        "webhookEvent": "comment_created",
        "issue": {
            "id": 651497,
            "key": "OP-8517",
            "fields": {"summary": "Avaliar lead"},
        },
        "comment": {
            "id": 965554,
            "created": 1792448148683,
            "body": (
                "Comment by Sandro Cicero dos Santos (sandro.cicero@loonar.cloud):\n"
                "Confirmação do cliente."
            ),
            "author": {
                "displayName": "Sandro Cicero dos Santos",
                "emailAddress": "sandro.cicero@loonar.cloud",
            },
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
    validated_payload = agent_class.return_value.process_ticket.call_args.args[0]
    assert validated_payload.comment.id == "965554"
    assert validated_payload.comment.created == "1792448148683"
    assert validated_payload.comment.author.display_name == "Sandro Cicero dos Santos"
    assert validated_payload.comment.author.email_address == "sandro.cicero@loonar.cloud"


def test_explicitly_unsupported_event_remains_ignored():
    payload = {
        "webhookEvent": "jira:issue_deleted",
        "issue": {
            "id": "10001",
            "key": "OP-101",
            "fields": {"summary": "Avaliar lead"},
        },
    }

    with (
        patch("src.webhook_handler.verify_jira_webhook"),
        patch("src.webhook_handler.JiraTriageAgent") as agent_class,
    ):
        status_code, response_body = process_jira_webhook(
            json.dumps(payload).encode(),
            {},
            require_webhook_signature=False,
        )

    assert status_code == 200
    assert response_body["status"] == "ignored"
    agent_class.return_value.process_ticket.assert_not_called()


def test_webhook_emits_structured_logs_and_redacts_secrets(caplog):
    """Ensure incoming webhooks emit structured WEBHOOK_RECEIVED and WEBHOOK_RESULT logs without leaking secrets."""
    import logging

    payload = {
        "webhookEvent": "comment_created",
        "issue": {
            "id": "10001",
            "key": "OP-101",
            "fields": {
                "summary": "Avaliar lead",
                "issuetype": {"id": "12716", "name": "Lead"},
                "status": {"id": "1", "name": "Open Lead"},
            },
        },
        "comment": {
            "id": "comment-20",
            "body": "Prazo de pagamento: 30 dias.",
            "author": {"accountId": "customer-1", "displayName": "Solicitante"},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Atlassian-Webhook-Secret": "super-secret-value-123",
        "Authorization": "Bearer secret-jwt-token",
    }

    with (
        caplog.at_level(logging.INFO, logger="jira-webhook-handler"),
        patch("src.webhook_handler.verify_jira_webhook"),
        patch("src.webhook_handler.JiraTriageAgent") as agent_class,
    ):
        agent_class.return_value.process_ticket.return_value = MagicMock(
            success=True,
            decision=None,
            actions_taken=["Ferramenta Jira executada: get_lead_details."],
            run_id="resp_123",
            error_message=None,
            model_dump=lambda mode: {"success": True},
        )
        status_code, _ = process_jira_webhook(
            json.dumps(payload).encode(),
            headers,
            require_webhook_signature=True,
            transaction_id="transaction-test-1",
        )

    assert status_code == 200
    log_text = "\n".join(caplog.messages)
    assert "[WEBHOOK_RECEIVED]" in log_text
    assert "[WEBHOOK_RESULT]" in log_text
    assert "OP-101" in log_text
    assert "comment_created" in log_text
    assert "super-secret-value-123" not in log_text
    assert "secret-jwt-token" not in log_text
    assert "***REDACTED***" in log_text
    assert "Prazo de pagamento: 30 dias." not in log_text
    assert "Avaliar lead" not in log_text
    assert log_text.count('"transaction_id": "transaction-test-1"') == 2


def test_debug_content_logs_are_issue_scoped_expiring_and_redact_credentials(caplog):
    logger = logging.getLogger("jira-debug-content-test")
    expires_at = datetime.now(UTC) + timedelta(minutes=10)

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        logged = log_debug_content(
            logger,
            issue_key="OP-101",
            stage="model_input",
            content={
                "comment": "Full customer comment",
                "api_token": "never-log-this",
            },
            enabled=True,
            configured_issue_key="op-101",
            expires_at=expires_at,
        )
        wrong_issue_logged = log_debug_content(
            logger,
            issue_key="OP-102",
            stage="model_input",
            content="must not be logged",
            enabled=True,
            configured_issue_key="OP-101",
            expires_at=expires_at,
        )
        all_issues_logged = log_debug_content(
            logger,
            issue_key="OP-102",
            stage="model_output",
            content="model output from a different issue",
            enabled=True,
            configured_issue_key="*",
            expires_at=expires_at,
        )
        expired_logged = log_debug_content(
            logger,
            issue_key="OP-101",
            stage="model_input",
            content="must not be logged",
            enabled=True,
            configured_issue_key="OP-101",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )

    assert logged is True
    assert wrong_issue_logged is False
    assert all_issues_logged is True
    assert expired_logged is False
    assert "[AGENT_DEBUG_CONTENT]" in caplog.text
    assert "Full customer comment" in caplog.text
    assert "model output from a different issue" in caplog.text
    assert '"issue_key": "OP-102"' in caplog.text
    assert "never-log-this" not in caplog.text
    assert "***REDACTED***" in caplog.text


def test_webhook_full_payload_is_logged_only_when_debug_is_explicitly_scoped(caplog):
    import logging

    payload = {
        "webhookEvent": "comment_created",
        "issue": {
            "id": "10001",
            "key": "OP-101",
            "fields": {"summary": "Private lead details"},
        },
        "comment": {"body": "Full private customer comment"},
    }
    settings = Settings(
        jira_debug_log_content=True,
        jira_debug_log_content_issue_key="OP-101",
        jira_debug_log_content_until=datetime.now(UTC) + timedelta(minutes=5),
        log_level="DEBUG",
    )

    with (
        caplog.at_level(logging.DEBUG, logger="jira-webhook-handler"),
        patch("src.webhook_handler.get_settings", return_value=settings),
        patch("src.webhook_handler.verify_jira_webhook"),
        patch("src.webhook_handler.JiraTriageAgent") as agent_class,
    ):
        agent_class.return_value.process_ticket.return_value = MagicMock(
            success=True,
            model_dump=lambda mode: {"success": True},
        )
        status_code, _ = process_jira_webhook(
            json.dumps(payload).encode(),
            {},
            require_webhook_signature=False,
        )

    assert status_code == 200
    assert "Full private customer comment" in caplog.text
    assert "Private lead details" in caplog.text


def test_direct_jira_issue_json_payload_is_accepted():
    """Accept direct Jira REST API issue JSON (without an outer 'issue' wrapper)."""
    direct_issue_payload = {
        "id": "651497",
        "key": "OP-8885",
        "fields": {
            "summary": "[TESTE Agente IA] Novo Lead do Site - Anydesk",
            "issuetype": {"id": "12716", "name": "Lead"},
            "status": {"id": "10001", "name": "Open Lead"},
        },
    }

    with (
        patch("src.webhook_handler.verify_jira_webhook"),
        patch("src.webhook_handler.JiraTriageAgent") as agent_class,
    ):
        agent_class.return_value.process_ticket.return_value = MagicMock(
            success=True,
            decision=None,
            actions_taken=[],
            run_id="resp_direct",
            error_message=None,
            model_dump=lambda mode: {"success": True, "issue_key": "OP-8885"},
        )
        status_code, response_body = process_jira_webhook(
            json.dumps(direct_issue_payload).encode(),
            {},
            require_webhook_signature=False,
        )

    assert status_code == 200
    assert response_body == {"success": True, "issue_key": "OP-8885"}
    validated_payload = agent_class.return_value.process_ticket.call_args.args[0]
    assert validated_payload.issue_key == "OP-8885"
    assert validated_payload.issue.id == "651497"


def test_webhook_fast_return_when_agent_exceeds_wait_timeout(caplog):
    """Return 200 OK with status='processing' immediately when agent exceeds wait_timeout_seconds, while completing in background."""
    import logging
    import threading
    import time

    payload = {
        "webhookEvent": "jira:issue_created",
        "issue": {
            "id": "652011",
            "key": "OP-8888",
            "fields": {
                "summary": "[TESTE Agente IA] Lead do site | Loonar | AnyDesk",
                "issuetype": {"id": "12716", "name": "Lead"},
                "status": {"id": "10001", "name": "Open Lead"},
            },
        },
    }
    background_done = threading.Event()

    def _slow_process_ticket(_payload):
        time.sleep(0.15)
        background_done.set()
        return MagicMock(
            success=True,
            decision=None,
            actions_taken=["Ferramenta Jira executada: escalate_to_human_group."],
            run_id="resp_slow",
            error_message=None,
            model_dump=lambda mode: {"success": True, "issue_key": "OP-8888"},
        )

    with (
        caplog.at_level(logging.INFO, logger="jira-webhook-handler"),
        patch("src.webhook_handler.verify_jira_webhook"),
        patch("src.webhook_handler.JiraTriageAgent") as agent_class,
    ):
        agent_class.return_value.process_ticket.side_effect = _slow_process_ticket
        status_code, response_body = process_jira_webhook(
            json.dumps(payload).encode(),
            {},
            require_webhook_signature=True,
            wait_timeout_seconds=0.02,
            transaction_id="transaction-background-1",
        )
        assert status_code == 200
        assert response_body["status"] == "processing"
        assert response_body["issue_key"] == "OP-8888"
        assert response_body["success"] is True

        assert background_done.wait(timeout=2.0)
        time.sleep(0.02)

    log_text = "\n".join(caplog.messages)
    assert "[WEBHOOK_RECEIVED]" in log_text
    assert "[WEBHOOK_ACCEPTED_ASYNC]" in log_text
    assert "[WEBHOOK_RESULT]" in log_text
    assert "resp_slow" in log_text
    assert log_text.count('"transaction_id": "transaction-background-1"') == 3
