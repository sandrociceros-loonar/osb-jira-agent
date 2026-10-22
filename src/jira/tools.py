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
    phone: str | None = Field(default=None, max_length=100)
    license_count: int | None = Field(default=None, ge=1, le=100000)
    product_root: str | None = Field(default=None, max_length=255)
    request_details: str | None = Field(default=None, max_length=4000)
    domain: str | None = Field(default=None, max_length=255)
    job_title: str | None = Field(default=None, max_length=255)
    lead_source: str | None = Field(default=None, max_length=100)


class ProjectIssueTypeMetadataArguments(ToolArguments):
    project_key: str = Field(min_length=1, max_length=10, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    issue_type_id: str = Field(pattern=r"^\d+$")


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


class SoftwareSearchArguments(ToolArguments):
    software_name: str = Field(min_length=1, max_length=255)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=100)


class UpdateManufacturerArguments(IssueKeyArguments):
    manufacturer_name: str = Field(min_length=1, max_length=255)
    manufacturer_object_id: str | None = Field(
        default=None,
        pattern=r"^\d+$",
        max_length=100,
    )


class ProposalArguments(IssueKeyArguments):
    forecast_date: date
    probability: str = Field(min_length=1, max_length=100)
    next_follow_up_date: date
    priority: str = Field(min_length=1, max_length=100)
    billing: str = Field(min_length=1, max_length=255)
    payment_days: str = Field(min_length=1, max_length=100)
    payment_method: str = Field(min_length=1, max_length=100)
    proposal_valid_until: date | None = None
    proposal_information: str = Field(min_length=1, max_length=4000)


class PurchasingTransitionArguments(IssueKeyArguments):
    product_object_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^\d+$",
        description=(
            "objectId numérico do produto retornado por uma busca no Jira Assets; "
            "não use o ID do fabricante."
        ),
    )
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


class KBQueryArguments(ToolArguments):
    query: str = Field(
        min_length=2,
        max_length=1000,
        description="Dúvida apresentada pelo lead ou URL de link da base de conhecimento (mesmo domínio) a consultar",
    )


class EscalateHumanArguments(IssueKeyArguments):
    reason: str = Field(
        min_length=3,
        max_length=1000,
        description="Motivo do encaminhamento do lead para a equipe humana",
    )
    missing_data_message: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "Texto opcional indicando cordialmente quais dados comerciais faltam para a proposta, "
            "a ser integrado na mesma mensagem enviada ao lead."
        ),
    )


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
        "Cria um lead no projeto configurado usando os metadados Jira e os campos comerciais fornecidos, incluindo contato, telefone, detalhes da solicitação e origem. Requer escrita habilitada.",
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
        "get_project_issue_type_metadata",
        "Consulta metadados de criação do Jira para um projeto e tipo de issue permitidos, incluindo nomes, IDs, tipos, campos obrigatórios e opções disponíveis. Somente leitura.",
        ProjectIssueTypeMetadataArguments,
        "get_project_issue_type_metadata",
    ),
    JiraTool(
        "get_lead_details",
        "Obtém os campos e comentários do lead para verificar dados fornecidos pelo solicitante.",
        IssueKeyArguments,
        "get_lead_details",
    ),
    JiraTool(
        "get_latest_issue_comment",
        "Obtém o comentário mais recente da issue, incluindo autor, data e conteúdo.",
        IssueKeyArguments,
        "get_latest_issue_comment",
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
        "add_public_comment",
        "Adiciona uma mensagem comercial pública sobre o lead/proposta, dirigida ao lead ou contato comercial e possivelmente enviada a ele por e-mail pelo Jira — nunca ao operador Jira. Use sempre tom cordial, natural, profissional e conciso; não inclua detalhes técnicos internos, cabeçalho automático, nome da conta Jira nem assinatura. Requer escrita habilitada.",
        AddCommentArguments,
        "add_public_comment",
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
        "Pesquisa produtos no Jira Assets pelo fabricante, com a consulta AQL escapada. "
        "Retorna o id/objectId numérico de cada produto; use esse identificador como "
        "product_object_id ao chamar send_item_to_purchasing.",
        ProductSearchArguments,
        "search_assets_products_by_manufacturer",
    ),
    JiraTool(
        "search_assets_products_by_software",
        "Pesquisa no Jira Assets o software citado no lead para obter produto e fabricante. "
        "Retorna o id/objectId numérico de cada produto; use esse identificador como "
        "product_object_id ao chamar send_item_to_purchasing.",
        SoftwareSearchArguments,
        "search_assets_products_by_software",
    ),
    JiraTool(
        "update_lead_manufacturer",
        "Atualiza no lead o campo Fabricante/Manufacturer com dados confirmados pelo Jira Assets. Se a configuração de bypass estiver habilitada e o campo estiver indisponível para edição, retorna uma pendência; não considere o fabricante atualizado. Requer escrita habilitada.",
        UpdateManufacturerArguments,
        "update_lead_manufacturer",
        True,
    ),
    JiraTool(
        "send_item_to_purchasing",
        "Preenche os campos de compra e executa a transição do item. "
        "Use product_object_id obtido do resultado de uma busca de produto no Jira Assets. "
        "A ferramenta grava o produto no campo Assets customfield_11828 como uma referência "
        "com workspaceId configurado, id no formato workspaceId:objectId e objectId. "
        "Requer escrita habilitada.",
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
    JiraTool(
        "query_knowledge_base",
        "Pesquisa dúvidas do lead na base de conhecimento do Confluence (com cache RAG e fallback direto em atualização), lendo textos e links do mesmo domínio.",
        KBQueryArguments,
        "query_knowledge_base",
        False,
    ),
    JiraTool(
        "escalate_to_human_group",
        "Encaminha o lead para o grupo de atendimento comercial humano quando a base de conhecimento não contiver resposta suficiente. Requer escrita habilitada.",
        EscalateHumanArguments,
        "escalate_to_human_group",
        True,
    ),
)

JIRA_TOOLS_BY_NAME = {tool.name: tool for tool in JIRA_TOOLS}
