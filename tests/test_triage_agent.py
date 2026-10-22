"""Tests for Triage Agent parsing and logic."""

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from src.agent.prompts import TRIAGE_SYSTEM_PROMPT, format_triage_user_prompt
from src.agent.triage_agent import JiraTriageAgent
from src.jira.tools import JIRA_TOOLS
from src.models.agent_result import TriageCategory, TriagePriority
from src.models.jira_webhook import JiraWebhookPayload


def test_jira_tool_execution_emits_trace_without_recording_payload():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    connector = MagicMock()
    connector.execute_tool.return_value = {"key": "OP-101", "summary": "Private lead"}

    with patch("src.agent.triage_agent.tracer", provider.get_tracer("test")):
        result = JiraTriageAgent._execute_jira_tool(
            connector,
            "get_issue_fields",
            {"issue_key": "OP-101"},
        )

    span = exporter.get_finished_spans()[0]
    provider.shutdown()

    assert result == {"key": "OP-101", "summary": "Private lead"}
    assert span.name == "jira.execute_tool"
    assert span.attributes == {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": "get_issue_fields",
    }


def test_generate_proposal_runs_when_manufacturer_field_update_is_pending():
    connector = MagicMock()
    connector.manufacturer_update_pending = True
    connector.execute_tool.return_value = {"success": True, "issue_key": "OP-101"}

    result = JiraTriageAgent._execute_jira_tool(
        connector,
        "generate_new_proposal",
        {"issue_key": "OP-101"},
    )

    assert result == {"success": True, "issue_key": "OP-101"}
    connector.execute_tool.assert_called_once_with(
        "generate_new_proposal",
        {"issue_key": "OP-101"},
    )


def test_commercial_prompt_does_not_block_on_manufacturer_field_or_reconfirm_proposal():
    assert "nunca é pré-requisito" in TRIAGE_SYSTEM_PROMPT
    assert "continue o fluxo comercial" in TRIAGE_SYSTEM_PROMPT
    assert "não peça confirmação redundante" in TRIAGE_SYSTEM_PROMPT
    assert "mesmo quando os campos da issue ainda estiverem vazios ou desatualizados" in (
        TRIAGE_SYSTEM_PROMPT
    )
    assert "não peça novamente uma informação que já foi fornecida" in TRIAGE_SYSTEM_PROMPT
    assert (
        "Considere um dado confirmado se foi explicitamente informado pelo lead em qualquer comentário"
        in (TRIAGE_SYSTEM_PROMPT)
    )
    assert "geração de proposta bloqueada" not in TRIAGE_SYSTEM_PROMPT
    assert "questione o cliente cordialmente na mensagem se deve prosseguir" not in (
        TRIAGE_SYSTEM_PROMPT
    )


def test_failed_jira_tool_execution_marks_trace_without_recording_exception():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    connector = MagicMock()
    connector.execute_tool.side_effect = ValueError("sensitive Jira response")

    with (
        patch("src.agent.triage_agent.tracer", provider.get_tracer("test")),
        pytest.raises(ValueError, match="sensitive Jira response"),
    ):
        JiraTriageAgent._execute_jira_tool(connector, "get_issue_fields", {})

    span = exporter.get_finished_spans()[0]
    provider.shutdown()

    assert span.status.status_code == StatusCode.ERROR
    assert span.events == ()


def test_webhook_comment_adf_is_extracted_as_readable_text():
    payload = JiraWebhookPayload.model_validate(
        {
            "webhookEvent": "comment_created",
            "issue": {
                "id": "1",
                "key": "OP-1",
                "fields": {"summary": "Lead"},
            },
            "comment": {
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Pagamento em 30 dias"}],
                        },
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Vigência anual"}],
                        },
                    ],
                }
            },
        }
    )

    assert payload.comment is not None
    assert payload.comment.get_body_text() == "Pagamento em 30 dias\nVigência anual"


def test_commercial_prompt_uses_crm_purpose_and_safe_defaults():
    user_prompt = format_triage_user_prompt(
        issue_key="OP-101",
        summary="Proposta de renovação",
        description="Solicitação comercial",
        current_status="Em andamento",
        issue_type="Lead",
    )

    assert "Agente Comercial de CRM" in TRIAGE_SYSTEM_PROMPT
    assert "não incidentes" in TRIAGE_SYSTEM_PROMPT
    assert (
        '"category": "<Lead | Proposta | Item da proposta | Consulta comercial | Produto/Compras>"'
        in TRIAGE_SYSTEM_PROMPT
    )
    assert "salvo se o usuário pedir explicitamente sua alteração" in TRIAGE_SYSTEM_PROMPT
    assert "registro comercial do Jira" in user_prompt
    assert "Proposta de renovação" in user_prompt


def test_purchasing_prompt_maps_assets_product_id_to_jira_assets_field():
    purchasing_tool = next(tool for tool in JIRA_TOOLS if tool.name == "send_item_to_purchasing")
    product_id_schema = purchasing_tool.function_schema()["parameters"]["properties"][
        "product_object_id"
    ]

    assert "customfield_11828" in TRIAGE_SYSTEM_PROMPT
    assert "`<workspaceId>:<objectId>`" in TRIAGE_SYSTEM_PROMPT
    assert "workspaceId:objectId" in purchasing_tool.description
    assert "customfield_12345" in TRIAGE_SYSTEM_PROMPT
    assert "objectId numérico do produto" in product_id_schema["description"]
    assert "id/objectId numérico" in next(
        tool.description for tool in JIRA_TOOLS if tool.name == "search_assets_products_by_software"
    )


def test_commercial_prompt_includes_custom_fields_from_webhook():
    user_prompt = format_triage_user_prompt(
        issue_key="OP-8885",
        summary="Novo Lead do Site - Anydesk",
        description="Cenário somente leitura.",
        custom_fields={
            "customfield_10119": "Anydesk",
            "customfield_10143": {"id": "11102", "value": "Site"},
        },
    )

    assert "snapshot do evento" in user_prompt
    assert '"customfield_10119": "Anydesk"' in user_prompt
    assert '"customfield_10143": {"id": "11102", "value": "Site"}' in user_prompt


def test_public_lead_comment_is_not_addressed_to_the_jira_operator():
    user_prompt = format_triage_user_prompt(
        issue_key="OP-101",
        summary="Nova oportunidade",
        description="Produto: Acme Suite",
        reporter="Operador do Jira",
        issue_type="Lead",
    )

    assert "dirigida ao lead/contato comercial" in TRIAGE_SYSTEM_PROMPT
    assert "nunca escreva ao operador/usuário Jira" in TRIAGE_SYSTEM_PROMPT
    assert "nunca o trate como destinatário" in TRIAGE_SYSTEM_PROMPT
    assert (
        "Use saudação com nome somente se o nome do lead/contato estiver claramente identificado"
        in (TRIAGE_SYSTEM_PROMPT)
    )
    assert "Operador do Jira" in user_prompt
    assert "contexto operacional, não destinatário do comentário" in user_prompt
    assert "get_issue_fields" in TRIAGE_SYSTEM_PROMPT
    assert "não execute ferramentas de escrita nem transições" in TRIAGE_SYSTEM_PROMPT


def test_all_public_lead_comments_use_customer_facing_commercial_tone():
    assert "todo comentário publicado por `add_public_comment`" in TRIAGE_SYSTEM_PROMPT
    assert "sua proposta ou item relacionado" in TRIAGE_SYSTEM_PROMPT
    assert "pedidos de dados ou esclarecimentos, ambiguidades e pendências" in (
        TRIAGE_SYSTEM_PROMPT
    )
    assert "falhas operacionais, atualizações de andamento e confirmação de conclusão" in (
        TRIAGE_SYSTEM_PROMPT
    )
    assert "cordial, natural, profissional e comercial" in TRIAGE_SYSTEM_PROMPT
    assert "não exponha detalhes técnicos internos" in TRIAGE_SYSTEM_PROMPT
    public_comment_tool = next(tool for tool in JIRA_TOOLS if tool.name == "add_public_comment")
    assert "possivelmente enviada a ele por e-mail pelo Jira" in public_comment_tool.description
    assert "nunca ao operador Jira" in public_comment_tool.description


def test_lead_prompt_includes_webhook_event_and_new_requester_comment():
    user_prompt = format_triage_user_prompt(
        issue_key="OP-101",
        summary="Nova oportunidade",
        description="Produto: Acme Suite",
        issue_type="Lead",
        webhook_event="comment_created",
        incoming_comment="Pagamento em 30 dias.",
    )

    assert "comment_created" in user_prompt
    assert "Novo comentário recebido" in user_prompt
    assert "Pagamento em 30 dias." in user_prompt


def test_lead_doubt_human_escalation_rules_in_prompt():
    assert "query_knowledge_base" in TRIAGE_SYSTEM_PROMPT
    assert "escalate_to_human_group" in TRIAGE_SYSTEM_PROMPT
    assert "como uma pessoa da equipe comercial humana" in TRIAGE_SYSTEM_PROMPT
    assert "nunca cite ou dê a entender que é um agente de IA" in TRIAGE_SYSTEM_PROMPT
    assert "logo mais entrará em contato" in TRIAGE_SYSTEM_PROMPT
    assert "não peça confirmação redundante" in TRIAGE_SYSTEM_PROMPT
    assert "reitere cordialmente o pedido dos dados que ainda faltam" in TRIAGE_SYSTEM_PROMPT


def test_proposal_validity_license_orientation_and_offline_prompt_rules():
    from src.agent.prompts import SNAPSHOT_OFFLINE_SYSTEM_PROMPT

    assert "PRAZO DE VALIDADE AUTOMÁTICO" in TRIAGE_SYSTEM_PROMPT
    assert "NÃO precisa ser incluído pelo agente nem solicitado ao lead" in TRIAGE_SYSTEM_PROMPT
    assert "ENVIO AUTOMÁTICO PELO JIRA" in TRIAGE_SYSTEM_PROMPT
    assert "E-MAIL INFORMATIVO PRÉVIO" in TRIAGE_SYSTEM_PROMPT
    assert "TRATAMENTO DE PROBLEMAS NA GERAÇÃO" in TRIAGE_SYSTEM_PROMPT
    assert "direcionar o lead para os agentes humanos" in TRIAGE_SYSTEM_PROMPT
    assert "ORIENTAÇÃO DE LICENÇA OBRIGATÓRIA" in TRIAGE_SYSTEM_PROMPT
    assert "ANTECIPAÇÃO DA COLETA DE DADOS DA PROPOSTA" in TRIAGE_SYSTEM_PROMPT
    assert "REITERAÇÃO E COBRANÇA CONTÍNUA" in TRIAGE_SYSTEM_PROMPT
    assert "Você é um Agente Comercial de CRM da Loonar." in SNAPSHOT_OFFLINE_SYSTEM_PROMPT
    assert "sem utilizar ferramentas externas" in SNAPSHOT_OFFLINE_SYSTEM_PROMPT


def test_parse_decision_from_clean_json():
    """Testa parse de resposta JSON limpa do agente."""
    agent = JiraTriageAgent()
    raw_response = """
    {
        "category": "Infrastructure & Cloud",
        "priority": "Highest",
        "assigned_team": "Cloud-Platform",
        "suggested_status": "In Progress",
        "should_auto_close": false,
        "reasoning": "Servidor de produção inacessível, causando indisponibilidade crítica no checkout.",
        "internal_comment": "Triagem automática: Incidente P1 atribuído à equipe Cloud-Platform."
    }
    """
    decision = agent.parse_decision_from_text(raw_response)
    assert decision.category == TriageCategory.INFRASTRUCTURE
    assert decision.priority == TriagePriority.HIGHEST
    assert decision.assigned_team == "Cloud-Platform"
    assert decision.suggested_status == "In Progress"
    assert decision.should_auto_close is False


def test_parse_commercial_decision_without_legacy_triage_updates():
    agent = JiraTriageAgent()
    decision = agent.parse_decision_from_text(
        """{
            "category": "Lead",
            "priority": null,
            "assigned_team": null,
            "suggested_status": null,
            "should_auto_close": false,
            "reasoning": "Lead consultado sem necessidade de alteração.",
            "internal_comment": null
        }"""
    )

    assert decision.category == TriageCategory.LEAD
    assert decision.priority is None
    assert decision.assigned_team is None
    assert decision.suggested_status is None
    assert decision.should_auto_close is False


def test_parse_decision_with_markdown_fences():
    """Testa parse de resposta envolta em blocos markdown ```json ... ```."""
    agent = JiraTriageAgent()
    raw_response = """Aqui está o parecer de triagem:
    ```json
    {
        "category": "Access & Permissions",
        "priority": "Medium",
        "assigned_team": "SecOps-IAM",
        "suggested_status": "Waiting for Approval",
        "should_auto_close": false,
        "reasoning": "Solicitação de acesso à VPN corporativa requer validação de identidade.",
        "internal_comment": "Triagem automática: Chamado direcionado à fila de autorização SecOps-IAM."
    }
    ```
    """
    decision = agent.parse_decision_from_text(raw_response)
    assert decision.category == TriageCategory.ACCESS_MANAGEMENT
    assert decision.priority == TriagePriority.MEDIUM
    assert decision.assigned_team == "SecOps-IAM"


def test_parse_decision_rejects_invalid_json():
    """Impede que uma resposta inválida cause alterações com uma triagem padrão."""
    agent = JiraTriageAgent()
    raw_response = "Não foi possível formatar em JSON devido a erro de conexão."

    with pytest.raises(ValueError, match="resultado comercial válido"):
        agent.parse_decision_from_text(raw_response)


def test_process_ticket_end_to_end_mocked(sample_outage_webhook_payload):
    """Testa o fluxo de Responses API com o endpoint de projeto do Foundry."""
    sample_outage_webhook_payload["issue"]["fields"]["customfield_10119"] = "Anydesk"
    agent = JiraTriageAgent()
    payload = JiraWebhookPayload.model_validate(sample_outage_webhook_payload)
    mock_client = MagicMock()
    mock_client.responses.create.return_value = SimpleNamespace(
        id="response-123",
        output=[],
        output_text="""{
        "category": "Infrastructure & Cloud",
        "priority": "Highest",
        "assigned_team": "Cloud-Platform",
        "suggested_status": "In Progress",
        "should_auto_close": false,
        "reasoning": "Produção fora do ar",
        "internal_comment": "Triado automaticamente"
    }""",
    )

    with patch.object(agent.foundry_manager, "get_openai_client", return_value=mock_client):
        with patch("src.agent.triage_agent.get_jira_connector", return_value=None):
            result = agent.process_ticket(payload)

    assert result.success is True
    assert result.issue_key == "ITSM-101"
    assert result.decision is not None
    assert result.decision.category == TriageCategory.INFRASTRUCTURE
    assert result.decision.priority == TriagePriority.HIGHEST
    assert "Cloud-Platform" in result.decision.assigned_team
    assert result.thread_id is None
    assert result.run_id == "response-123"
    mock_client.responses.create.assert_called_once()
    assert (
        mock_client.responses.create.call_args.kwargs["model"]
        == agent.settings.azure_ai_model_deployment_name
    )
    assert (
        '"customfield_10119": "Anydesk"' in mock_client.responses.create.call_args.kwargs["input"]
    )


def test_process_ticket_applies_decision_with_jira_connector(sample_outage_webhook_payload):
    """Aplica a decisão ao Jira quando o conector está configurado."""
    agent = JiraTriageAgent()
    agent.settings.jira_allow_write_operations = True
    payload = JiraWebhookPayload.model_validate(sample_outage_webhook_payload)
    mock_client = MagicMock()
    mock_client.responses.create.return_value = SimpleNamespace(
        id="response-123",
        output=[],
        output_text="""{
        "category": "Infrastructure & Cloud",
        "priority": "Highest",
        "assigned_team": "Cloud-Platform",
        "should_auto_close": false,
        "reasoning": "Produção fora do ar",
        "internal_comment": "Incidente crítico encaminhado."
    }""",
    )
    jira_connector = MagicMock()
    jira_connector.available_tool_schemas.return_value = []
    jira_connector.apply_decision.return_value = ["Prioridade atualizada no Jira."]

    with patch.object(agent.foundry_manager, "get_openai_client", return_value=mock_client):
        with patch(
            "src.agent.triage_agent.get_jira_connector",
            return_value=jira_connector,
        ):
            result = agent.process_ticket(payload)

    assert result.success is True
    jira_connector.__enter__.assert_called_once()
    jira_connector.apply_decision.assert_called_once()
    jira_connector.__exit__.assert_called_once()
    assert "Prioridade atualizada no Jira." in result.actions_taken


def test_process_ticket_skips_agent_created_comment(sample_outage_webhook_payload):
    payload_data = sample_outage_webhook_payload
    payload_data["webhookEvent"] = "comment_created"
    payload_data["issue"]["key"] = "OP-101"
    payload_data["issue"]["fields"]["issuetype"] = {"id": "12716", "name": "Lead"}
    payload_data["comment"] = {
        "id": "comment-1",
        "body": "Loonar - Agente Comercial (resposta automática)\n\nDados pendentes.",
        "author": {"accountId": "automation-account"},
    }
    agent = JiraTriageAgent()
    payload = JiraWebhookPayload.model_validate(payload_data)
    mock_client = MagicMock()

    with patch.object(agent.foundry_manager, "get_openai_client", return_value=mock_client):
        with patch("src.agent.triage_agent.get_jira_connector") as get_connector:
            result = agent.process_ticket(payload)

    assert result.success is True
    assert result.decision is None
    assert "Evento ignorado" in result.actions_taken[0]
    get_connector.assert_not_called()
    mock_client.responses.create.assert_not_called()


def test_process_ticket_skips_duplicate_lead_event_after_agent_comment(
    sample_outage_webhook_payload,
):
    payload_data = sample_outage_webhook_payload
    payload_data["issue"]["key"] = "OP-101"
    payload_data["issue"]["fields"]["issuetype"] = {"id": "12716", "name": "Lead"}
    agent = JiraTriageAgent()
    payload = JiraWebhookPayload.model_validate(payload_data)
    mock_client = MagicMock()
    jira_connector = MagicMock()
    jira_connector.get_latest_issue_comment.return_value = {
        "latest_comment": {
            "body": "Loonar - Agente Comercial (resposta automática)\n\nAinda faltam dados.",
            "author": {"accountId": "automation-account"},
        }
    }

    with patch.object(agent.foundry_manager, "get_openai_client", return_value=mock_client):
        with patch(
            "src.agent.triage_agent.get_jira_connector",
            return_value=jira_connector,
        ):
            result = agent.process_ticket(payload)

    assert result.success is True
    assert result.decision is None
    assert "Evento ignorado" in result.actions_taken[0]
    jira_connector.get_latest_issue_comment.assert_called_once_with("OP-101")
    mock_client.responses.create.assert_not_called()


def test_process_ticket_skips_prefixless_comment_by_authenticated_jira_user(
    sample_outage_webhook_payload,
):
    payload_data = sample_outage_webhook_payload
    payload_data["issue"]["key"] = "OP-101"
    payload_data["issue"]["fields"]["issuetype"] = {"id": "12716", "name": "Lead"}
    payload = JiraWebhookPayload.model_validate(payload_data)
    agent = JiraTriageAgent()
    mock_client = MagicMock()
    jira_connector = MagicMock()
    latest_comment = {
        "body": "Olá, Maria! Poderia nos informar a data prevista?",
        "author": {"accountId": "connected-account"},
    }
    jira_connector.get_latest_issue_comment.return_value = {"latest_comment": latest_comment}
    jira_connector.is_authenticated_user_comment.return_value = True

    with patch.object(agent.foundry_manager, "get_openai_client", return_value=mock_client):
        with patch(
            "src.agent.triage_agent.get_jira_connector",
            return_value=jira_connector,
        ):
            result = agent.process_ticket(payload)

    assert result.success is True
    assert result.decision is None
    assert "Evento ignorado" in result.actions_taken[0]
    jira_connector.is_authenticated_user_comment.assert_called_once_with(latest_comment)
    mock_client.responses.create.assert_not_called()


def test_process_ticket_executes_manifest_tool_calls(sample_outage_webhook_payload):
    """Executa uma ferramenta allowlisted e envia o resultado de volta ao modelo."""
    agent = JiraTriageAgent()
    payload = JiraWebhookPayload.model_validate(sample_outage_webhook_payload)
    function_call = SimpleNamespace(
        type="function_call",
        name="get_issue_fields",
        call_id="call-1",
        arguments='{"issue_key":"ITSM-101"}',
    )
    function_response = SimpleNamespace(id="response-tools", output=[function_call])
    final_response = SimpleNamespace(
        id="response-final",
        output=[],
        output_text="""{
            "category": "Infrastructure & Cloud",
            "priority": "Highest",
            "assigned_team": "Cloud-Platform",
            "should_auto_close": false,
            "reasoning": "Produção fora do ar",
            "internal_comment": "Triagem concluída"
        }""",
    )
    mock_client = MagicMock()
    mock_client.responses.create.side_effect = [function_response, final_response]
    jira_connector = MagicMock()
    jira_connector.available_tool_schemas.return_value = [
        {"type": "function", "name": "get_issue_fields"}
    ]
    jira_connector.execute_tool.return_value = {"key": "ITSM-101"}

    with patch.object(agent.foundry_manager, "get_openai_client", return_value=mock_client):
        with patch(
            "src.agent.triage_agent.get_jira_connector",
            return_value=jira_connector,
        ):
            result = agent.process_ticket(payload)

    assert result.success is True
    jira_connector.execute_tool.assert_called_once_with(
        "get_issue_fields",
        {"issue_key": "ITSM-101"},
    )
    follow_up = mock_client.responses.create.call_args_list[1].kwargs
    assert follow_up["previous_response_id"] == "response-tools"
    assert follow_up["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": '{"key": "ITSM-101"}',
        }
    ]
    assert "Ferramenta Jira executada: get_issue_fields." in result.actions_taken


@pytest.mark.parametrize(
    ("provider", "model_name"),
    [("foundry-local", "phi-4-mini"), ("ollama", "qwen3:4b")],
)
def test_local_provider_runs_chat_completions_tool_cycle(
    sample_outage_webhook_payload,
    provider,
    model_name,
    caplog,
):
    agent = JiraTriageAgent()
    agent.settings.model_provider = provider
    agent.settings.log_level = "DEBUG"
    agent.settings.jira_debug_log_content = True
    agent.settings.jira_debug_log_content_issue_key = "ITSM-101"
    agent.settings.jira_debug_log_content_until = datetime.now(UTC) + timedelta(minutes=5)
    if provider == "ollama":
        agent.settings.ollama_model_name = model_name
    else:
        agent.settings.foundry_local_model_alias = model_name
    payload = JiraWebhookPayload.model_validate(sample_outage_webhook_payload)
    assistant_message = SimpleNamespace(
        tool_calls=[
            SimpleNamespace(
                id="call-local-1",
                function=SimpleNamespace(
                    name="get_issue_fields",
                    arguments='{"issue_key":"ITSM-101"}',
                ),
            )
        ],
        content=None,
        model_dump=lambda exclude_none: {
            "role": "assistant",
            "tool_calls": [{"id": "call-local-1"}],
        },
    )
    final_message = SimpleNamespace(
        tool_calls=None,
        content="""{
            "category": "Lead",
            "priority": null,
            "assigned_team": null,
            "should_auto_close": false,
            "reasoning": "Consulta comercial concluída",
            "internal_comment": null
        }""",
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        SimpleNamespace(choices=[SimpleNamespace(message=assistant_message)]),
        SimpleNamespace(
            id="local-response-final",
            choices=[SimpleNamespace(message=final_message)],
        ),
    ]
    jira_connector = MagicMock()
    jira_connector.available_tool_schemas.return_value = [
        {
            "type": "function",
            "name": "get_issue_fields",
            "description": "Obtém campos da issue.",
            "parameters": {"type": "object"},
        }
    ]
    jira_connector.execute_tool.return_value = {"key": "ITSM-101"}

    with (
        caplog.at_level(logging.DEBUG, logger="triage-agent"),
        patch.object(agent.foundry_manager, "get_openai_client", return_value=mock_client),
        patch(
            "src.agent.triage_agent.get_jira_connector",
            return_value=jira_connector,
        ),
    ):
        result = agent.process_ticket(payload)

    assert result.success is True
    first_request = mock_client.chat.completions.create.call_args_list[0].kwargs
    assert first_request["model"] == model_name
    if provider == "ollama":
        assert first_request["extra_body"] == {"think": False}
        assert first_request["max_tokens"] == 1024
    assert result.run_id == "local-response-final"
    jira_connector.execute_tool.assert_called_once_with(
        "get_issue_fields",
        {"issue_key": "ITSM-101"},
    )
    assert '"stage": "model_input"' in caplog.text
    assert '"stage": "model_request"' in caplog.text
    assert '"stage": "model_response"' in caplog.text
    assert '"stage": "tool_call"' in caplog.text
    assert '"stage": "tool_result"' in caplog.text
    calls = mock_client.chat.completions.create.call_args_list
    assert calls[0].kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_issue_fields",
                "description": "Obtém campos da issue.",
                "parameters": {"type": "object"},
            },
        }
    ]
    assert calls[1].kwargs["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "call-local-1",
        "content": '{"key": "ITSM-101"}',
    }
