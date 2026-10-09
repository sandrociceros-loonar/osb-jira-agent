"""Authenticated Jira Service Management REST API client."""

import base64
import re
from urllib.parse import quote, urlparse

import httpx
from pydantic import ValidationError

from src.config import Settings
from src.jira.tools import JIRA_TOOLS, JIRA_TOOLS_BY_NAME
from src.models.agent_result import TriageDecision


class JiraConnectorError(Exception):
    """Raised when Jira configuration or an API operation is invalid."""


class JiraConnector:
    """Calls the allowlisted Jira operations represented by the collection manifests."""

    TRANSITION_NAMES = (
        "start_lead_work",
        "transition_lead_to_proposal_item",
        "generate_new_proposal",
        "send_item_to_purchasing",
        "set_proposal_item_price",
    )
    ASSETS_API_ROOT = "https://api.atlassian.com/ex/jira"
    LEAD_DETAILS_FIELDS = (
        "assignee,comment,description,summary,customfield_10115,customfield_10117,"
        "customfield_10116,customfield_10119,customfield_10468,customfield_10125"
    )
    PROPOSAL_ITEM_FIELDS = (
        "status,customfield_10191,customfield_10171,customfield_13867,customfield_10109,"
        "customfield_10245,customfield_13834,customfield_13334"
    )

    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parsed_url = urlparse(settings.jira_instance_url)
        if (
            parsed_url.scheme != "https"
            or not parsed_url.netloc
            or parsed_url.username
            or parsed_url.password
            or parsed_url.path not in ("", "/")
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise JiraConnectorError(
                "JIRA_INSTANCE_URL must be an HTTPS Jira Cloud base URL without a path."
            )

        if not settings.jira_api_email or not settings.jira_api_token:
            raise JiraConnectorError(
                "Configure both JIRA_API_EMAIL and JIRA_API_TOKEN to enable the Jira connector."
            )

        allowed_projects = {key.upper() for key in settings.jira_allowed_project_keys}
        if not allowed_projects:
            raise JiraConnectorError("Configure at least one JIRA_ALLOWED_PROJECT_KEYS entry.")
        if settings.jira_lead_project_key.upper() not in allowed_projects:
            raise JiraConnectorError(
                "JIRA_LEAD_PROJECT_KEY must be included in JIRA_ALLOWED_PROJECT_KEYS."
            )

        self.team_account_ids = settings.jira_team_account_ids
        self.allowed_projects = allowed_projects
        self._jira_api_email = settings.jira_api_email
        self._jira_api_token = settings.jira_api_token
        self.lead_project_key = settings.jira_lead_project_key.upper()
        self.lead_issue_type_id = settings.jira_lead_issue_type_id
        self.transition_ids = settings.jira_transition_ids
        self.allow_write_operations = settings.jira_allow_write_operations
        self.assets_access_token = settings.jira_assets_access_token
        self.assets_cloud_id = settings.jira_assets_cloud_id
        self.assets_workspace_id = settings.jira_assets_workspace_id
        self.assets_product_object_type_id = settings.jira_assets_product_object_type_id
        self.attachment_max_bytes = settings.jira_attachment_max_bytes
        if not re.fullmatch(r"\d+", self.lead_issue_type_id):
            raise JiraConnectorError("JIRA_LEAD_ISSUE_TYPE_ID must contain only digits.")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", self.lead_project_key):
            raise JiraConnectorError("JIRA_LEAD_PROJECT_KEY has an invalid format.")
        if not re.fullmatch(r"\d+", self.assets_product_object_type_id):
            raise JiraConnectorError(
                "JIRA_ASSETS_PRODUCT_OBJECT_TYPE_ID must contain only digits."
            )
        if any(
            not re.fullmatch(r"\d+", self.transition_ids.get(name, ""))
            for name in self.TRANSITION_NAMES
        ):
            raise JiraConnectorError(
                "JIRA_TRANSITION_IDS must define numeric IDs for every manifest transition."
            )
        self._transport = transport
        self._client = httpx.Client(
            base_url=settings.jira_instance_url.rstrip("/"),
            auth=httpx.BasicAuth(settings.jira_api_email, settings.jira_api_token),
            headers={"Accept": "application/json"},
            timeout=15.0,
            transport=transport,
            follow_redirects=True,
        )
        self._assets_client: httpx.Client | None = None

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()
        if self._assets_client is not None:
            self._assets_client.close()

    def __enter__(self) -> "JiraConnector":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def apply_decision(self, issue_key: str, decision: TriageDecision) -> list[str]:
        """Apply the configured priority, assignee, internal note, and status."""
        self._require_write_enabled()
        encoded_issue_key = self._encoded_issue_key(issue_key)
        target_status = decision.suggested_status
        if decision.should_auto_close and not target_status:
            target_status = "Resolved"

        transition_to_apply: dict[str, object] | None = None
        if target_status:
            transitions_response = self._request(
                "GET",
                f"/rest/api/3/issue/{encoded_issue_key}/transitions",
            )
            try:
                transitions = transitions_response.json().get("transitions", [])
            except (ValueError, AttributeError) as exc:
                raise JiraConnectorError("Jira returned an invalid transitions response.") from exc

            matching_transitions = [
                transition
                for transition in transitions
                if transition.get("to", {}).get("name", "").casefold() == target_status.casefold()
            ]
            if len(matching_transitions) != 1:
                raise JiraConnectorError(
                    f"Expected one Jira transition to '{target_status}', "
                    f"found {len(matching_transitions)}."
                )

            target = matching_transitions[0].get("to", {})
            status_category = target.get("statusCategory", {}).get("key", "").casefold()
            terminal_status_names = {
                "closed",
                "complete",
                "completed",
                "concluído",
                "concluido",
                "fechado",
                "resolvido",
                "resolved",
            }
            is_terminal = (
                status_category == "done" or target_status.casefold() in terminal_status_names
            )
            if decision.should_auto_close != is_terminal:
                raise JiraConnectorError(
                    f"Jira transition to '{target_status}' conflicts with should_auto_close."
                )
            transition_to_apply = matching_transitions[0]

        fields: dict[str, object] = {}
        if decision.priority is not None:
            fields["priority"] = {"name": decision.priority.value}
        account_id = (
            self.team_account_ids.get(decision.assigned_team) if decision.assigned_team else None
        )
        if account_id and decision.assigned_team:
            fields["assignee"] = {"accountId": account_id}

        if fields:
            self._request(
                "PUT",
                f"/rest/api/3/issue/{encoded_issue_key}",
                json={"fields": fields},
            )

        actions = []
        if decision.priority is not None:
            actions.append(f"Prioridade atualizada para '{decision.priority.value}' no Jira.")
        if account_id:
            actions.append(f"Issue atribuída à equipe '{decision.assigned_team}'.")
        elif decision.assigned_team:
            actions.append(
                f"Equipe '{decision.assigned_team}' não atribuída: configure seu accountId "
                "em JIRA_TEAM_ACCOUNT_IDS."
            )

        if decision.internal_comment:
            self._request(
                "POST",
                f"/rest/servicedeskapi/request/{encoded_issue_key}/comment",
                json={"body": decision.internal_comment, "public": False},
            )
            actions.append("Nota interna adicionada ao chamado.")

        if target_status and transition_to_apply:
            self._request(
                "POST",
                f"/rest/api/3/issue/{encoded_issue_key}/transitions",
                json={"transition": {"id": transition_to_apply["id"]}},
            )
            actions.append(f"Chamado movido para '{target_status}'.")

        return actions

    def available_tool_schemas(self) -> list[dict[str, object]]:
        """Return read tools and, only when explicitly enabled, write tools."""
        return [
            tool.function_schema()
            for tool in JIRA_TOOLS
            if self.allow_write_operations or not tool.write_operation
        ]

    def execute_tool(self, name: str, arguments: dict[str, object]) -> object:
        """Validate and dispatch one explicit manifest operation."""
        tool = JIRA_TOOLS_BY_NAME.get(name)
        if tool is None:
            raise JiraConnectorError(f"Jira tool '{name}' is not allowlisted.")
        if tool.write_operation:
            self._require_write_enabled()
        try:
            parsed_arguments = tool.arguments_model.model_validate(arguments)
        except ValidationError as exc:
            raise JiraConnectorError(f"Invalid arguments for Jira tool '{name}'.") from exc
        return getattr(self, tool.handler_name)(
            **parsed_arguments.model_dump(mode="json", exclude_none=True)
        )

    def create_lead(
        self,
        summary: str,
        company: str | None = None,
        contact_name: str | None = None,
        email: str | None = None,
        license_count: int | None = None,
        product_root: str | None = None,
        lead_source: str | None = None,
    ) -> dict[str, object]:
        self._require_write_enabled()
        fields: dict[str, object] = {
            "summary": summary,
            "issuetype": {"id": self.lead_issue_type_id},
            "project": {"key": self.lead_project_key},
        }
        custom_fields: tuple[tuple[str, object | None], ...] = (
            ("customfield_10115", company),
            ("customfield_10116", contact_name),
            ("customfield_10117", email),
            ("customfield_10468", license_count),
            ("customfield_10119", product_root),
            ("customfield_10143", {"value": lead_source} if lead_source else None),
        )
        fields.update({field: value for field, value in custom_fields if value is not None})
        response = self._request("POST", "/rest/api/3/issue", json={"fields": fields})
        return self._json(response)

    def get_issue_fields(self, issue_key: str) -> dict[str, object]:
        key = self._encoded_issue_key(issue_key)
        response = self._request(
            "GET",
            f"/rest/api/3/issue/{key}",
            params={"expand": "names,editmeta,transitions"},
        )
        return self._json(response)

    def get_lead_details(self, issue_key: str) -> dict[str, object]:
        key = self._encoded_issue_key(issue_key)
        response = self._request(
            "GET",
            f"/rest/api/3/issue/{key}",
            params={
                "fieldsByKeys": "true",
                "fields": self.LEAD_DETAILS_FIELDS,
                "expand": "names",
            },
        )
        return self._json(response)

    def start_lead_work(self, issue_key: str) -> dict[str, object]:
        return self._transition_issue(
            issue_key,
            self.transition_ids["start_lead_work"],
            {"customfield_14975": {"value": "N.B. Licença nova"}},
        )

    def transition_lead_to_proposal_item(self, issue_key: str) -> dict[str, object]:
        return self._transition_issue(
            issue_key,
            self.transition_ids["transition_lead_to_proposal_item"],
        )

    def find_proposal_items(self, issue_key: str) -> dict[str, object]:
        self._encoded_issue_key(issue_key)
        response = self._request(
            "GET",
            "/rest/api/3/search/jql",
            params={"jql": f"parent={issue_key}", "fields": "parent,key"},
        )
        return self._json(response)

    def generate_new_proposal(
        self,
        issue_key: str,
        forecast_date: str | None = None,
        probability: str | None = None,
        next_follow_up_date: str | None = None,
        priority: str | None = None,
        billing: str | None = None,
        payment_days: str | None = None,
        payment_method: str | None = None,
        proposal_valid_until: str | None = None,
        proposal_information: str | None = None,
    ) -> dict[str, object]:
        values: dict[str, object | None] = {
            "customfield_10142": forecast_date,
            "customfield_10141": {"value": probability} if probability else None,
            "customfield_10140": next_follow_up_date,
            "priority": {"name": priority} if priority else None,
            "customfield_10100": {"value": billing} if billing else None,
            "customfield_10131": {"value": payment_days} if payment_days else None,
            "customfield_10132": {"value": payment_method} if payment_method else None,
            "customfield_10139": proposal_valid_until,
            "customfield_10144": proposal_information,
        }
        fields = {field: value for field, value in values.items() if value is not None}
        return self._transition_issue(
            issue_key,
            self.transition_ids["generate_new_proposal"],
            fields,
        )

    def list_issue_attachments(self, issue_key: str) -> dict[str, object]:
        key = self._encoded_issue_key(issue_key)
        response = self._request(
            "GET",
            f"/rest/api/3/issue/{key}",
            params={"fieldsByKeys": "true", "fields": "attachment", "expand": "names"},
        )
        data = self._json(response)
        fields = data.get("fields", {})
        attachments = fields.get("attachment", []) if isinstance(fields, dict) else []
        if not isinstance(attachments, list):
            raise JiraConnectorError("Jira returned an invalid attachment list.")
        return {
            "issue_key": issue_key,
            "attachments": [
                {
                    field: attachment[field]
                    for field in ("id", "filename", "mimeType", "size", "created")
                    if field in attachment
                }
                for attachment in attachments
                if isinstance(attachment, dict)
            ],
        }

    def download_issue_attachment(self, issue_key: str, attachment_id: str) -> dict[str, object]:
        attachment_list = self.list_issue_attachments(issue_key)["attachments"]
        if not any(str(item.get("id")) == attachment_id for item in attachment_list):
            raise JiraConnectorError("The attachment does not belong to the specified Jira issue.")

        content = bytearray()
        content_type = "application/octet-stream"
        path = f"/rest/api/3/attachment/content/{quote(attachment_id, safe='')}"
        try:
            with self._client.stream("GET", path) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", content_type)
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > self.attachment_max_bytes:
                        raise JiraConnectorError(
                            f"Attachment exceeds the configured "
                            f"{self.attachment_max_bytes}-byte limit."
                        )
                    content.extend(chunk)
        except httpx.HTTPStatusError as exc:
            raise JiraConnectorError(
                f"Jira API returned HTTP {exc.response.status_code} for GET {path}."
            ) from exc
        except httpx.RequestError as exc:
            raise JiraConnectorError(f"Could not reach the Jira API for GET {path}.") from exc
        return {
            "issue_key": issue_key,
            "attachment_id": attachment_id,
            "content_type": content_type,
            "content_base64": base64.b64encode(content).decode("ascii"),
        }

    def add_internal_comment(self, issue_key: str, comment: str) -> dict[str, object]:
        self._require_write_enabled()
        key = self._encoded_issue_key(issue_key)
        response = self._request(
            "POST",
            f"/rest/servicedeskapi/request/{key}/comment",
            json={"body": comment, "public": False},
        )
        if response.content:
            return self._json(response)
        return {"issue_key": issue_key, "added": True, "public": False}

    def list_assets_schemas(
        self,
        start_at: int = 0,
        max_results: int = 50,
        include_counts: bool = False,
    ) -> dict[str, object]:
        params: dict[str, object] = {"startAt": start_at, "maxResults": max_results}
        if include_counts:
            params["includeCounts"] = "true"
        response = self._assets_request(
            "GET",
            f"/jsm/assets/workspace/{quote(self._resolve_workspace_id(), safe='')}"
            "/v1/objectschema/list",
            params=params,
        )
        return self._json(response)

    def get_assets_object_types(self, objectschema_id: str) -> dict[str, object]:
        response = self._assets_request(
            "GET",
            f"/jsm/assets/workspace/{quote(self._resolve_workspace_id(), safe='')}"
            f"/v1/objectschema/{quote(objectschema_id, safe='')}/objecttypes",
        )
        return self._json(response)

    def get_assets_cloud_id(self) -> dict[str, str]:
        return {"cloud_id": self._resolve_cloud_id()}

    def get_assets_workspaces(self) -> dict[str, object]:
        response = self._request("GET", "/rest/servicedeskapi/assets/workspace")
        data = self._json(response)
        workspaces = data.get("values", data.get("workspaces", []))
        if isinstance(workspaces, list):
            workspace_ids = [
                item.get("workspaceId")
                for item in workspaces
                if isinstance(item, dict) and isinstance(item.get("workspaceId"), str)
            ]
            if len(workspace_ids) == 1:
                self.assets_workspace_id = workspace_ids[0]
        return data

    def search_assets_products_by_manufacturer(
        self,
        manufacturer: str,
        workspace_id: str | None = None,
    ) -> dict[str, object]:
        cloud_id = self._resolve_cloud_id()
        resolved_workspace = workspace_id or self._resolve_workspace_id()
        safe_manufacturer = manufacturer.replace("\\", "\\\\").replace('"', '\\"')
        if any(ord(character) < 32 for character in safe_manufacturer):
            raise JiraConnectorError("Manufacturer search contains unsupported control characters.")
        query = (
            f'objectTypeId = {self.assets_product_object_type_id} AND '
            f'Fabricante like "{safe_manufacturer}"'
        )
        response = self._assets_request(
            "POST",
            f"/jsm/assets/workspace/{quote(resolved_workspace, safe='')}/v1/object/aql",
            json={"qlQuery": query},
            cloud_id=cloud_id,
        )
        return self._json(response)

    def send_item_to_purchasing(
        self,
        issue_key: str,
        product_object_id: str,
        quantity: int,
        quotation_classification: str,
        period_months: str,
        price_type: str,
        reference: str = "-",
    ) -> dict[str, object]:
        workspace_id = self._resolve_workspace_id()
        object_id = product_object_id
        fields = {
            "customfield_11828": [
                {
                    "workspaceId": workspace_id,
                    "id": f"{workspace_id}:{object_id}",
                    "objectId": object_id,
                }
            ],
            "customfield_10093": quantity,
            "customfield_11348": reference,
            "customfield_10846": {"value": quotation_classification},
            "customfield_13268": {"value": period_months},
            "customfield_10243": {"value": price_type},
        }
        return self._transition_issue(
            issue_key,
            self.transition_ids["send_item_to_purchasing"],
            fields,
        )

    def get_proposal_item_values(self, issue_key: str) -> dict[str, object]:
        key = self._encoded_issue_key(issue_key)
        response = self._request(
            "GET",
            f"/rest/api/3/issue/{key}",
            params={
                "fieldsByKeys": "true",
                "expand": "names,editmeta",
                "fields": self.PROPOSAL_ITEM_FIELDS,
            },
        )
        return self._json(response)

    def set_proposal_item_price(
        self,
        issue_key: str,
        unit_price: float,
        likely_scenario: bool,
    ) -> dict[str, object]:
        return self._transition_issue(
            issue_key,
            self.transition_ids["set_proposal_item_price"],
            {
                "customfield_10173": unit_price,
                "customfield_13868": {"value": "Sim" if likely_scenario else "Não"},
            },
        )

    def _transition_issue(
        self,
        issue_key: str,
        transition_id: str,
        fields: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self._require_write_enabled()
        key = self._encoded_issue_key(issue_key)
        available_response = self._request(
            "GET",
            f"/rest/api/3/issue/{key}/transitions",
        )
        available = self._json(available_response).get("transitions", [])
        if not isinstance(available, list) or not any(
            isinstance(item, dict) and str(item.get("id")) == transition_id
            for item in available
        ):
            raise JiraConnectorError(
                f"Configured Jira transition '{transition_id}' is not available for this issue."
            )

        body: dict[str, object] = {"transition": {"id": transition_id}}
        if fields:
            body["fields"] = fields
        response = self._request(
            "POST",
            f"/rest/api/3/issue/{key}/transitions",
            json=body,
        )
        if response.content:
            return self._json(response)
        return {"issue_key": issue_key, "transition_id": transition_id, "transitioned": True}

    def _resolve_cloud_id(self) -> str:
        if self.assets_cloud_id:
            return self.assets_cloud_id
        data = self._json(self._request("GET", "/_edge/tenant_info"))
        cloud_id = data.get("cloudId") or data.get("cloud_id")
        if not isinstance(cloud_id, str) or not cloud_id:
            raise JiraConnectorError("Jira tenant info did not contain a Cloud ID.")
        self.assets_cloud_id = cloud_id
        return cloud_id

    def _resolve_workspace_id(self) -> str:
        if self.assets_workspace_id:
            return self.assets_workspace_id
        data = self._json(self._request("GET", "/rest/servicedeskapi/assets/workspace"))
        workspaces = data.get("values", data.get("workspaces", []))
        if not isinstance(workspaces, list):
            raise JiraConnectorError("Jira Assets returned an invalid workspace list.")
        workspace_ids = [
            item.get("workspaceId")
            for item in workspaces
            if isinstance(item, dict) and isinstance(item.get("workspaceId"), str)
        ]
        if len(workspace_ids) != 1:
            raise JiraConnectorError(
                "Configure JIRA_ASSETS_WORKSPACE_ID when Jira returns zero or multiple workspaces."
            )
        self.assets_workspace_id = workspace_ids[0]
        return workspace_ids[0]

    def _assets_request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        cloud_id = kwargs.pop("cloud_id", None) or self._resolve_cloud_id()
        client = self._get_assets_client()
        try:
            response = client.request(
                method,
                f"{self.ASSETS_API_ROOT}/{quote(str(cloud_id), safe='')}{path}",
                **kwargs,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            raise JiraConnectorError(
                f"Jira Assets API returned HTTP {exc.response.status_code} for "
                f"{method} {path.split('?')[0]}."
            ) from exc
        except httpx.RequestError as exc:
            raise JiraConnectorError(
                f"Could not reach the Jira Assets API for {method} {path.split('?')[0]}."
            ) from exc

    def _get_assets_client(self) -> httpx.Client:
        if self._assets_client is None:
            headers = {"Accept": "application/json"}
            auth = None
            if self.assets_access_token:
                headers["Authorization"] = f"Bearer {self.assets_access_token}"
            else:
                auth = httpx.BasicAuth(self._jira_api_email, self._jira_api_token)
            self._assets_client = httpx.Client(
                auth=auth,
                headers=headers,
                timeout=15.0,
                transport=self._transport,
                follow_redirects=True,
            )
        return self._assets_client

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, object]:
        try:
            data = response.json()
        except ValueError as exc:
            raise JiraConnectorError("Jira returned a non-JSON response.") from exc
        if not isinstance(data, dict):
            raise JiraConnectorError("Jira returned an unexpected response shape.")
        return data

    def _encoded_issue_key(self, issue_key: str) -> str:
        self._validate_issue_key(issue_key)
        project_key = issue_key.split("-", maxsplit=1)[0].upper()
        if project_key not in self.allowed_projects:
            raise JiraConnectorError(
                f"Issue project '{project_key}' is not included in JIRA_ALLOWED_PROJECT_KEYS."
            )
        return quote(issue_key, safe="")

    @staticmethod
    def _validate_issue_key(issue_key: str) -> None:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", issue_key):
            raise JiraConnectorError("Jira issue key has an invalid format.")

    def _require_write_enabled(self) -> None:
        if not self.allow_write_operations:
            raise JiraConnectorError(
                "Jira write operations are disabled; set JIRA_ENABLE_WRITE_OPERATIONS=true "
                "only after validating the target Jira project."
            )

    def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            raise JiraConnectorError(
                f"Jira API returned HTTP {exc.response.status_code} for "
                f"{method} {path.split('?')[0]}."
            ) from exc
        except httpx.RequestError as exc:
            raise JiraConnectorError(
                f"Could not reach the Jira API for {method} {path.split('?')[0]}."
            ) from exc


def get_jira_connector(settings: Settings) -> JiraConnector | None:
    """Return a configured connector, or None when credentials are not supplied."""
    if not settings.jira_api_email and not settings.jira_api_token:
        return None
    return JiraConnector(settings)
