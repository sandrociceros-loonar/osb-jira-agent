"""Typed function tools corresponding to the Jira operation manifests."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolArguments(BaseModel):
    """Common validation for model-supplied Jira tool arguments."""

    model_config = ConfigDict(extra="forbid")


class IssueKeyArguments(ToolArguments):
    issue_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]*-\d+$")


class CreateLeadArguments(ToolArguments):
    summary: str = Field(min_length=1, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    license_count: int | None = Field(default=None, ge=1, le=100000)
    product_root: str | None = Field(default=None, max_length=255)
    lead_source: str | None = Field(default=None, max_length=100)


class AttachmentArguments(IssueKeyArguments):
    attachment_id: str = Field(pattern=r"^\d+$")


class AssetsSchemaListArguments(ToolArguments):
    start_at: int = Field(default=0, ge=0)
    max_results: int = Field(default=50, ge=1, le=100)
    include_counts: bool = False


class AssetsObjectTypesArguments(ToolArguments):
    objectschema_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class ProductSearchArguments(ToolArguments):
    manufacturer: str = Field(min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=100)


class ProposalArguments(IssueKeyArguments):
    forecast_date: date | None = None
    probability: str | None = Field(default=None, max_length=100)
    next_follow_up_date: date | None = None
    priority: str | None = Field(default=None, max_length=100)
    billing: str | None = Field(default=None, max_length=255)
    payment_days: str | None = Field(default=None, max_length=100)
    payment_method: str | None = Field(default=None, max_length=100)
    proposal_valid_until: date | None = None
    proposal_information: str | None = Field(default=None, max_length=4000)


class PurchasingTransitionArguments(IssueKeyArguments):
    product_object_id: str = Field(min_length=1, max_length=100, pattern=r"^\d+$")
    quantity: int = Field(ge=1, le=100000)
    quotation_classification: str = Field(min_length=1, max_length=100)
    period_months: str = Field(min_length=1, max_length=100)
    price_type: str = Field(min_length=1, max_length=100)
    reference: str = Field(default="-", max_length=255)


class SetPriceArguments(IssueKeyArguments):
    unit_price: float = Field(ge=0, le=1000000000)
    likely_scenario: bool


class AddCommentArguments(IssueKeyArguments):
    comment: str = Field(min_length=1, max_length=10000)


@dataclass(frozen=True)
class JiraTool:
    """One model-callable operation with its argument model and connector handler."""

    name: str
    description: str
    arguments_model: type[ToolArguments]
    handler_name: str
    write_operation: bool = False

    def function_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.arguments_model.model_json_schema(),
        }


JIRA_TOOLS: tuple[JiraTool, ...] = (
    JiraTool(
        "create_lead",
        "Cria um lead no projeto configurado com os campos fornecidos. Requer escrita habilitada.",
        CreateLeadArguments,
        "create_lead",
        True,
    ),
    JiraTool(
        "get_issue_fields",
        "Obtém todos os campos, nomes, metadados de edição e transições disponíveis de uma issue.",
        IssueKeyArguments,
        "get_issue_fields",
    ),
    JiraTool(
        "get_lead_details",
        "Obtém os campos e comentários definidos no manifesto de consulta de lead.",
        IssueKeyArguments,
        "get_lead_details",
    ),
    JiraTool(
        "start_lead_work",
        "Transiciona um lead para iniciar o trabalho e define a classificação de licença. Requer escrita habilitada.",
        IssueKeyArguments,
        "start_lead_work",
        True,
    ),
    JiraTool(
        "transition_lead_to_proposal_item",
        "Transiciona um lead para a etapa de item da proposta. Requer escrita habilitada.",
        IssueKeyArguments,
        "transition_lead_to_proposal_item",
        True,
    ),
    JiraTool(
        "find_proposal_items",
        "Pesquisa issues filhas da issue de lead indicada.",
        IssueKeyArguments,
        "find_proposal_items",
    ),
    JiraTool(
        "generate_new_proposal",
        "Atualiza os campos da proposta e executa a transição correspondente. Requer escrita habilitada.",
        ProposalArguments,
        "generate_new_proposal",
        True,
    ),
    JiraTool(
        "list_issue_attachments",
        "Lista metadados dos anexos de uma issue.",
        IssueKeyArguments,
        "list_issue_attachments",
    ),
    JiraTool(
        "download_issue_attachment",
        "Obtém o conteúdo Base64 de um anexo pertencente à issue; limitado pelo tamanho configurado.",
        AttachmentArguments,
        "download_issue_attachment",
    ),
    JiraTool(
        "add_internal_comment",
        "Adiciona uma nota interna, nunca pública, à issue. Requer escrita habilitada.",
        AddCommentArguments,
        "add_internal_comment",
        True,
    ),
    JiraTool(
        "list_assets_schemas",
        "Lista os object schemas do Jira Assets, com paginação opcional.",
        AssetsSchemaListArguments,
        "list_assets_schemas",
    ),
    JiraTool(
        "get_assets_object_types",
        "Lista os object types de um object schema do Jira Assets.",
        AssetsObjectTypesArguments,
        "get_assets_object_types",
    ),
    JiraTool(
        "get_assets_cloud_id",
        "Obtém o Cloud ID da instância Jira configurada.",
        ToolArguments,
        "get_assets_cloud_id",
    ),
    JiraTool(
        "get_assets_workspaces",
        "Lista os workspaces do Jira Assets da instância configurada.",
        ToolArguments,
        "get_assets_workspaces",
    ),
    JiraTool(
        "search_assets_products_by_manufacturer",
        "Pesquisa produtos no Jira Assets pelo fabricante, com a consulta AQL escapada.",
        ProductSearchArguments,
        "search_assets_products_by_manufacturer",
    ),
    JiraTool(
        "send_item_to_purchasing",
        "Preenche os campos de compra e executa a transição do item. Requer escrita habilitada.",
        PurchasingTransitionArguments,
        "send_item_to_purchasing",
        True,
    ),
    JiraTool(
        "get_proposal_item_values",
        "Obtém status, campos selecionados e metadados de edição do item da proposta.",
        IssueKeyArguments,
        "get_proposal_item_values",
    ),
    JiraTool(
        "set_proposal_item_price",
        "Define preço unitário e cenário provável no item. Requer escrita habilitada.",
        SetPriceArguments,
        "set_proposal_item_price",
        True,
    ),
)

JIRA_TOOLS_BY_NAME = {tool.name: tool for tool in JIRA_TOOLS}
