"""Models representing the AI Agent decision and triage outcome."""

from enum import StrEnum

from pydantic import BaseModel, Field


class TriageCategory(StrEnum):
    """Categorias operacionais comuns de ITSM."""

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
    """Decisão estruturada emitida pelo Agente do Foundry."""

    category: TriageCategory = Field(description="Categoria atribuída ao chamado")
    priority: TriagePriority = Field(description="Prioridade calculada para o chamado")
    assigned_team: str = Field(description="Equipe ou fila sugerida/atribuída")
    suggested_status: str | None = Field(
        default=None,
        description="Status para transição (ex: 'In Progress', 'Waiting for Customer', 'Resolved')",
    )
    should_auto_close: bool = Field(
        default=False,
        description="Indica se o chamado foi resolvido e deve ser fechado automaticamente",
    )
    reasoning: str = Field(description="Justificativa da triagem baseada no conteúdo do chamado")
    internal_comment: str | None = Field(
        default=None,
        description="Comentário interno a ser registrado na issue do Jira",
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
