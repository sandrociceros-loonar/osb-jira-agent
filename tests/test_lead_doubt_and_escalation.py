"""Tests for lead doubts handling, Detalhes da Solicitação extraction, and human escalation."""

import json
from unittest.mock import MagicMock

import httpx

from src.agent.prompts import format_triage_user_prompt
from src.config import Settings
from src.jira.connector import JiraConnector
from src.kb.models import KBChunkMatch, KBSearchResult
from src.models.jira_webhook import JiraWebhookPayload


def test_request_details_field_defaults_when_configuration_is_blank():
    settings = Settings(JIRA_REQUEST_DETAILS_FIELD_ID="")
    assert settings.jira_request_details_field_id == "customfield_10120"


def test_request_details_extracted_from_webhook_payload():
    payload_data = {
        "webhookEvent": "jira:issue_created",
        "issue": {
            "id": "9901",
            "key": "OP-9901",
            "fields": {
                "summary": "Novo lead recebido",
                "customfield_10120": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Gostaria de saber se vocês oferecem suporte 24/7 e SLA de atendimento.",
                                }
                            ],
                        }
                    ],
                },
            },
        },
    }

    payload = JiraWebhookPayload.model_validate(payload_data)
    # Com field_id configurado
    extracted = payload.issue.fields.get_request_details_text("customfield_10120")
    assert extracted == "Gostaria de saber se vocês oferecem suporte 24/7 e SLA de atendimento."

    # Com descoberta por chave ou nome
    payload_data2 = {
        "webhookEvent": "jira:issue_created",
        "issue": {
            "id": "9902",
            "key": "OP-9902",
            "fields": {
                "summary": "Lead com detalhes",
                "detalhes_da_solicitacao": "Temos desconto para pagamento anual?",
            },
        },
    }
    payload2 = JiraWebhookPayload.model_validate(payload_data2)
    assert (
        payload2.issue.fields.get_request_details_text() == "Temos desconto para pagamento anual?"
    )


def test_format_triage_user_prompt_includes_request_details():
    prompt = format_triage_user_prompt(
        issue_key="OP-500",
        summary="Cotação de Licenças",
        description="Contato via portal",
        request_details="Dúvida: qual o prazo de entrega das licenças?",
    )
    assert "Detalhes da Solicitação**: Dúvida: qual o prazo de entrega das licenças?" in prompt


def test_jira_connector_get_lead_details_extracts_request_details():
    issue_data = {
        "id": "9901",
        "key": "OP-9901",
        "names": {
            "summary": "Summary",
            "customfield_10120": "Detalhes da Solicitação",
        },
        "fields": {
            "summary": "Lead de Teste",
            "customfield_10120": "Qual a validade das propostas enviadas?",
        },
    }

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=issue_data if "/comment" not in request.url.path else {"comments": []},
            request=request,
        )
    )

    settings = Settings(
        JIRA_INSTANCE_URL="https://test.atlassian.net",
        JIRA_API_EMAIL="test@example.com",
        JIRA_API_TOKEN="token",
        JIRA_REQUEST_DETAILS_FIELD_ID="customfield_10120",
        JIRA_ALLOWED_PROJECT_KEYS=["OP"],
        JIRA_LEAD_PROJECT_KEY="OP",
    )

    with JiraConnector(settings, transport=transport) as connector:
        lead_details = connector.get_lead_details("OP-9901")
        assert lead_details.get("request_details") == "Qual a validade das propostas enviadas?"


def test_jira_connector_query_knowledge_base():
    mock_rag = MagicMock()
    mock_rag.search.return_value = KBSearchResult(
        query="suporte 24/7",
        found=True,
        confidence_score=0.88,
        matches=[
            KBChunkMatch(
                chunk_id="chunk_1",
                title="SLA e Suporte Enterprise",
                url="https://wiki/sla",
                content="Suporte 24/7 disponível em contratos Enterprise.",
                score=0.88,
            )
        ],
        fallback_used=False,
        source="cache",
        message="Artigo relevante encontrado.",
    )

    settings = Settings(
        JIRA_INSTANCE_URL="https://test.atlassian.net",
        JIRA_API_EMAIL="test@example.com",
        JIRA_API_TOKEN="token",
        JIRA_ALLOWED_PROJECT_KEYS=["OP"],
    )

    with JiraConnector(
        settings, transport=httpx.MockTransport(lambda r: httpx.Response(200)), rag_engine=mock_rag
    ) as connector:
        res = connector.execute_tool("query_knowledge_base", {"query": "suporte 24/7"})
        assert res["found"] is True
        assert res["confidence_score"] == 0.88
        assert res["matches"][0]["title"] == "SLA e Suporte Enterprise"
        assert "same_domain_links" in res["matches"][0]
        mock_rag.search.assert_called_once_with("suporte 24/7")


def test_jira_connector_escalate_to_human_group():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/transitions"):
            return httpx.Response(204, request=request)
        if request.url.path.endswith("/comment"):
            return httpx.Response(201, json={"id": "comment-10"}, request=request)
        if request.method == "PUT":
            return httpx.Response(204, request=request)
        return httpx.Response(200, json={}, request=request)

    settings = Settings(
        JIRA_INSTANCE_URL="https://test.atlassian.net",
        JIRA_API_EMAIL="test@example.com",
        JIRA_API_TOKEN="token",
        JIRA_ENABLE_WRITE_OPERATIONS=True,
        JIRA_ALLOWED_PROJECT_KEYS=["OP"],
        KB_HUMAN_ESCALATION_TEAM="Equipe Especialistas Comerciais",
        KB_HUMAN_ESCALATION_GROUP_ACCOUNT_ID="human-group-account-id",
        KB_HUMAN_ESCALATION_TRANSITION_ID="99",
    )

    with JiraConnector(settings, transport=httpx.MockTransport(handler)) as connector:
        result = connector.execute_tool(
            "escalate_to_human_group",
            {
                "issue_key": "OP-500",
                "reason": "Dúvida específica não consta na base de conhecimento",
                "missing_data_message": "forma de pagamento e prazo de faturamento",
            },
        )

        assert result["escalated"] is True
        assert result["team"] == "Equipe Especialistas Comerciais"
        assert len(result["actions"]) >= 3

        # Verifica se houve chamada PUT para atribuição
        put_requests = [r for r in requests if r.method == "PUT"]
        assert len(put_requests) == 1
        put_payload = json.loads(put_requests[0].content)
        assert put_payload["fields"]["assignee"]["accountId"] == "human-group-account-id"

        # Verifica se houve chamada POST da transição Mensagem para o Cliente (ID 36 / customfield_15195) informando o lead cordialmente como humano e pedindo dados
        transition_posts = [
            r for r in requests if r.method == "POST" and r.url.path.endswith("/transitions")
        ]
        assert len(transition_posts) >= 1
        customer_msg_payload = json.loads(transition_posts[-1].content)
        assert customer_msg_payload["transition"]["id"] == "36"
        public_comment_body = customer_msg_payload["fields"]["customfield_15195"]
        assert "logo mais entrarei em contato" in public_comment_body
        assert "forma de pagamento e prazo de faturamento" in public_comment_body
        assert "inteligência artificial" not in public_comment_body.lower()
        assert "agente de ia" not in public_comment_body.lower()


def test_triage_prompt_includes_non_repetition_and_lead_work_rules():
    from src.agent.prompts import TRIAGE_SYSTEM_PROMPT

    assert "REGRA DE NÃO REPETIÇÃO" in TRIAGE_SYSTEM_PROMPT
    assert "start_lead_work" in TRIAGE_SYSTEM_PROMPT
    assert "respostas breves do lead" in TRIAGE_SYSTEM_PROMPT
    assert "não consulte a base de conhecimento novamente" in TRIAGE_SYSTEM_PROMPT.lower()
