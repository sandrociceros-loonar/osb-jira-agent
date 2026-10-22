"""Tests for the Bash Jira transaction log parser."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "parse_jira_transactions.sh"


def _parse(lines: list[str], *arguments: str) -> dict[str, object]:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--format", "json", *arguments],
        input="\n".join(lines) + "\n",
        capture_output=True,
        check=True,
        text=True,
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required by the Bash parser")
def test_parser_groups_invocation_events_by_transaction_and_issue():
    lines = [
        "2026-10-21T10:00:00 [INFO] [hosted-agent] [INVOCATION_RECEIVED] "
        '{"event_tag":"INVOCATION_RECEIVED","transaction_id":"tx-1"}',
        "2026-10-21T10:00:01 [INFO] [jira-webhook-handler] [WEBHOOK_RECEIVED] "
        '{"event_tag":"WEBHOOK_RECEIVED","transaction_id":"tx-1",'
        '"issue_key":"OP-123","source":"foundry_hosted_agent",'
        '"webhook_event":"comment_created"}',
        "2026-10-21T10:00:05 [INFO] [jira-webhook-handler] [WEBHOOK_RESULT] "
        '{"event_tag":"WEBHOOK_RESULT","transaction_id":"tx-1",'
        '"issue_key":"OP-123","status":"processed","status_code":200,'
        '"duration_ms":3900,"run_id":"resp-1",'
        '"actions_taken":["Lead atualizado"]}',
        "2026-10-21T10:00:06 [INFO] [hosted-agent] [INVOCATION_COMPLETED] "
        '{"event_tag":"INVOCATION_COMPLETED","transaction_id":"tx-1",'
        '"status_code":200}',
        "2026-10-21T11:00:00 [INFO] [jira-webhook-handler] [WEBHOOK_RECEIVED] "
        '{"event_tag":"WEBHOOK_RECEIVED","transaction_id":"tx-2",'
        '"issue_key":"OP-123","webhook_event":"issue_updated"}',
        "2026-10-21T11:00:03 [INFO] [jira-webhook-handler] [WEBHOOK_RESULT] "
        '{"event_tag":"WEBHOOK_RESULT","transaction_id":"tx-2",'
        '"issue_key":"OP-123","status":"failed","status_code":500}',
        "2026-10-21T12:00:00 [INFO] [jira-webhook-handler] [WEBHOOK_RECEIVED] "
        '{"event_tag":"WEBHOOK_RECEIVED","issue_key":"OP-456",'
        '"webhook_event":"jira:issue_created"}',
    ]

    report = _parse(lines)

    assert [issue["issue_key"] for issue in report["issues"]] == ["OP-123", "OP-456"]
    lead = report["issues"][0]
    assert lead["event_count"] == 6
    assert lead["uncorrelated_event_count"] == 0
    assert [run["transaction_id"] for run in lead["transactions"]] == ["tx-1", "tx-2"]
    assert lead["transactions"][0]["status"] == "processed"
    assert lead["transactions"][0]["run_id"] == "resp-1"
    assert lead["transactions"][0]["events"][0]["event_tag"] == "INVOCATION_RECEIVED"
    assert lead["transactions"][0]["events"][-1]["event_tag"] == "INVOCATION_COMPLETED"
    assert lead["transactions"][0]["started_at"] == "2026-10-21T10:00:00"
    assert lead["transactions"][1]["status_code"] == 500
    assert lead["status"] == "failed"
    assert report["unassigned_events"] == []


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required by the Bash parser")
def test_parser_keeps_legacy_events_in_timeline_without_guessing_transactions():
    lines = [
        '[WEBHOOK_RECEIVED] {"event_tag":"WEBHOOK_RECEIVED","issue_key":"OP-123"}',
        '[WEBHOOK_RESULT] {"event_tag":"WEBHOOK_RESULT","issue_key":"OP-123","status":"processed"}',
    ]

    lead = _parse(lines)["issues"][0]

    assert lead["event_count"] == 2
    assert lead["uncorrelated_event_count"] == 2
    assert lead["transactions"] == []


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required by the Bash parser")
def test_parser_treats_blank_transaction_id_as_missing():
    lines = [
        '[WEBHOOK_RECEIVED] {"event_tag":"WEBHOOK_RECEIVED","issue_key":"OP-123",'
        '"transaction_id":""}',
        '[WEBHOOK_RESULT] {"event_tag":"WEBHOOK_RESULT","issue_key":"OP-123",'
        '"transaction_id":"","status":"processed"}',
    ]

    lead = _parse(lines)["issues"][0]

    assert lead["uncorrelated_event_count"] == 2
    assert lead["transactions"] == []


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required by the Bash parser")
def test_parser_reads_application_insights_custom_dimensions_and_filters_issue():
    lines = [
        '{"timestamp":"2026-10-21T10:00:00Z",'
        '"customDimensions":{"event_tag":"WEBHOOK_RESULT",'
        '"issue_key":"OP-123","transaction_id":"tx-1","status":"processed"}}',
        '{"timestamp":"2026-10-21T10:00:01Z",'
        '"customDimensions":{"event_tag":"WEBHOOK_RESULT",'
        '"issue_key":"OP-456","transaction_id":"tx-2","status":"failed"}}',
    ]

    report = _parse(lines, "--issue-key", "op-123")

    assert len(report["issues"]) == 1
    assert report["issues"][0]["issue_key"] == "OP-123"


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required by the Bash parser")
def test_parser_keeps_orphaned_correlated_logs_visible():
    lines = [
        "2026-10-21T10:00:00 [INFO] [hosted-agent] "
        "[transaction_id=tx-orphan] Preparando conexão Jira.",
    ]

    report = _parse(lines)

    assert report["issues"] == []
    assert report["unassigned_events"][0]["transaction_id"] == "tx-orphan"
    assert report["unassigned_events"][0]["message"] == "Preparando conexão Jira."
    assert report["unassigned_events"][0]["timestamp"] == "2026-10-21T10:00:00"


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required by the Bash parser")
def test_parser_text_mode_summarizes_transaction():
    lines = [
        '[WEBHOOK_RECEIVED] {"event_tag":"WEBHOOK_RECEIVED","issue_key":"OP-111",'
        '"transaction_id":"tx-demo","source":"foundry_hosted_agent"}',
        '[WEBHOOK_RESULT] {"event_tag":"WEBHOOK_RESULT","issue_key":"OP-111",'
        '"transaction_id":"tx-demo","status":"processed","status_code":200,'
        '"duration_ms":123,"actions_taken":["Lead atualizada"]}',
    ]
    result = subprocess.run(
        ["bash", str(SCRIPT), "--issue-key", "OP-111"],
        input="\n".join(lines) + "\n",
        capture_output=True,
        check=True,
        text=True,
    )

    assert "Lead OP-111 | eventos=2 | execuções correlacionadas=1" in result.stdout
    assert "Execução tx-demo: processed (200), duração=123 ms" in result.stdout
    assert "- Lead atualizada" in result.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required by the Bash parser")
def test_parser_reads_app_insights_tables_structure():
    table_payload = {
        "tables": [
            {
                "name": "PrimaryResult",
                "columns": [
                    {"name": "timestamp", "type": "datetime"},
                    {"name": "eventTag", "type": "string"},
                    {"name": "issue_key", "type": "string"},
                    {"name": "source", "type": "string"},
                    {"name": "status", "type": "string"},
                    {"name": "statusCode", "type": "int"},
                    {"name": "durationMs", "type": "real"},
                    {"name": "operation_Id", "type": "string"},
                    {"name": "actions_taken", "type": "dynamic"},
                ],
                "rows": [
                    [
                        "2026-10-21T10:00:00Z",
                        "WEBHOOK_RECEIVED",
                        "OP-8989",
                        "azure_function",
                        "Open Lead",
                        None,
                        None,
                        "op-id-123",
                        None,
                    ],
                    [
                        "2026-10-21T10:00:05Z",
                        "WEBHOOK_RESULT",
                        "OP-8989",
                        "azure_function",
                        "processed",
                        200,
                        4500.0,
                        "op-id-123",
                        json.dumps(["Comentário enviado"]),
                    ],
                ],
            }
        ]
    }
    result = subprocess.run(
        ["bash", str(SCRIPT), "--format", "json", "--issue-key", "OP-8989"],
        input=json.dumps(table_payload),
        capture_output=True,
        check=True,
        text=True,
    )
    report = json.loads(result.stdout)
    assert len(report["issues"]) == 1
    lead = report["issues"][0]
    assert lead["issue_key"] == "OP-8989"
    assert lead["event_count"] == 2
    assert lead["status"] == "processed"
    assert lead["transactions"][0]["transaction_id"] == "op-id-123"
    assert lead["transactions"][0]["actions_taken"] == ["Comentário enviado"]


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required by the Bash parser")
def test_parser_outputs_valid_otlp_spans():
    lines = [
        '[WEBHOOK_RECEIVED] {"event_tag":"WEBHOOK_RECEIVED","issue_key":"OP-8989",'
        '"transaction_id":"d77e2bccca000492f00a60170a8ada01","source":"azure_function"}',
        '[WEBHOOK_RESULT] {"event_tag":"WEBHOOK_RESULT","issue_key":"OP-8989",'
        '"transaction_id":"d77e2bccca000492f00a60170a8ada01","status":"processed",'
        '"status_code":200,"duration_ms":1500,"actions_taken":["Lead atualizada"]}',
    ]
    result = subprocess.run(
        ["bash", str(SCRIPT), "--format", "otlp", "--issue-key", "OP-8989"],
        input="\n".join(lines) + "\n",
        capture_output=True,
        check=True,
        text=True,
    )
    otlp = json.loads(result.stdout)
    assert "resourceSpans" in otlp
    spans = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 3  # 1 root span + 2 child event spans
    root_span = spans[0]
    assert root_span["traceId"] == "d77e2bccca000492f00a60170a8ada01"
    assert len(root_span["spanId"]) == 16
    assert root_span["parentSpanId"] == ""
    assert root_span["name"] == "Jira Lead OP-8989 (Execução d77e2bcc)"
    assert spans[1]["parentSpanId"] == root_span["spanId"]
    assert spans[1]["name"] == "WEBHOOK_RECEIVED"
    assert spans[2]["parentSpanId"] == root_span["spanId"]
    assert spans[2]["name"] == "WEBHOOK_RESULT"
