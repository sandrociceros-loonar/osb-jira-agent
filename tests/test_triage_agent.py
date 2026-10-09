"""Tests for Triage Agent parsing and logic."""

from unittest.mock import MagicMock, patch

from src.agent.triage_agent import JiraTriageAgent
from src.models.agent_result import TriageCategory, TriagePriority
from src.models.jira_webhook import JiraWebhookPayload


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


def test_parse_decision_fallback_on_invalid_json():
    """Testa recuperação graciosa com fallback em caso de saída não-JSON."""
    agent = JiraTriageAgent()
    raw_response = "Não foi possível formatar em JSON devido a erro de conexão."
    decision = agent.parse_decision_from_text(raw_response)

    assert decision.category == TriageCategory.GENERAL_SUPPORT
    assert decision.priority == TriagePriority.MEDIUM
    assert decision.assigned_team == "ServiceDesk-L1"


def test_process_ticket_end_to_end_mocked(sample_outage_webhook_payload):
    """Testa fluxo completo de processamento com mocks do SDK do Azure AI Projects."""
    agent = JiraTriageAgent()
    payload = JiraWebhookPayload.model_validate(sample_outage_webhook_payload)

    mock_client = MagicMock()
    mock_agent_obj = MagicMock(id="agent-xyz", name="osb-jira-triage-agent")
    mock_thread_obj = MagicMock(id="thread-abc")
    mock_run_obj = MagicMock(id="run-123")

    mock_message_text = MagicMock(
        value="""{
        "category": "Infrastructure & Cloud",
        "priority": "Highest",
        "assigned_team": "Cloud-Platform",
        "suggested_status": "In Progress",
        "should_auto_close": false,
        "reasoning": "Produção fora do ar",
        "internal_comment": "Triado automaticamente"
    }"""
    )
    mock_content_block = MagicMock(text=mock_message_text)
    mock_assistant_msg = MagicMock(role="assistant", content=[mock_content_block])
    mock_messages_list = MagicMock(data=[mock_assistant_msg])

    mock_client.agents.list_agents.return_value = MagicMock(data=[mock_agent_obj])
    mock_client.agents.create_thread.return_value = mock_thread_obj
    mock_client.agents.create_and_process_run.return_value = mock_run_obj
    mock_client.agents.list_messages.return_value = mock_messages_list

    with patch.object(agent.foundry_manager, "get_client", return_value=mock_client):
        result = agent.process_ticket(payload)

    assert result.success is True
    assert result.issue_key == "ITSM-101"
    assert result.decision is not None
    assert result.decision.category == TriageCategory.INFRASTRUCTURE
    assert result.decision.priority == TriagePriority.HIGHEST
    assert "Cloud-Platform" in result.decision.assigned_team
    assert result.thread_id == "thread-abc"
    assert result.run_id == "run-123"
