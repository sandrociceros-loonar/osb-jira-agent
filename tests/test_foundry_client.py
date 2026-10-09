"""Tests for Microsoft Foundry project endpoint handling."""

from unittest.mock import MagicMock, patch

import pytest

from src.agent.foundry_client import FoundryClientManager


def test_project_endpoint_initializes_current_sdk_client():
    manager = FoundryClientManager(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo"
    )
    credential = MagicMock()
    manager._credential = credential

    with patch("src.agent.foundry_client.AIProjectClient") as client_class:
        project_client = client_class.return_value
        openai_client = project_client.get_openai_client.return_value
        assert manager.get_openai_client() is openai_client

    client_class.assert_called_once_with(
        endpoint="https://example.services.ai.azure.com/api/projects/demo",
        credential=credential,
    )


def test_legacy_connection_string_is_converted_to_project_endpoint():
    manager = FoundryClientManager(
        connection_string=(
            "https://example.services.ai.azure.com/;subscription;resource-group;project name"
        )
    )

    assert manager._endpoint_from_legacy_connection_string() == (
        "https://example.services.ai.azure.com/api/projects/project%20name"
    )


@pytest.mark.parametrize(
    "connection_string",
    [
        "host;subscription;resource-group",
        "http://example.com;subscription;resource-group;project",
        "https://example.com/path;subscription;resource-group;project",
    ],
)
def test_invalid_legacy_connection_strings_fail_explicitly(connection_string):
    manager = FoundryClientManager(connection_string=connection_string)
    with pytest.raises(ValueError):
        manager._endpoint_from_legacy_connection_string()


def test_non_https_project_endpoint_is_rejected():
    manager = FoundryClientManager(project_endpoint="http://example.services.ai.azure.com/project")
    with pytest.raises(ValueError, match="HTTPS"):
        manager.get_client()


def test_local_provider_returns_openai_client_without_azure_project():
    manager = FoundryClientManager()
    manager.settings.model_provider = "foundry-local"
    local_client = MagicMock()

    with patch.object(manager, "_get_local_openai_client", return_value=local_client):
        assert manager.get_openai_client() is local_client

    assert manager._client is None
    assert manager._credential is None


def test_ollama_provider_returns_openai_compatible_client_without_azure_project():
    manager = FoundryClientManager()
    manager.settings.model_provider = "ollama"
    manager.settings.ollama_base_url = "http://127.0.0.1:11434/v1"

    with patch("src.agent.foundry_client.OpenAI") as client_class:
        client = manager.get_openai_client()

    client_class.assert_called_once_with(
        base_url="http://127.0.0.1:11434/v1",
        api_key="ollama",
    )
    assert client is client_class.return_value
    assert manager._client is None
    assert manager._credential is None


def test_ollama_provider_rejects_invalid_endpoint():
    manager = FoundryClientManager()
    manager.settings.model_provider = "ollama"
    manager.settings.ollama_base_url = "not-a-url"

    with pytest.raises(ValueError, match="OLLAMA_BASE_URL"):
        manager.get_openai_client()
