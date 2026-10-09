"""Application Configuration using Pydantic Settings."""

from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações globais da aplicação carregadas do ambiente."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Model provider
    model_provider: Literal["azure", "foundry-local", "ollama"] = Field(
        default="azure",
        alias="MODEL_PROVIDER",
        description="Provedor do modelo: Azure Foundry, Foundry Local ou Ollama",
    )

    # Azure AI Foundry
    azure_ai_project_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices("AZURE_AI_PROJECT_ENDPOINT", "FOUNDRY_PROJECT_ENDPOINT"),
        description="Endpoint completo do projeto Azure AI Foundry",
    )
    azure_ai_project_connection_string: str = Field(
        default="",
        alias="AZURE_AI_PROJECT_CONNECTION_STRING",
        description="String legada do projeto no Azure AI Foundry",
    )
    azure_ai_model_deployment_name: str = Field(
        default="gpt-4o",
        alias="AZURE_AI_MODEL_DEPLOYMENT_NAME",
        description="Nome do deployment do modelo no Azure AI Foundry",
    )
    foundry_local_model_alias: str = Field(
        default="phi-4-mini",
        alias="FOUNDRY_LOCAL_MODEL_ALIAS",
        description="Alias do modelo instalado no Foundry Local",
    )
    foundry_local_base_url: str = Field(
        default="http://127.0.0.1:5273/v1",
        alias="FOUNDRY_LOCAL_BASE_URL",
        description="Endpoint OpenAI-compatible do serviço Foundry Local",
    )
    ollama_model_name: str = Field(
        default="qwen3:4b",
        alias="OLLAMA_MODEL_NAME",
        description="Nome do modelo instalado no Ollama",
    )
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434/v1",
        alias="OLLAMA_BASE_URL",
        description="Endpoint OpenAI-compatible do Ollama local",
    )
    azure_ai_max_tool_calls: int = Field(
        default=16,
        alias="AZURE_AI_MAX_TOOL_CALLS",
        ge=1,
        le=64,
        description="Limite total de chamadas de ferramentas Jira por execução",
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
    jira_api_email: str = Field(
        default="",
        alias="JIRA_API_EMAIL",
        description="E-mail da conta Atlassian usado para autenticação na API",
    )
    jira_api_token: str = Field(
        default="",
        alias="JIRA_API_TOKEN",
        description="Token de API Atlassian usado para autenticação na API",
        repr=False,
    )
    jira_team_account_ids: dict[str, str] = Field(
        default_factory=dict,
        alias="JIRA_TEAM_ACCOUNT_IDS",
        description="Mapeamento de equipe para accountId do Jira",
    )
    jira_project_key: str = Field(
        default="ITSM",
        alias="JIRA_PROJECT_KEY",
        description="Chave do projeto Jira Service Management padrão",
    )
    jira_allowed_project_keys: list[str] = Field(
        default_factory=lambda: ["ITSM", "OP"],
        alias="JIRA_ALLOWED_PROJECT_KEYS",
        description="Projetos que o agente pode consultar ou alterar",
    )
    jira_lead_project_key: str = Field(
        default="OP",
        alias="JIRA_LEAD_PROJECT_KEY",
        description="Projeto Jira no qual a ferramenta pode criar leads",
    )
    jira_lead_issue_type_id: str = Field(
        default="12716",
        alias="JIRA_LEAD_ISSUE_TYPE_ID",
        description="ID do tipo de issue usado ao criar leads",
    )
    jira_transition_ids: dict[str, str] = Field(
        default_factory=lambda: {
            "start_lead_work": "2",
            "transition_lead_to_proposal_item": "21",
            "generate_new_proposal": "3",
            "send_item_to_purchasing": "12",
            "set_proposal_item_price": "7",
        },
        alias="JIRA_TRANSITION_IDS",
        description="IDs das transições definidas nos manifestos; variam por workflow Jira",
    )
    jira_allow_write_operations: bool = Field(
        default=False,
        alias="JIRA_ENABLE_WRITE_OPERATIONS",
        description="Habilita criação, comentários e transições definidos nas ferramentas",
    )
    jira_assets_access_token: str = Field(
        default="",
        alias="JIRA_ASSETS_ACCESS_TOKEN",
        description="Token OAuth Bearer para as APIs Jira Assets em api.atlassian.com",
        repr=False,
    )
    jira_assets_cloud_id: str = Field(
        default="",
        alias="JIRA_ASSETS_CLOUD_ID",
        description="Cloud ID do Jira; pode ser descoberto automaticamente",
    )
    jira_assets_workspace_id: str = Field(
        default="",
        alias="JIRA_ASSETS_WORKSPACE_ID",
        description="Workspace ID do Assets; pode ser descoberto automaticamente",
    )
    jira_assets_product_object_type_id: str = Field(
        default="157",
        alias="JIRA_ASSETS_PRODUCT_OBJECT_TYPE_ID",
        description="Object type ID de produtos consultado pela pesquisa AQL",
    )
    jira_attachment_max_bytes: int = Field(
        default=65536,
        alias="JIRA_ATTACHMENT_MAX_BYTES",
        ge=1,
        le=1048576,
        description="Limite de bytes para anexos disponibilizados ao modelo",
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
