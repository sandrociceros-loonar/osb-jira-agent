"""Load Jira credentials from Azure Key Vault for the Foundry hosted runtime."""

from urllib.parse import urlparse

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

from src.config import get_settings

JIRA_RUNTIME_SECRET_NAMES = {
    "jira_api_token": "jira-api-token",
    "jira_assets_access_token": "jira-assets-access-token",
}


def configure_jira_runtime_secrets() -> None:
    """Load Jira API credentials using the Foundry agent identity."""
    settings = get_settings()
    parsed_url = urlparse(settings.jira_key_vault_url)
    if (
        parsed_url.scheme != "https"
        or not parsed_url.netloc
        or parsed_url.path not in ("", "/")
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise ValueError("JIRA_KEY_VAULT_URL must be a valid HTTPS Key Vault URL.")

    credential = DefaultAzureCredential()
    try:
        client = SecretClient(
            vault_url=settings.jira_key_vault_url.rstrip("/"),
            credential=credential,
        )
        try:
            secrets = {
                setting_name: _get_required_secret(client, secret_name)
                for setting_name, secret_name in JIRA_RUNTIME_SECRET_NAMES.items()
            }
        finally:
            client.close()
    finally:
        credential.close()

    settings.jira_api_token = secrets["jira_api_token"]
    settings.jira_assets_access_token = secrets["jira_assets_access_token"]


def _get_required_secret(client: SecretClient, secret_name: str) -> str:
    secret = client.get_secret(secret_name)
    if not secret.value:
        raise ValueError(f"Azure Key Vault secret '{secret_name}' is empty or unavailable.")
    return secret.value
