"""Models representing the AI Agent decision and triage outcome."""

from enum import StrEnum

from pydantic import BaseModel, Field


class TriageCategory(StrEnum):
    """Categorias de CRM comercial, mantendo os valores ITSM legados válidos."""

    LEAD = "Lead"
    PROPOSAL = "Proposta"
    PROPOSAL_ITEM = "Item da proposta"
    COMMERCIAL_QUERY = "Consulta comercial"
    PRODUCT_PURCHASING = "Produto/Compras"
    INFRASTRUCTURE = "Infrastructure & Cloud"
    ACCESS_MANAGEMENT = "Access & Permissions"
    SOFTWARE_BUG = "Software Bug"
    HARDWARE = "Hardware & Peripherals"
    NETWORK = "Network & VPN"
    GENERAL_SUPPORT = "General Support"


class TriagePriority(StrEnum):
    """Níveis de prioridade do Jira."""

    HIGHEST = "Highest"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    LOWEST = "Lowest"


class TriageDecision(BaseModel):
    """Resumo estruturado de uma interação do agente com uma issue Jira."""

    category: TriageCategory = Field(description="Categoria comercial da issue ou da solicitação")
    priority: TriagePriority | None = Field(
        default=None,
        description="Prioridade Jira; null para não alterar a prioridade",
    )
    assigned_team: str | None = Field(
        default=None,
        description="Equipe Jira; null para não alterar a atribuição",
    )
    suggested_status: str | None = Field(
        default=None,
        description="Status Jira opcional; null quando nenhuma transição genérica deve ocorrer",
    )
    should_auto_close: bool = Field(
        default=False,
        description="Indica se a issue deve ser encerrada automaticamente",
    )
    reasoning: str = Field(
        description="Resumo do pedido e da ação comercial baseada nos dados disponíveis"
    )
    internal_comment: str | None = Field(
        default=None,
        description="Comentário interno solicitado explicitamente para a issue",
    )


class AgentExecutionResult(BaseModel):
    """Resultado da execução completa do agente para um webhook."""

    issue_key: str
    success: bool
    decision: TriageDecision | None = None
    actions_taken: list[str] = Field(default_factory=list)
    error_message: str | None = None
    thread_id: str | None = None
    run_id: str | None = None
