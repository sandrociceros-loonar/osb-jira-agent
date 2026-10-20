"""Pydantic schemas for Jira Webhook payloads."""

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _normalize_jira_identifier(value: Any) -> Any:
    """Normalize numeric Jira IDs to strings while preserving invalid values for validation."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value


JiraIdentifier = Annotated[str, BeforeValidator(_normalize_jira_identifier)]
OptionalJiraIdentifier = Annotated[str | None, BeforeValidator(_normalize_jira_identifier)]


class JiraUser(BaseModel):
    """Representa um usuário no Jira."""

    account_id: str | None = Field(default=None, alias="accountId")
    display_name: str | None = Field(default=None, alias="displayName")
    email_address: str | None = Field(default=None, alias="emailAddress")


class JiraPriority(BaseModel):
    """Prioridade de uma issue."""

    id: OptionalJiraIdentifier = None
    name: str | None = None


class JiraStatus(BaseModel):
    """Status atual da issue."""

    id: OptionalJiraIdentifier = None
    name: str | None = None


class JiraIssueType(BaseModel):
    """Tipo do chamado no Jira."""

    id: OptionalJiraIdentifier = None
    name: str | None = None


class JiraComment(BaseModel):
    """Comentário opcional incluído nos eventos de comentário do Jira."""

    id: OptionalJiraIdentifier = None
    body: Any | None = None
    author: JiraUser | None = None
    created: OptionalJiraIdentifier = None
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

    id: JiraIdentifier
    key: str
    fields: JiraFields


class JiraWebhookPayload(BaseModel):
    """Payload de webhook enviado pelo Jira Service Management."""

    webhook_event: str | None = Field(default=None, alias="webhookEvent")
    timestamp: int | None = None
    issue: JiraIssue
    changelog: dict[str, Any] | None = None
    comment: JiraComment | None = None

    @model_validator(mode="before")
    @classmethod
    def _wrap_direct_issue_payload(cls, value: Any) -> Any:
        """Aceita tanto o envelope de webhook ({'issue': {...}}) quanto o JSON direto da issue Jira ({'id', 'key', 'fields'})."""
        if (
            isinstance(value, dict)
            and "issue" not in value
            and "key" in value
            and "fields" in value
        ):
            issue_id = value.get("id") or value.get("key")
            fields = value.get("fields")
            comment = value.get("comment")
            if comment is None and isinstance(fields, dict):
                comment_block = fields.get("comment")
                if isinstance(comment_block, dict):
                    comments_list = comment_block.get("comments")
                    if isinstance(comments_list, list) and comments_list:
                        comment = comments_list[-1]
            wrapped: dict[str, Any] = {
                "webhookEvent": value.get("webhookEvent"),
                "timestamp": value.get("timestamp"),
                "issue": {
                    "id": issue_id,
                    "key": value["key"],
                    "fields": fields,
                },
            }
            if comment is not None:
                wrapped["comment"] = comment
            return wrapped
        return value

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
