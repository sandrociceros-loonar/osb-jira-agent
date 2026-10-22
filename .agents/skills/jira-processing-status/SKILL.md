---
name: jira-processing-status
description: "Find the latest Jira webhook processing status for an issue and diagnose agent failures using Application Insights. Use when asked whether a Jira comment, email, webhook, or issue was processed, to check the last agent status, or to investigate an OP-1234 processing error."
argument-hint: "Jira issue key, e.g. OP-8888; optional time range"
---

# Jira Processing Status and Diagnosis

Use this workflow to report the latest recorded processing result for one Jira issue and diagnose errors without exposing customer content.

## Procedure

1. Resolve the Jira issue key from the request. If absent, ask for it. Use the last 24 hours by default; honor an explicit time range.
2. Resolve the active Azure environment and its Application Insights component. Prefer the project's selected `azd` environment and Azure resource configuration. The development component has previously been named `osbjira-proj-development-appinsights-5763` in resource group `rg-osb-jira-agent-dev`; verify it is still the correct target before querying. If multiple environments are plausible, ask which one.
3. Query the Function's structured `WEBHOOK_*` records in Application Insights `traces`, filtering by the exact issue key. Use the Azure `monitor_resource_log_query` tool when available, passing the resource ID and subscription explicitly. Otherwise use `az monitor app-insights query` with the selected component and a bounded time range.
4. Display the KQL query before executing it. Start with this query, replacing the issue key and time range:

   ```kql
   traces
   | where timestamp > ago(24h)
   | where message contains "[WEBHOOK_"
   | extend eventTag = extract(@"\[(WEBHOOK_RESULT|WEBHOOK_ACCEPTED_ASYNC|WEBHOOK_RECEIVED)\]", 1, message)
   | extend payload = parse_json(extract(@"\[(?:WEBHOOK_RESULT|WEBHOOK_ACCEPTED_ASYNC|WEBHOOK_RECEIVED)\]\s+(\{.*\})", 1, message))
   | where tostring(payload.issue_key) == "OP-8888"
   | project timestamp, eventTag,
       source = tostring(payload.source),
       status = tostring(payload.status),
       statusCode = toint(payload.status_code),
       webhookEvent = tostring(payload.webhook_event),
       success = tostring(payload.success),
       runId = tostring(payload.run_id),
       durationMs = todouble(payload.duration_ms),
       operation_Id,
       diagnostic = tostring(coalesce(payload.error_message, payload.reason))
   | order by timestamp desc
   | take 20
   ```

   `WEBHOOK_RESULT` is the processing outcome. `WEBHOOK_ACCEPTED_ASYNC` means the HTTP request was accepted while background processing continued; it is not evidence that processing succeeded. `WEBHOOK_RECEIVED` confirms receipt only. Report the newest result and distinguish it from later receipt/acceptance records.
5. If the newest record failed, inspect only correlated technical diagnostics: use `operation_Id` to query `exceptions` or related Function traces, and inspect the Function's invocation logs if needed. Do not query or display `WEBHOOK_RAW_PAYLOAD`, `AGENT_DEBUG_CONTENT`, comments, comment previews, issue summaries, reporter names, headers, credentials, or full model messages. Treat free-form `reason`/exception text as potentially sensitive; redact it before sharing and summarize only the technical cause.
6. If no result appears, check whether the requested range and environment are correct, then widen the time range only as needed. Mention telemetry ingestion delay as a possibility. A missing `WEBHOOK_RESULT` is **unknown**, not success. Invalid or unauthenticated webhooks may not contain an issue key and cannot always be correlated by issue.
7. Summarize in Portuguese unless the user used another language: issue key, environment, latest result timestamp, source, event, status, HTTP status, and concise technical diagnosis or why status is unknown. State clearly whether the event was merely received, accepted asynchronously, or completed. Recommend the smallest next diagnostic or remediation step.

## Foundry Hosted Agent

The Jira webhook normally enters through the Azure Function. If the request specifically concerns a direct Foundry Hosted Agent invocation, follow the Microsoft Foundry `trace` and `troubleshoot` workflows instead; hosted-agent session logs are not a substitute for the Function's issue-keyed `WEBHOOK_RESULT`.

## Safety

- This is a read-only diagnostic workflow. Never replay a webhook, invoke an agent with a production issue, or modify Jira while checking status.
- Always bound telemetry queries by time and issue key. Display the query before running it.
- Never print secrets or expose customer comments or payload contents in the answer.
- `AGENT_DEBUG_CONTENT` may contain full Jira payloads, prompts, model replies, and tool data; never include it in status queries, diagnostics, or summaries.
