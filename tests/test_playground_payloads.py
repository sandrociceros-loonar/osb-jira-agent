"""Validate the Jira webhook examples used by the Hosted Agent Playground."""

from pathlib import Path

import pytest

from src.agent.prompts import format_triage_user_prompt
from src.models.jira_webhook import JiraWebhookPayload

PLAYGROUND_DIR = Path(__file__).parent / "playground"
PLAYGROUND_PAYLOADS = sorted(PLAYGROUND_DIR.glob("*.json"))


@pytest.mark.parametrize("payload_path", PLAYGROUND_PAYLOADS, ids=lambda path: path.stem)
def test_playground_payload_is_valid_and_reaches_the_agent_prompt(payload_path: Path):
    payload = JiraWebhookPayload.model_validate_json(payload_path.read_text(encoding="utf-8"))
    fields = payload.issue.fields
    custom_fields = {
        field_name: value
        for field_name, value in (fields.model_extra or {}).items()
        if field_name.startswith("customfield_") and value is not None
    }

    user_prompt = format_triage_user_prompt(
        issue_key=payload.issue.key,
        summary=fields.summary,
        description=fields.get_description_text(),
        reporter=fields.reporter.display_name if fields.reporter else None,
        current_priority=fields.priority.name if fields.priority else None,
        current_status=fields.status.name if fields.status else None,
        issue_type=fields.issuetype.name if fields.issuetype else None,
        webhook_event=payload.webhook_event,
        incoming_comment=payload.comment.get_body_text() if payload.comment else None,
        custom_fields=custom_fields,
    )

    assert payload.issue.key in user_prompt
    assert fields.summary in user_prompt
    if fields.get_description_text():
        assert fields.get_description_text() in user_prompt
    if payload.comment and payload.comment.get_body_text():
        assert payload.comment.get_body_text() in user_prompt
    for field_name in custom_fields:
        assert field_name in user_prompt
