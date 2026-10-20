"""Tests for Jira Service Management API integration."""

import json

import httpx
import pytest
from pydantic import ValidationError

from src.config import Settings
from src.jira.connector import JiraConnector, JiraConnectorError, get_jira_connector
from src.jira.tools import JIRA_TOOLS, ProposalArguments
from src.models.agent_result import TriageCategory, TriageDecision, TriagePriority


def jira_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "JIRA_INSTANCE_URL": "https://example.atlassian.net",
        "JIRA_API_EMAIL": "agent@example.com",
        "JIRA_API_TOKEN": "local-test-token",
        "JIRA_TEAM_ACCOUNT_IDS": {"Cloud-Platform": "account-123"},
        "JIRA_ENABLE_WRITE_OPERATIONS": True,
        "JIRA_ALLOWED_PROJECT_KEYS": ["ITSM", "OP"],
        "JIRA_LEAD_PROJECT_KEY": "OP",
        "JIRA_LEAD_ISSUE_TYPE_ID": "12716",
        "JIRA_ASSETS_CLOUD_ID": "",
        "JIRA_ASSETS_WORKSPACE_ID": "",
    }
    values.update(overrides)
    return Settings(**values)


def outage_decision(**overrides: object) -> TriageDecision:
    values: dict[str, object] = {
        "category": TriageCategory.INFRASTRUCTURE,
        "priority": TriagePriority.HIGHEST,
        "assigned_team": "Cloud-Platform",
        "suggested_status": "In Progress",
        "should_auto_close": False,
        "reasoning": "Produção fora do ar.",
        "internal_comment": "Incidente crítico encaminhado.",
    }
    values.update(overrides)
    return TriageDecision(**values)


def test_apply_decision_updates_issue_internal_note_and_transition():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "transitions": [
                        {
                            "id": "31",
                            "to": {
                                "name": "In Progress",
                                "statusCategory": {"key": "indeterminate"},
                            },
                        }
                    ]
                },
                request=request,
            )
        return httpx.Response(204, request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        actions = connector.apply_decision("ITSM-101", outage_decision())

    assert [request.method for request in requests] == ["GET", "PUT", "POST", "POST"]
    assert requests[1].url.path == "/rest/api/3/issue/ITSM-101"
    assert json.loads(requests[1].content) == {
        "fields": {
            "priority": {"name": "Highest"},
            "assignee": {"accountId": "account-123"},
        }
    }
    assert requests[2].url.path == "/rest/servicedeskapi/request/ITSM-101/comment"
    assert json.loads(requests[2].content) == {
        "body": "Incidente crítico encaminhado.",
        "public": False,
    }
    assert json.loads(requests[3].content) == {"transition": {"id": "31"}}
    assert requests[1].headers["authorization"].startswith("Basic ")
    assert "Issue atribuída à equipe 'Cloud-Platform'." in actions
    assert "Nota interna adicionada ao chamado." in actions
    assert "Chamado movido para 'In Progress'." in actions


def test_apply_commercial_decision_without_updates_makes_no_jira_requests():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204, request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        actions = connector.apply_decision(
            "OP-101",
            TriageDecision(
                category=TriageCategory.LEAD,
                reasoning="Lead consultado sem necessidade de alteração.",
            ),
        )

    assert actions == []
    assert requests == []


def test_auto_close_uses_resolved_transition():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "transitions": [
                        {
                            "id": "41",
                            "to": {
                                "name": "Resolved",
                                "statusCategory": {"key": "done"},
                            },
                        }
                    ]
                },
                request=request,
            )
        return httpx.Response(204, request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        actions = connector.apply_decision(
            "ITSM-101",
            outage_decision(suggested_status=None, should_auto_close=True),
        )

    assert "Chamado movido para 'Resolved'." in actions


def test_missing_transition_fails_explicitly():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"transitions": []}, request=request)
        return httpx.Response(204, request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        with pytest.raises(JiraConnectorError, match="Expected one Jira transition"):
            connector.apply_decision("ITSM-101", outage_decision())


def test_terminal_transition_requires_auto_close_flag():
    request_methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_methods.append(request.method)
        return httpx.Response(
            200,
            json={
                "transitions": [
                    {
                        "id": "41",
                        "to": {"name": "Resolved", "statusCategory": {"key": "done"}},
                    }
                ]
            },
            request=request,
        )

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        with pytest.raises(JiraConnectorError, match="conflicts with should_auto_close"):
            connector.apply_decision("ITSM-101", outage_decision(suggested_status="Resolved"))

    assert request_methods == ["GET"]


def test_http_errors_are_reported_without_response_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="private server detail", request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        with pytest.raises(JiraConnectorError, match="HTTP 403") as exc_info:
            connector.apply_decision("ITSM-101", outage_decision())

    assert "private server detail" not in str(exc_info.value)


def test_connector_requires_https_and_complete_credentials():
    with pytest.raises(JiraConnectorError, match="HTTPS"):
        JiraConnector(jira_settings(JIRA_INSTANCE_URL="http://example.atlassian.net"))

    with pytest.raises(JiraConnectorError, match="both JIRA_API_EMAIL and JIRA_API_TOKEN"):
        JiraConnector(jira_settings(JIRA_API_TOKEN=""))


def test_connector_is_disabled_only_when_both_credentials_are_absent():
    assert get_jira_connector(jira_settings(JIRA_API_EMAIL="", JIRA_API_TOKEN="")) is None
    with pytest.raises(JiraConnectorError, match="both JIRA_API_EMAIL and JIRA_API_TOKEN"):
        get_jira_connector(jira_settings(JIRA_API_TOKEN=""))


def test_manifest_tool_registry_is_complete_and_write_tools_are_gated():
    assert len(JIRA_TOOLS) == 25
    assert len({tool.name for tool in JIRA_TOOLS}) == 25
    with JiraConnector(
        jira_settings(JIRA_ENABLE_WRITE_OPERATIONS=False),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request)),
    ) as connector:
        available_names = {schema["name"] for schema in connector.available_tool_schemas()}
        assert "get_issue_fields" in available_names
        assert "get_project_issue_type_metadata" in available_names
        assert "search_assets_products_by_manufacturer" in available_names
        assert "search_assets_products_by_software" in available_names
        assert "get_latest_issue_comment" in available_names
        assert "query_knowledge_base" in available_names
        assert "escalate_to_human_group" not in available_names
        assert "add_public_comment" not in available_names
        assert "update_lead_manufacturer" not in available_names
        assert "create_lead" not in available_names
        assert "set_proposal_item_price" not in available_names
        with pytest.raises(JiraConnectorError, match="write operations are disabled"):
            connector.execute_tool("create_lead", {"summary": "Test"})


def test_create_lead_posts_only_supplied_fields():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "fields": [
                        {
                            "fieldId": "customfield_10115",
                            "name": "Empresa",
                            "required": False,
                            "schema": {"type": "string"},
                            "operations": ["set"],
                            "hasDefaultValue": False,
                        },
                        {
                            "fieldId": "customfield_10118",
                            "name": "Telefone",
                            "required": False,
                            "schema": {"type": "string"},
                            "operations": ["set"],
                            "hasDefaultValue": False,
                        },
                        {
                            "fieldId": "customfield_10120",
                            "name": "Detalhes da Solicitação",
                            "required": False,
                            "schema": {"type": "string"},
                            "operations": ["set"],
                            "hasDefaultValue": False,
                        },
                        {
                            "fieldId": "customfield_10468",
                            "name": "Quantidade de licenças",
                            "required": False,
                            "schema": {"type": "number"},
                            "operations": ["set"],
                            "hasDefaultValue": False,
                        },
                        {
                            "fieldId": "customfield_10143",
                            "name": "Origem do Lead",
                            "required": False,
                            "schema": {"type": "option"},
                            "operations": ["set"],
                            "hasDefaultValue": False,
                            "allowedValues": [{"id": "3", "value": "Site"}],
                        },
                    ]
                },
                request=request,
            )
        return httpx.Response(201, json={"key": "OP-9001"}, request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        result = connector.execute_tool(
            "create_lead",
            {
                "summary": "Novo lead",
                "company": "Empresa exemplo",
                "phone": "+55 11 5555-0100",
                "license_count": 3,
                "request_details": "Licenças para equipe comercial",
                "lead_source": "Site",
            },
        )

    assert result == {"key": "OP-9001"}
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/rest/api/3/issue/createmeta/OP/issuetypes/12716"
    assert requests[0].url.params["expand"] == "fields"
    assert requests[1].method == "POST"
    assert requests[1].url.path == "/rest/api/3/issue"
    assert json.loads(requests[1].content) == {
        "fields": {
            "summary": "Novo lead",
            "issuetype": {"id": "12716"},
            "project": {"key": "OP"},
            "customfield_10115": "Empresa exemplo",
            "customfield_10118": "+55 11 5555-0100",
            "customfield_10120": "Licenças para equipe comercial",
            "customfield_10468": 3,
            "customfield_10143": {"value": "Site"},
        }
    }


def test_project_issue_type_metadata_is_project_scoped_and_sanitized():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "fields": [
                    {
                        "fieldId": "customfield_10120",
                        "name": "Detalhes da Solicitação",
                        "required": False,
                        "schema": {"type": "string", "custom": "textarea"},
                        "operations": ["set"],
                        "hasDefaultValue": False,
                        "allowedValues": [],
                    },
                    {
                        "fieldId": "customfield_10143",
                        "name": "Origem do Lead",
                        "required": False,
                        "schema": {"type": "option"},
                        "operations": ["set"],
                        "hasDefaultValue": False,
                        "allowedValues": [
                            {"id": "3", "value": "Site", "self": "https://example.invalid"},
                        ],
                    },
                ]
            },
            request=request,
        )

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        result = connector.execute_tool(
            "get_project_issue_type_metadata",
            {"project_key": "op", "issue_type_id": "12716"},
        )
        with pytest.raises(JiraConnectorError, match="not included"):
            connector.execute_tool(
                "get_project_issue_type_metadata",
                {"project_key": "OTHER", "issue_type_id": "12716"},
            )

    assert requests[0].url.path == "/rest/api/3/issue/createmeta/OP/issuetypes/12716"
    assert result["fields"][1]["allowed_values"] == [{"id": "3", "value": "Site"}]
    assert len(requests) == 1


def test_create_lead_rejects_unavailable_option_from_metadata():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "fields": [
                    {
                        "fieldId": "customfield_10143",
                        "name": "Origem do Lead",
                        "required": False,
                        "schema": {"type": "option"},
                        "operations": ["set"],
                        "hasDefaultValue": False,
                        "allowedValues": [{"value": "Site"}],
                    }
                ]
            },
            request=request,
        )

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        with pytest.raises(JiraConnectorError, match="not one of its allowed options"):
            connector.create_lead("Novo lead", lead_source="Evento")

    assert len(requests) == 1


@pytest.mark.parametrize(
    ("tool_name", "arguments", "transition_id", "expected_fields"),
    [
        (
            "start_lead_work",
            {"issue_key": "OP-1"},
            "2",
            {"customfield_14975": {"value": "N.B. Licença nova"}},
        ),
        (
            "transition_lead_to_proposal_item",
            {"issue_key": "OP-1"},
            "21",
            None,
        ),
        (
            "generate_new_proposal",
            {
                "issue_key": "OP-1",
                "forecast_date": "2026-09-30",
                "probability": "2 - Média",
                "next_follow_up_date": "2026-10-02",
                "priority": "1- Padrão",
                "billing": "Empresa exemplo",
                "payment_days": "28 dd",
                "payment_method": "Boleto",
                "proposal_valid_until": "2026-10-05",
                "proposal_information": "Informações comerciais",
            },
            "3",
            {
                "customfield_10142": "2026-09-30",
                "customfield_10141": {"value": "2 - Média"},
                "customfield_10140": "2026-10-02",
                "priority": {"name": "1- Padrão"},
                "customfield_10100": {"value": "Empresa exemplo"},
                "customfield_10131": {"value": "28 dd"},
                "customfield_10132": {"value": "Boleto"},
                "customfield_10139": "2026-10-05",
                "customfield_10144": "Informações comerciais",
            },
        ),
        (
            "send_item_to_purchasing",
            {
                "issue_key": "OP-1",
                "product_object_id": "6195",
                "quantity": 1,
                "quotation_classification": "Licença Nova",
                "period_months": "12",
                "price_type": "Corporativo",
            },
            "12",
            {
                "customfield_11828": [
                    {
                        "workspaceId": "workspace-test",
                        "id": "workspace-test:6195",
                        "objectId": "6195",
                    }
                ],
                "customfield_10093": 1,
                "customfield_11348": "-",
                "customfield_10846": {"value": "Licença Nova"},
                "customfield_13268": {"value": "12"},
                "customfield_10243": {"value": "Corporativo"},
            },
        ),
        (
            "set_proposal_item_price",
            {"issue_key": "OP-1", "unit_price": 5850, "likely_scenario": True},
            "7",
            {
                "customfield_10173": 5850.0,
                "customfield_13868": {"value": "Sim"},
            },
        ),
    ],
)
def test_manifest_transitions_check_availability_and_post_manifest_fields(
    tool_name,
    arguments,
    transition_id,
    expected_fields,
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"transitions": [{"id": transition_id}]},
                request=request,
            )
        return httpx.Response(204, request=request)

    with JiraConnector(
        jira_settings(JIRA_ASSETS_WORKSPACE_ID="workspace-test"),
        transport=httpx.MockTransport(handler),
    ) as connector:
        connector.execute_tool(tool_name, arguments)

    assert [request.method for request in requests] == ["GET", "POST"]
    assert requests[0].url.path == "/rest/api/3/issue/OP-1/transitions"
    payload = json.loads(requests[1].content)
    assert payload["transition"] == {"id": transition_id}
    if expected_fields is None:
        assert "fields" not in payload
    else:
        assert payload["fields"] == expected_fields


def test_transition_not_available_is_rejected_before_write():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"transitions": []}, request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        with pytest.raises(JiraConnectorError, match="not available"):
            connector.execute_tool("start_lead_work", {"issue_key": "OP-1"})

    assert [request.method for request in requests] == ["GET"]


def test_get_issue_and_lead_tools_use_manifest_fields():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"fields": {}}, request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        connector.execute_tool("get_issue_fields", {"issue_key": "OP-1"})
        connector.execute_tool("get_lead_details", {"issue_key": "OP-2"})
        connector.execute_tool("get_proposal_item_values", {"issue_key": "OP-3"})
        connector.execute_tool("find_proposal_items", {"issue_key": "OP-4"})

    assert [request.url.path for request in requests] == [
        "/rest/api/3/issue/OP-1",
        "/rest/api/3/issue/OP-2",
        "/rest/api/3/issue/OP-2/comment",
        "/rest/api/3/issue/OP-3",
        "/rest/api/3/search/jql",
    ]
    assert requests[0].url.params["expand"] == "names,editmeta,transitions"
    assert requests[1].url.params["fields"] == JiraConnector.LEAD_DETAILS_FIELDS
    assert requests[2].url.params["orderBy"] == "created"
    assert requests[3].url.params["fields"] == JiraConnector.PROPOSAL_ITEM_FIELDS
    assert requests[4].url.params["jql"] == "parent=OP-4"


def test_get_lead_details_paginates_complete_comment_history():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/comment"):
            start_at = int(request.url.params["startAt"])
            if start_at == 0:
                return httpx.Response(
                    200,
                    json={
                        "startAt": 0,
                        "maxResults": 100,
                        "total": 2,
                        "comments": [{"id": "1", "body": "Olá"}],
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "startAt": 1,
                    "maxResults": 100,
                    "total": 2,
                    "comments": [{"id": "2", "body": "Pagamento em 30 dias"}],
                },
                request=request,
            )
        return httpx.Response(200, json={"fields": {}}, request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        result = connector.get_lead_details("OP-1")

    assert [comment["id"] for comment in result["comments"]] == ["1", "2"]
    assert [request.url.params.get("startAt") for request in requests[1:]] == ["0", "1"]


def test_attachment_download_is_scoped_to_issue_and_limited():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/rest/api/3/issue/OP-1":
            return httpx.Response(
                200,
                json={
                    "fields": {
                        "attachment": [
                            {
                                "id": "22",
                                "filename": "info.txt",
                                "mimeType": "text/plain",
                                "size": 4,
                            }
                        ]
                    }
                },
                request=request,
            )
        return httpx.Response(200, content=b"data", request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        result = connector.execute_tool(
            "download_issue_attachment",
            {"issue_key": "OP-1", "attachment_id": "22"},
        )

    assert result["content_base64"] == "ZGF0YQ=="
    assert requests[1].url.path == "/rest/api/3/attachment/content/22"

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        with pytest.raises(JiraConnectorError, match="does not belong"):
            connector.execute_tool(
                "download_issue_attachment",
                {"issue_key": "OP-1", "attachment_id": "999"},
            )


def test_add_comment_is_always_internal():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"id": "comment-1"}, request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        result = connector.execute_tool(
            "add_internal_comment",
            {"issue_key": "OP-1", "comment": "Nota para a equipe"},
        )

    assert result == {"id": "comment-1"}
    assert requests[0].url.path == "/rest/servicedeskapi/request/OP-1/comment"
    assert json.loads(requests[0].content) == {
        "body": "Nota para a equipe",
        "public": False,
    }


def test_public_comment_is_visible_to_requester_without_repeating_account_name():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204, request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        result = connector.execute_tool(
            "add_public_comment",
            {"issue_key": "OP-1", "comment": "Informe a forma de pagamento."},
        )

    assert result == {
        "issue_key": "OP-1",
        "added": True,
        "public": True,
        "transition_id": "36",
        "field_id": "customfield_15195",
    }
    assert requests[0].url.path == "/rest/api/2/issue/OP-1/transitions"
    assert json.loads(requests[0].content) == {
        "transition": {"id": "36"},
        "fields": {"customfield_15195": "Informe a forma de pagamento."},
    }


def test_public_comment_removes_repeated_legacy_agent_headers():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/transitions"):
            return httpx.Response(400, request=request)
        return httpx.Response(201, json={"id": "comment-public"}, request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        connector.add_public_comment(
            "OP-1",
            f"{JiraConnector.AGENT_COMMENT_PREFIX}\n\n"
            f"{JiraConnector.AGENT_COMMENT_PREFIX}\n\n"
            "Olá, Maria! Poderia nos informar a data prevista?",
        )

    assert requests[-1].url.path == "/rest/api/2/issue/OP-1/comment"
    assert json.loads(requests[-1].content)["body"] == (
        "Olá, Maria! Poderia nos informar a data prevista?"
    )


def test_public_comment_rejects_legacy_header_without_message():
    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(
            lambda request: pytest.fail("Empty comments must not be sent to Jira")
        ),
    ) as connector:
        with pytest.raises(JiraConnectorError, match="must contain message text"):
            connector.add_public_comment("OP-1", JiraConnector.AGENT_COMMENT_PREFIX)


def test_authenticated_user_comment_uses_configured_account_id():
    with JiraConnector(
        jira_settings(JIRA_AGENT_ACCOUNT_ID="connected-account"),
        transport=httpx.MockTransport(
            lambda request: pytest.fail("Should not need to resolve the current account")
        ),
    ) as connector:
        assert connector.is_authenticated_user_comment(
            {"author": {"accountId": "connected-account"}}
        )
        assert not connector.is_authenticated_user_comment(
            {"author": {"accountId": "another-account"}}
        )


def test_authenticated_user_comment_resolves_and_caches_current_account():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"accountId": "connected-account"}, request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        comment = {"author": {"accountId": "connected-account"}}
        assert connector.is_authenticated_user_comment(comment)
        assert connector.is_authenticated_user_comment(comment)

    assert len(requests) == 1
    assert requests[0].url.path == "/rest/api/3/myself"


def test_latest_comment_query_returns_comment_and_orders_newest_first():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"comments": [{"id": "12", "body": "Nova resposta"}]},
            request=request,
        )

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        result = connector.execute_tool(
            "get_latest_issue_comment",
            {"issue_key": "OP-1"},
        )

    assert result["latest_comment"]["id"] == "12"
    assert requests[0].url.params["orderBy"] == "-created"
    assert requests[0].url.params["maxResults"] == "1"


def test_update_lead_manufacturer_discovers_editable_text_field():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "names": {"customfield_12345": "Fabricante"},
                    "editmeta": {
                        "fields": {
                            "customfield_12345": {"schema": {"type": "string"}},
                        }
                    },
                    "fields": {
                        "issuetype": {"id": "12716"},
                        "customfield_12345": None,
                    },
                },
                request=request,
            )
        return httpx.Response(204, request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        result = connector.execute_tool(
            "update_lead_manufacturer",
            {"issue_key": "OP-1", "manufacturer_name": "Acme Software"},
        )

    assert result == {
        "issue_key": "OP-1",
        "field_id": "customfield_12345",
        "manufacturer": "Acme Software",
        "updated": True,
    }
    assert [request.method for request in requests] == ["GET", "PUT"]
    assert json.loads(requests[1].content) == {"fields": {"customfield_12345": "Acme Software"}}


def test_update_lead_manufacturer_sets_assets_reference_from_assets_id():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "names": {"customfield_12345": "Fabricante"},
                    "editmeta": {
                        "fields": {
                            "customfield_12345": {
                                "schema": {
                                    "type": "array",
                                    "items": "com.riadalabs.jira.plugins.insight:rlabs-customfield-object",
                                }
                            }
                        }
                    },
                    "fields": {
                        "issuetype": {"id": "12716"},
                        "customfield_12345": None,
                    },
                },
                request=request,
            )
        return httpx.Response(204, request=request)

    with JiraConnector(
        jira_settings(JIRA_ASSETS_WORKSPACE_ID="workspace-test"),
        transport=httpx.MockTransport(handler),
    ) as connector:
        connector.execute_tool(
            "update_lead_manufacturer",
            {
                "issue_key": "OP-1",
                "manufacturer_name": "Acme Software",
                "manufacturer_object_id": "6195",
            },
        )

    assert json.loads(requests[1].content) == {
        "fields": {
            "customfield_12345": [
                {
                    "workspaceId": "workspace-test",
                    "id": "workspace-test:6195",
                    "objectId": "6195",
                }
            ]
        }
    }


def test_update_lead_manufacturer_rejects_non_lead_project_before_request():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        with pytest.raises(JiraConnectorError, match="restricted to the configured lead project"):
            connector.execute_tool(
                "update_lead_manufacturer",
                {"issue_key": "ITSM-1", "manufacturer_name": "Acme Software"},
            )

    assert requests == []


def test_update_lead_manufacturer_rejects_non_lead_issue_type():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "names": {"customfield_12345": "Fabricante"},
                "editmeta": {
                    "fields": {
                        "customfield_12345": {"schema": {"type": "string"}},
                    }
                },
                "fields": {"issuetype": {"id": "1"}, "customfield_12345": None},
            },
            request=request,
        )

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        with pytest.raises(JiraConnectorError, match="restricted to the configured lead issue"):
            connector.execute_tool(
                "update_lead_manufacturer",
                {"issue_key": "OP-1", "manufacturer_name": "Acme Software"},
            )

    assert [request.method for request in requests] == ["GET"]


@pytest.mark.parametrize("manufacturer_field_id", ["", "customfield_10081"])
def test_update_lead_manufacturer_reports_named_field_that_is_not_editable(
    manufacturer_field_id: str,
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "names": {"customfield_10081": "Fabricante"},
                "editmeta": {"fields": {"issuetype": {"schema": {"type": "issuetype"}}}},
                "fields": {"issuetype": {"id": "12716"}},
            },
            request=request,
        )

    with JiraConnector(
        jira_settings(JIRA_MANUFACTURER_FIELD_ID=manufacturer_field_id),
        transport=httpx.MockTransport(handler),
    ) as connector:
        with pytest.raises(
            JiraConnectorError,
            match=r"customfield_10081.*not editable.*edit screen",
        ):
            connector.execute_tool(
                "update_lead_manufacturer",
                {"issue_key": "OP-1", "manufacturer_name": "Acme Software"},
            )

    assert [request.method for request in requests] == ["GET"]


def test_update_lead_manufacturer_can_be_skipped_as_pending_when_not_editable():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "names": {"customfield_10081": "Fabricante"},
                "editmeta": {"fields": {"issuetype": {"schema": {"type": "issuetype"}}}},
                "fields": {"issuetype": {"id": "12716"}},
            },
            request=request,
        )

    with JiraConnector(
        jira_settings(
            JIRA_SKIP_MANUFACTURER_UPDATE_IF_NOT_EDITABLE=True,
            JIRA_MANUFACTURER_FIELD_ID="customfield_10081",
        ),
        transport=httpx.MockTransport(handler),
    ) as connector:
        result = connector.execute_tool(
            "update_lead_manufacturer",
            {"issue_key": "OP-1", "manufacturer_name": "Acme Software"},
        )
        assert connector.manufacturer_update_pending is True

    assert result == {
        "issue_key": "OP-1",
        "field_id": "customfield_10081",
        "manufacturer": "Acme Software",
        "updated": False,
        "pending": True,
        "reason": (
            "Configured JIRA_MANUFACTURER_FIELD_ID 'customfield_10081' is not editable on "
            "this issue. Add the field to the Jira lead edit screen and grant the integration "
            "account permission to edit it."
        ),
    }
    assert [request.method for request in requests] == ["GET"]


def test_proposal_tool_requires_all_fields_to_start_generation():
    with pytest.raises(ValidationError):
        ProposalArguments.model_validate({"issue_key": "OP-1"})


def test_assets_aql_uses_fixed_host_bearer_auth_and_escaped_manufacturer():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"objectEntries": []}, request=request)

    with JiraConnector(
        jira_settings(
            JIRA_ASSETS_ACCESS_TOKEN="assets-bearer-test",
            JIRA_ASSETS_CLOUD_ID="cloud-test",
            JIRA_ASSETS_WORKSPACE_ID="workspace-test",
        ),
        transport=httpx.MockTransport(handler),
    ) as connector:
        connector.execute_tool(
            "search_assets_products_by_manufacturer",
            {
                "manufacturer": 'ACME" OR objectTypeId = 2 OR Fabricante like "ACME',
            },
        )

    request = requests[0]
    assert request.url.host == "api.atlassian.com"
    assert request.url.path == (
        "/ex/jira/cloud-test/jsm/assets/workspace/workspace-test/v1/object/aql"
    )
    assert request.headers["authorization"] == "Bearer assets-bearer-test"
    query = json.loads(request.content)["qlQuery"]
    assert query.startswith("objectTypeId = 157 AND Fabricante like ")
    assert '\\" OR objectTypeId = 2 OR Fabricante like \\"' in query


def test_assets_retries_with_jira_api_token_after_bearer_unauthorized():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers.get("authorization", "").startswith("Bearer "):
            return httpx.Response(401, request=request)
        return httpx.Response(200, json={"objectEntries": []}, request=request)

    with JiraConnector(
        jira_settings(
            JIRA_ASSETS_ACCESS_TOKEN="rejected-bearer-token",
            JIRA_ASSETS_CLOUD_ID="cloud-test",
            JIRA_ASSETS_WORKSPACE_ID="workspace-test",
        ),
        transport=httpx.MockTransport(handler),
    ) as connector:
        result = connector.execute_tool(
            "search_assets_products_by_software",
            {"software_name": "Example Software"},
        )

    assert result["objectEntries"] == []
    assert len(requests) == 2
    assert requests[0].headers["authorization"].startswith("Bearer ")
    assert requests[1].headers["authorization"].startswith("Basic ")
    assert requests[0].url == requests[1].url
    assert requests[0].content == requests[1].content


def test_assets_reports_unauthorized_when_both_auth_methods_fail():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401, request=request)

    with JiraConnector(
        jira_settings(
            JIRA_ASSETS_ACCESS_TOKEN="rejected-bearer-token",
            JIRA_ASSETS_CLOUD_ID="cloud-test",
            JIRA_ASSETS_WORKSPACE_ID="workspace-test",
        ),
        transport=httpx.MockTransport(handler),
    ) as connector:
        with pytest.raises(JiraConnectorError, match="HTTP 401"):
            connector.execute_tool(
                "search_assets_products_by_software",
                {"software_name": "Example Software"},
            )

    assert len(requests) == 2
    assert requests[0].headers["authorization"].startswith("Bearer ")
    assert requests[1].headers["authorization"].startswith("Basic ")


def test_assets_aql_searches_by_software_name_with_escaped_value():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"objectEntries": []}, request=request)

    with JiraConnector(
        jira_settings(
            JIRA_ASSETS_ACCESS_TOKEN="assets-bearer-test",
            JIRA_ASSETS_CLOUD_ID="cloud-test",
            JIRA_ASSETS_WORKSPACE_ID="workspace-test",
        ),
        transport=httpx.MockTransport(handler),
    ) as connector:
        connector.execute_tool(
            "search_assets_products_by_software",
            {"software_name": 'Acme "Suite"'},
        )

    query = json.loads(requests[0].content)["qlQuery"]
    assert query == 'objectTypeId = 157 AND Name like "Acme \\"Suite\\""'


def test_assets_product_search_limits_and_compacts_results():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {"id": "1167", "name": "Fabricante"},
                    {"id": "1153", "name": "Key"},
                ],
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "startAt": 0,
                "maxResults": 5,
                "total": 62,
                "hasMoreResults": False,
                "objectTypeAttributes": [{"id": "large-unneeded-metadata"}],
                "values": [
                    {
                        "id": "6969",
                        "objectKey": "CRM-6969",
                        "label": "Actions for Jira Service Desk",
                        "avatar": {"large": "unneeded"},
                        "attributes": [
                            {
                                "objectTypeAttributeId": "1167",
                                "objectAttributeValues": [
                                    {"displayValue": "Atlassian", "value": "Atlassian"}
                                ],
                            },
                            {
                                "objectTypeAttributeId": "1153",
                                "objectAttributeValues": [{"displayValue": "CRM-6969"}],
                            },
                        ],
                    }
                ],
            },
            request=request,
        )

    with JiraConnector(
        jira_settings(
            JIRA_ASSETS_ACCESS_TOKEN="assets-bearer-test",
            JIRA_ASSETS_CLOUD_ID="cloud-test",
            JIRA_ASSETS_WORKSPACE_ID="workspace-test",
        ),
        transport=httpx.MockTransport(handler),
    ) as connector:
        result = connector.execute_tool(
            "search_assets_products_by_software",
            {"software_name": "Jira"},
        )

    assert requests[0].method == "POST"
    assert requests[0].url.params["startAt"] == "0"
    assert requests[0].url.params["maxResults"] == "5"
    assert requests[1].method == "GET"
    assert requests[1].url.path.endswith("/v1/objecttype/157/attributes")
    assert result["total"] == 62
    assert result["hasMoreResults"] is True
    assert "objectTypeAttributes" not in result
    assert result["values"] == [
        {
            "id": "6969",
            "objectKey": "CRM-6969",
            "name": "Actions for Jira Service Desk",
            "manufacturer": ["Atlassian"],
        }
    ]


def test_assets_schema_list_and_object_types_use_assets_api_and_pagination():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"values": []}, request=request)

    with JiraConnector(
        jira_settings(
            JIRA_ASSETS_ACCESS_TOKEN="assets-bearer-test",
            JIRA_ASSETS_CLOUD_ID="cloud-test",
            JIRA_ASSETS_WORKSPACE_ID="workspace-test",
        ),
        transport=httpx.MockTransport(handler),
    ) as connector:
        connector.execute_tool(
            "list_assets_schemas",
            {"start_at": 20, "max_results": 10, "include_counts": True},
        )
        connector.execute_tool(
            "get_assets_object_types",
            {"objectschema_id": "crm-1"},
        )

    assert requests[0].url.path.endswith("/v1/objectschema/list")
    assert requests[0].url.params["startAt"] == "20"
    assert requests[0].url.params["maxResults"] == "10"
    assert requests[0].url.params["includeCounts"] == "true"
    assert requests[1].url.path.endswith("/v1/objectschema/crm-1/objecttypes")


def test_assets_cloud_id_and_workspace_discovery():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/_edge/tenant_info":
            return httpx.Response(200, json={"cloudId": "cloud-discovered"}, request=request)
        return httpx.Response(
            200,
            json={"values": [{"workspaceId": "workspace-discovered"}]},
            request=request,
        )

    with JiraConnector(
        jira_settings(),
        transport=httpx.MockTransport(handler),
    ) as connector:
        cloud_id = connector.execute_tool("get_assets_cloud_id", {})
        workspaces = connector.execute_tool("get_assets_workspaces", {})
        connector.execute_tool("list_assets_schemas", {})

    assert cloud_id == {"cloud_id": "cloud-discovered"}
    assert workspaces["values"][0]["workspaceId"] == "workspace-discovered"
    assert requests[0].url.path == "/_edge/tenant_info"
    assert requests[1].url.path == "/rest/servicedeskapi/assets/workspace"
    assert requests[2].url.host == "api.atlassian.com"
    assert requests[2].url.path.endswith("/workspace/workspace-discovered/v1/objectschema/list")
