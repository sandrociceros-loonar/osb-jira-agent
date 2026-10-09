"""Tests for Jira Service Management API integration."""

import json

import httpx
import pytest

from src.config import Settings
from src.jira.connector import JiraConnector, JiraConnectorError, get_jira_connector
from src.jira.tools import JIRA_TOOLS
from src.models.agent_result import TriageCategory, TriageDecision, TriagePriority


def jira_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "JIRA_INSTANCE_URL": "https://example.atlassian.net",
        "JIRA_API_EMAIL": "agent@example.com",
        "JIRA_API_TOKEN": "local-test-token",
        "JIRA_TEAM_ACCOUNT_IDS": {"Cloud-Platform": "account-123"},
        "JIRA_ENABLE_WRITE_OPERATIONS": True,
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
    assert len(JIRA_TOOLS) == 18
    assert len({tool.name for tool in JIRA_TOOLS}) == 18
    with JiraConnector(
        jira_settings(JIRA_ENABLE_WRITE_OPERATIONS=False),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request)),
    ) as connector:
        available_names = {
            schema["name"] for schema in connector.available_tool_schemas()
        }
        assert "get_issue_fields" in available_names
        assert "search_assets_products_by_manufacturer" in available_names
        assert "create_lead" not in available_names
        assert "set_proposal_item_price" not in available_names
        with pytest.raises(JiraConnectorError, match="write operations are disabled"):
            connector.execute_tool("create_lead", {"summary": "Test"})


def test_create_lead_posts_only_supplied_fields():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
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
                "license_count": 3,
                "lead_source": "Site",
            },
        )

    assert result == {"key": "OP-9001"}
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/rest/api/3/issue"
    assert json.loads(requests[0].content) == {
        "fields": {
            "summary": "Novo lead",
            "issuetype": {"id": "12716"},
            "project": {"key": "OP"},
            "customfield_10115": "Empresa exemplo",
            "customfield_10468": 3,
            "customfield_10143": {"value": "Site"},
        }
    }


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
        "/rest/api/3/issue/OP-3",
        "/rest/api/3/search/jql",
    ]
    assert requests[0].url.params["expand"] == "names,editmeta,transitions"
    assert requests[1].url.params["fields"] == JiraConnector.LEAD_DETAILS_FIELDS
    assert requests[2].url.params["fields"] == JiraConnector.PROPOSAL_ITEM_FIELDS
    assert requests[3].url.params["jql"] == "parent=OP-4"


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
