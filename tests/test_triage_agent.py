"""Tests for Triage Agent parsing and logic."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.agent.prompts import TRIAGE_SYSTEM_PROMPT, format_triage_user_prompt
from src.agent.triage_agent import JiraTriageAgent
from src.models.agent_result import TriageCategory, TriagePriority
from src.models.jira_webhook import JiraWebhookPayload


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
    assert mock_client.responses.create.call_args.kwargs["model"] == agent.settings.azure_ai_model_deployment_name


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
):
    agent = JiraTriageAgent()
    agent.settings.model_provider = provider
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

    with patch.object(agent.foundry_manager, "get_openai_client", return_value=mock_client):
        with patch(
            "src.agent.triage_agent.get_jira_connector",
            return_value=jira_connector,
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
