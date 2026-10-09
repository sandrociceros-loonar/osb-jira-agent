"""Tests for webhook security and HMAC verification."""

import hashlib
import hmac

import pytest

from src.security.webhook_verifier import WebhookSecurityError, verify_jira_webhook


def test_verify_webhook_with_valid_secret_header(test_settings):
    """Testa aprovação de webhook com cabeçalho de segredo correto."""
    headers = {"X-Atlassian-Webhook-Secret": "test-secret-12345"}
    raw_body = b'{"test": "payload"}'

    assert (
        verify_jira_webhook(headers=headers, raw_body=raw_body, secret="test-secret-12345") is True
    )


def test_verify_webhook_with_invalid_secret_header(test_settings):
    """Testa rejeição de webhook com cabeçalho de segredo incorreto."""
    headers = {"X-Atlassian-Webhook-Secret": "wrong-secret"}
    raw_body = b'{"test": "payload"}'

    with pytest.raises(WebhookSecurityError):
        verify_jira_webhook(headers=headers, raw_body=raw_body, secret="test-secret-12345")


def test_verify_webhook_with_valid_hmac_signature(test_settings):
    """Testa aprovação de webhook com assinatura HMAC-SHA256 válida."""
    secret = "test-secret-12345"
    raw_body = b'{"issue": "ITSM-101"}'
    signature = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    headers = {"X-Hub-Signature-256": f"sha256={signature}"}
    assert verify_jira_webhook(headers=headers, raw_body=raw_body, secret=secret) is True


def test_verify_webhook_with_invalid_hmac_signature(test_settings):
    """Testa rejeição de webhook com assinatura HMAC-SHA256 adulterada."""
    secret = "test-secret-12345"
    raw_body = b'{"issue": "ITSM-101"}'
    fake_signature = "sha256=1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"

    headers = {"X-Hub-Signature-256": fake_signature}
    with pytest.raises(WebhookSecurityError):
        verify_jira_webhook(headers=headers, raw_body=raw_body, secret=secret)
