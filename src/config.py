"""Application Configuration using Pydantic Settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações globais da aplicação carregadas do ambiente."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Azure AI Foundry
    azure_ai_project_connection_string: str = Field(
        default="",
        alias="AZURE_AI_PROJECT_CONNECTION_STRING",
        description="String de conexão do projeto no Azure AI Foundry",
    )
    azure_ai_agent_id: str = Field(
        default="",
        alias="AZURE_AI_AGENT_ID",
        description="ID do agente pré-criado no Foundry Studio (opcional)",
    )
    azure_ai_model_deployment_name: str = Field(
        default="gpt-4o",
        alias="AZURE_AI_MODEL_DEPLOYMENT_NAME",
        description="Nome do deployment do modelo no Azure AI Foundry",
    )

    # Jira Webhook Security
    jira_webhook_secret: str = Field(
        default="",
        alias="JIRA_WEBHOOK_SECRET",
        description="Segredo compartilhado para validação do webhook do Jira",
    )
    jira_webhook_secret_header: str = Field(
        default="X-Atlassian-Webhook-Secret",
        alias="JIRA_WEBHOOK_SECRET_HEADER",
        description="Nome do cabeçalho HTTP contendo o segredo do webhook",
    )

    # Jira Context
    jira_instance_url: str = Field(
        default="https://your-domain.atlassian.net",
        alias="JIRA_INSTANCE_URL",
        description="URL base da instância Jira",
    )
    jira_project_key: str = Field(
        default="ITSM",
        alias="JIRA_PROJECT_KEY",
        description="Chave do projeto Jira Service Management padrão",
    )

    # Runtime
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    environment: str = Field(default="development", alias="ENVIRONMENT")


_settings: Settings | None = None


def get_settings() -> Settings:
    """Retorna a instância singleton de configurações."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
