"""Pydantic schemas for Jira Webhook payloads."""

from typing import Any

from pydantic import BaseModel, Field


class JiraUser(BaseModel):
    """Representa um usuário no Jira."""

    account_id: str | None = Field(default=None, alias="accountId")
    display_name: str | None = Field(default=None, alias="displayName")
    email_address: str | None = Field(default=None, alias="emailAddress")


class JiraPriority(BaseModel):
    """Prioridade de uma issue."""

    id: str | None = None
    name: str | None = None


class JiraStatus(BaseModel):
    """Status atual da issue."""

    id: str | None = None
    name: str | None = None


class JiraIssueType(BaseModel):
    """Tipo do chamado no Jira."""

    id: str | None = None
    name: str | None = None


class JiraFields(BaseModel):
    """Campos principais de uma issue do Jira Service Management."""

    summary: str = Field(description="Título/resumo do chamado")
    description: Any | None = Field(
        default=None, description="Descrição do chamado (texto ou doc format)"
    )
    priority: JiraPriority | None = None
    status: JiraStatus | None = None
    issuetype: JiraIssueType | None = None
    labels: list[str] = Field(default_factory=list)
    reporter: JiraUser | None = None
    assignee: JiraUser | None = None

    def get_description_text(self) -> str:
        """Extrai a descrição em formato de texto legível."""
        if isinstance(self.description, str):
            return self.description
        if isinstance(self.description, dict):
            # Formato Atlassian Document Format (ADF) simples
            return str(self.description)
        return ""


class JiraIssue(BaseModel):
    """Objeto da issue incluído no webhook."""

    id: str
    key: str
    fields: JiraFields


class JiraWebhookPayload(BaseModel):
    """Payload de webhook enviado pelo Jira Service Management."""

    webhook_event: str = Field(alias="webhookEvent")
    timestamp: int | None = None
    issue: JiraIssue
    changelog: dict[str, Any] | None = None

    @property
    def issue_key(self) -> str:
        return self.issue.key

    @property
    def summary(self) -> str:
        return self.issue.fields.summary

    @property
    def description(self) -> str:
        return self.issue.fields.get_description_text()
