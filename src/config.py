"""Application Configuration using Pydantic Settings."""

from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações globais da aplicação carregadas do ambiente."""

    @field_validator("jira_request_details_field_id", mode="before")
    @classmethod
    def default_request_details_field_id(cls, value: object) -> str:
        if value is None or not str(value).strip():
            return "customfield_10120"
        return str(value).strip()

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
        default="gpt-5",
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
        repr=False,
    )
    jira_key_vault_url: str = Field(
        default="",
        alias="JIRA_KEY_VAULT_URL",
        description="URI do Azure Key Vault que contém os segredos Jira",
    )
    jira_webhook_secret_header: str = Field(
        default="X-Atlassian-Webhook-Secret",
        alias="JIRA_WEBHOOK_SECRET_HEADER",
        description="Nome do cabeçalho HTTP contendo o segredo do webhook",
    )
    jira_webhook_response_timeout_seconds: float = Field(
        default=2.0,
        alias="JIRA_WEBHOOK_RESPONSE_TIMEOUT_SECONDS",
        ge=0.0,
        le=120.0,
        description=(
            "Tempo máximo em segundos que o endpoint de webhook aguarda pelo agente "
            "antes de responder 200 OK (retorno rápido) e concluir em background"
        ),
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
    jira_customer_message_transition_id: str = Field(
        default="36",
        alias="JIRA_CUSTOMER_MESSAGE_TRANSITION_ID",
        description="ID da transição Jira 'Mensagem para o Cliente' que dispara o envio ao cliente",
    )
    jira_customer_message_field_id: str = Field(
        default="customfield_15195",
        alias="JIRA_CUSTOMER_MESSAGE_FIELD_ID",
        description="ID do campo Jira 'Mensagem Para Cliente' preenchido na transição de envio ao cliente",
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
    jira_manufacturer_field_id: str = Field(
        default="",
        alias="JIRA_MANUFACTURER_FIELD_ID",
        description=(
            "ID opcional do campo Jira para gravar o fabricante; "
            "se vazio, o conector localiza um campo chamado Fabricante/Manufacturer"
        ),
    )
    jira_skip_manufacturer_update_if_not_editable: bool = Field(
        default=False,
        alias="JIRA_SKIP_MANUFACTURER_UPDATE_IF_NOT_EDITABLE",
        description=(
            "Permite continuar o webhook com atualização de fabricante pendente quando "
            "o campo existe, mas não está editável; a geração de proposta continua bloqueada"
        ),
    )
    jira_agent_account_id: str = Field(
        default="",
        alias="JIRA_AGENT_ACCOUNT_ID",
        description="Account ID Jira do agente para reconhecer seus próprios comentários",
    )
    jira_attachment_max_bytes: int = Field(
        default=65536,
        alias="JIRA_ATTACHMENT_MAX_BYTES",
        ge=1,
        le=1048576,
        description="Limite de bytes para anexos disponibilizados ao modelo",
    )

    # Confluence Knowledge Base & RAG
    confluence_space_url: str = Field(
        default="https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage",
        alias="CONFLUENCE_SPACE_URL",
        description="URL completa do espaço Confluence da base de conhecimento",
    )
    confluence_base_url: str = Field(
        default="https://loonar-osb.atlassian.net/wiki",
        alias="CONFLUENCE_BASE_URL",
        description="URL base da API do Confluence Cloud",
    )
    confluence_space_key: str = Field(
        default="osbjiraage",
        alias="CONFLUENCE_SPACE_KEY",
        description="Chave do espaço Confluence da base de conhecimento",
    )
    confluence_api_email: str = Field(
        default="",
        alias="CONFLUENCE_API_EMAIL",
        description="E-mail da conta Atlassian para Confluence; herda de JIRA_API_EMAIL se vazio",
    )
    confluence_api_token: str = Field(
        default="",
        alias="CONFLUENCE_API_TOKEN",
        description="Token de API Confluence; herda de JIRA_API_TOKEN se vazio",
        repr=False,
    )
    confluence_webhook_secret: str = Field(
        default="",
        alias="CONFLUENCE_WEBHOOK_SECRET",
        description="Segredo compartilhado para validação do webhook do Confluence",
        repr=False,
    )
    confluence_webhook_secret_header: str = Field(
        default="X-Atlassian-Webhook-Secret",
        alias="CONFLUENCE_WEBHOOK_SECRET_HEADER",
        description="Nome do cabeçalho contendo o segredo do webhook Confluence",
    )
    jira_request_details_field_id: str = Field(
        default="customfield_10120",
        alias="JIRA_REQUEST_DETAILS_FIELD_ID",
        description="ID do campo Jira Detalhes da Solicitação (conforme metadados do projeto OP)",
    )
    kb_cache_dir: str = Field(
        default=".cache/kb",
        alias="KB_CACHE_DIR",
        description="Diretório para armazenamento em disco do cache da base de conhecimento",
    )
    kb_cache_ttl_seconds: int = Field(
        default=3600,
        alias="KB_CACHE_TTL_SECONDS",
        ge=1,
        description="TTL do cache da base de conhecimento em segundos",
    )
    kb_min_confidence_score: float = Field(
        default=0.15,
        alias="KB_MIN_CONFIDENCE_SCORE",
        ge=0.0,
        le=1.0,
        description="Similaridade mínima para validar resposta encontrada na KB",
    )
    kb_human_escalation_team: str = Field(
        default="Equipe Comercial Humana",
        alias="KB_HUMAN_ESCALATION_TEAM",
        description="Nome da equipe humana para escalação quando a resposta não for encontrada",
    )
    kb_human_escalation_group_account_id: str = Field(
        default="",
        alias="KB_HUMAN_ESCALATION_GROUP_ACCOUNT_ID",
        description="AccountId Jira do grupo ou responsável para escalação humana",
    )
    kb_human_escalation_transition_id: str = Field(
        default="",
        alias="KB_HUMAN_ESCALATION_TRANSITION_ID",
        description="ID opcional de transição Jira para mover o lead para atendimento humano",
    )
    kb_enabled: bool = Field(
        default=True,
        alias="KB_ENABLED",
        description="Habilita resposta a dúvidas com base de conhecimento Confluence",
    )

    def model_post_init(self, __context: object) -> None:
        super().model_post_init(__context)
        if self.confluence_space_url:
            parsed = urlparse(self.confluence_space_url)
            if "/spaces/" in parsed.path:
                parts = parsed.path.strip("/").split("/")
                try:
                    idx = parts.index("spaces")
                    if idx + 1 < len(parts) and parts[idx + 1]:
                        self.confluence_space_key = parts[idx + 1]
                except ValueError:
                    pass
                wiki_part = parsed.path[: parsed.path.find("/spaces")].rstrip("/")
                self.confluence_base_url = f"{parsed.scheme}://{parsed.netloc}{wiki_part}"

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
