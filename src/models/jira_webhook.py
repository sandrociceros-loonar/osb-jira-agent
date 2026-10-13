"""Pydantic schemas for Jira Webhook payloads."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class JiraComment(BaseModel):
    """Comentário opcional incluído nos eventos de comentário do Jira."""

    id: str | None = None
    body: Any | None = None
    author: JiraUser | None = None
    created: str | None = None
    update_author: JiraUser | None = Field(default=None, alias="updateAuthor")

    def get_body_text(self) -> str:
        """Retorna texto de comentário em string ou Atlassian Document Format."""
        return _extract_adf_text(self.body)


class JiraFields(BaseModel):
    """Campos principais de uma issue do Jira Service Management."""

    model_config = ConfigDict(extra="allow")

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
        return _extract_adf_text(self.description)

    def get_request_details_text(self, field_id: str | None = None) -> str | None:
        """Extrai o texto do campo Detalhes da Solicitação se presente."""
        if field_id:
            val = getattr(self, field_id, None)
            if val is None and hasattr(self, "__pydantic_extra__") and self.__pydantic_extra__:
                val = self.__pydantic_extra__.get(field_id)
            if val is not None:
                text = _extract_adf_text(val).strip()
                if text:
                    return text

        if hasattr(self, "__pydantic_extra__") and self.__pydantic_extra__:
            for k, v in self.__pydantic_extra__.items():
                k_lower = k.lower()
                if "detalhe" in k_lower or "request_detail" in k_lower or "solicitacao" in k_lower:
                    text = _extract_adf_text(v).strip()
                    if text:
                        return text

        return None


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
    comment: JiraComment | None = None

    @property
    def issue_key(self) -> str:
        return self.issue.key

    @property
    def summary(self) -> str:
        return self.issue.fields.summary

    @property
    def description(self) -> str:
        return self.issue.fields.get_description_text()

    @property
    def request_details(self) -> str | None:
        return self.issue.fields.get_request_details_text()


def _extract_adf_text(value: Any) -> str:
    """Flatten text nodes from Jira strings, ADF documents, or nested lists."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_extract_adf_text(item) for item in value)
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text
        content = value.get("content")
        if isinstance(content, list):
            separator = (
                "\n"
                if value.get("type")
                in {"doc", "paragraph", "heading", "listItem", "blockquote", "tableRow"}
                else ""
            )
            return separator.join(_extract_adf_text(item) for item in content)
    return ""
