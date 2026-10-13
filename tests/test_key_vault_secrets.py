"""Tests for loading hosted-agent Jira credentials from Azure Key Vault."""

from unittest.mock import Mock, patch

import pytest

from src.config import Settings
from src.security.key_vault_secrets import (
    JIRA_RUNTIME_SECRET_NAMES,
    configure_jira_runtime_secrets,
)


def test_loads_jira_secrets_from_key_vault():
    settings = Settings(JIRA_KEY_VAULT_URL="https://example.vault.azure.net/")
    credential = Mock()
    client = Mock()
    client.get_secret.side_effect = lambda name: Mock(value=f"value-for-{name}")

    with (
        patch("src.security.key_vault_secrets.get_settings", return_value=settings),
        patch("src.security.key_vault_secrets.DefaultAzureCredential", return_value=credential),
        patch("src.security.key_vault_secrets.SecretClient", return_value=client) as create_client,
    ):
        configure_jira_runtime_secrets()

    create_client.assert_called_once_with(
        vault_url="https://example.vault.azure.net",
        credential=credential,
    )
    assert [call.args[0] for call in client.get_secret.call_args_list] == list(
        JIRA_RUNTIME_SECRET_NAMES.values()
    )
    assert settings.jira_api_token == "value-for-jira-api-token"
    assert settings.jira_assets_access_token == "value-for-jira-assets-access-token"
    client.close.assert_called_once()
    credential.close.assert_called_once()


def test_rejects_empty_key_vault_secret_and_closes_clients():
    settings = Settings(JIRA_KEY_VAULT_URL="https://example.vault.azure.net")
    credential = Mock()
    client = Mock()
    client.get_secret.side_effect = lambda name: Mock(
        value="" if name == JIRA_RUNTIME_SECRET_NAMES["jira_api_token"] else "value"
    )

    with (
        patch("src.security.key_vault_secrets.get_settings", return_value=settings),
        patch("src.security.key_vault_secrets.DefaultAzureCredential", return_value=credential),
        patch("src.security.key_vault_secrets.SecretClient", return_value=client),
        pytest.raises(ValueError, match="jira-api-token"),
    ):
        configure_jira_runtime_secrets()

    client.close.assert_called_once()
    credential.close.assert_called_once()


def test_rejects_non_https_key_vault_url():
    settings = Settings(JIRA_KEY_VAULT_URL="http://example.vault.azure.net")

    with (
        patch("src.security.key_vault_secrets.get_settings", return_value=settings),
        patch("src.security.key_vault_secrets.DefaultAzureCredential") as create_credential,
        pytest.raises(ValueError, match="JIRA_KEY_VAULT_URL"),
    ):
        configure_jira_runtime_secrets()

    create_credential.assert_not_called()
