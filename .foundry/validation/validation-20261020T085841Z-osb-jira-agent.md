# Microsoft Foundry Agent Validation

## Summary

**Report ID:** `20261020T085841Z`<br>
**Hosted agent:** osb-jira-agent<br>
**Agent path:** /home/sandro/_prj/devopsvanilla/loonar/loonar-morpheus-sysint/osb-jira-agent<br>
**Generated:** 2026-10-20T08:58:41Z

**Results:** 4 passed · 1 inconclusive · 6 not applicable

## Passed checks

<details>
<summary>Do not instruct agents to bypass controls or fabricate success</summary>

- **Rule:** `AGT-001`
- **Level:** warning

#### Rationale

Operative agent instructions must not authorize fabricated outcomes, unrestricted consequential actions, or bypasses of runtime controls and required approvals.

#### Source code

`src/agent/triage_agent.py:138-147`, `src/agent/prompts.py:7-33`

#### Details

The entry point passes TRIAGE_SYSTEM_PROMPT to the model. The operative prompt requires verified tool results, prohibits inventing data, bounds authorized commercial actions, says not to bypass disabled writes, and requires reporting failures rather than claiming success. No instruction to bypass controls or fabricate outcomes was found.

#### Guidance

- [Tool best practices for agents](<https://learn.microsoft.com/azure/foundry/agents/concepts/tool-best-practice>)
- [Responsible AI transparency note for agents](<https://learn.microsoft.com/azure/foundry/responsible-ai/agents/transparency-note>)

</details>

<details>
<summary>Do not override platform-managed runtime configuration</summary>

- **Rule:** `CFG-001`
- **Level:** warning

#### Rationale

Overriding platform-injected FOUNDRY_* or AGENT_* runtime variables can break hosted-agent behavior.

#### Source code

`azure.yaml:25-68`, `src/hosted_agent/main.py:1-40`

#### Details

The selected service's deployed environmentVariables and entry point do not assign reserved FOUNDRY_* or AGENT_* names. JIRA_AGENT_ACCOUNT_ID is a JIRA_AGENT_* application variable, not an AGENT_* runtime variable.

#### Guidance

- [Review platform environment variables](<https://learn.microsoft.com/azure/foundry/agents/how-to/configure-hosted-agent-env-variables#review-platform-environment-variables>)

</details>

<details>
<summary>Keep declared protocols consistent with runtime handlers</summary>

- **Rule:** `PROTO-001`
- **Level:** warning

#### Rationale

Declared hosted-agent protocols must match the deployed handlers.

#### Source code

`azure.yaml:18-24`, `src/hosted_agent/main.py:6-20`

#### Details

azure.yaml declares the Invocations protocol and selects src/hosted_agent/main.py as the entry point. The entry point constructs InvocationAgentServerHost and registers handle_invocation with @app.invoke_handler, matching the declared protocol.

#### Guidance

- [Hosted-agent protocol endpoints](<https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agent-contract#protocol-endpoints>)
- [Add a protocol adapter](<https://learn.microsoft.com/azure/foundry/agents/how-to/add-protocol-adapter>)

</details>

<details>
<summary>Use recommended Foundry hosted-agent SDKs</summary>

- **Rule:** `SDK-002`
- **Level:** recommendation

#### Rationale

Approved Foundry hosting packages reduce custom protocol code.

#### Source code

`pyproject.toml:8`, `requirements.txt:26`

#### Details

The selected service resolves to the approved Python hosting dependency azure-ai-agentserver-invocations, declared in pyproject.toml and pinned in requirements.txt. No unapproved agent or hosting SDK was found in the selected dependency manifests.

#### Guidance

- [Python hosted-agent framework samples](<https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/hosted-agents>)
- [.NET hosted-agent framework samples](<https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/csharp/hosted-agents>)
- [Python LangGraph hosting samples](<https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/hosted-agents/langgraph>)

</details>

## Inconclusive

<details>
<summary>Enable supported tracing for hosted agents</summary>

- **Rule:** `OBS-001`
- **Level:** recommendation

#### Rationale

Tracing connects agent, model and tool operations to an inspectable telemetry destination.

#### Source code

`azure.yaml:25-68`, `src/agent/triage_agent.py:7-23`

#### Details

The selected azure.yaml service does not declare APPLICATIONINSIGHTS_CONNECTION_STRING, OTEL_EXPORTER_OTLP_ENDPOINT, or a signal-specific OTLP endpoint. Local code obtains an OpenTelemetry tracer, but the inspected repository configuration does not establish a supported exporter and destination. Automatic hosting or project-level tracing may be configured externally and cannot be confirmed from these files.

#### Guidance

- [Configure hosted-agent telemetry](<https://learn.microsoft.com/azure/foundry/agents/how-to/configure-hosted-agent-telemetry>)
- [Set up tracing for agents](<https://learn.microsoft.com/azure/foundry/observability/how-to/trace-agent-setup>)

</details>

## Not applicable

<details>
<summary>Preserve private-only access in repository-managed recovery</summary>

- **Rule:** `NET-001`
- **Level:** warning

#### Rationale

Automatically opening public access or sending private workload data to a public fallback during recovery defeats an explicitly configured private-only access boundary.

#### Source code

`terraform/modules/ai_foundry/main.tf:23`

#### Details

No private-only access boundary is established for the selected hosted-agent service. The repository's linked Foundry resource configuration explicitly enables public network access; no private-only contract for this hosted service was found.

#### Guidance

- [Foundry hosted-agent virtual networks](<https://learn.microsoft.com/azure/foundry/agents/how-to/virtual-networks>)
- [Private-network hosted-agent security boundaries](<https://github.com/microsoft/Foundry-Agent-Solution-Templates/blob/main/private-network-hosted-agent/docs/security.md>)

</details>

<details>
<summary>Configure and access MCP through Foundry Toolbox</summary>

- **Rule:** `TOOL-001`
- **Level:** recommendation

#### Rationale

Foundry Toolbox centralizes MCP configuration, authentication, credential handling, and policy enforcement while allowing tools to be updated without changing hosted-agent code.

#### Details

The selected hosted-agent entry point and its associated configuration use Jira and Confluence APIs directly; no MCP server connection is established in the inspected service.

#### Guidance

- [Agent Framework Foundry Toolbox sample](<https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/hosted-agents/agent-framework/responses/04-foundry-toolbox>)
- [LangGraph Foundry Toolbox sample](<https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/hosted-agents/langgraph/responses/02-langgraph-toolbox>)

</details>

<details>
<summary>Use AI Gateway for required rate limits</summary>

- **Rule:** `AIGW-001`
- **Level:** recommendation

#### Rationale

Azure API Management AI Gateway can enforce model token or request limits and tool-call limits before traffic reaches backends.

#### Source code

`src/agent/triage_agent.py:147-153`, `src/config.py:69`

#### Details

No model token/request rate limit or tool-call rate-limit requirement is established in the selected service configuration. The per-response max_output_tokens and per-execution max_tool_calls caps are not evidence of a rate-limit requirement.

#### Guidance

- [APIM hosted-agent solution template](<https://github.com/microsoft/Foundry-Agent-Solution-Templates/tree/main/apim-hosted-agent>)

</details>

<details>
<summary>Use consistent Microsoft Agent Framework dependencies</summary>

- **Rule:** `SDK-001`
- **Level:** recommendation

#### Rationale

Consistent Agent Framework declarations and imports prevent avoidable dependency mismatches; other supported frameworks remain valid.

#### Source code

`pyproject.toml:8-19`, `src/hosted_agent/main.py:6`

#### Details

The selected service declares the Invocations hosting package and uses Azure AI Projects/OpenAI clients; it does not declare or import Microsoft Agent Framework.

#### Guidance

- [Microsoft Agent Framework SDK overview](<https://learn.microsoft.com/azure/foundry/how-to/develop/sdk-overview#agent-framework>)
- [Choose a hosted-agent framework](<https://learn.microsoft.com/azure/foundry/agents/quickstarts/quickstart-deploy-own-code#choose-your-framework>)

</details>

<details>
<summary>Use Microsoft Entra authentication for Azure AI Search</summary>

- **Rule:** `AUTH-001`
- **Level:** recommendation

#### Rationale

Microsoft Entra authentication avoids distributing Search API keys and supports identity-based access control for hosted-agent retrieval.

#### Source code

`src/agent/prompts.py:16`, `src/kb/confluence_client.py:1`

#### Details

The selected service's knowledge retrieval path uses Confluence and local RAG code; no runtime Azure AI Search client or linked Search tool/connection is established.

#### Guidance

- [Azure AI Search role-based access control](<https://learn.microsoft.com/azure/search/search-security-rbac>)
- [Enterprise knowledge-agent connection configuration](<https://github.com/microsoft/Foundry-Agent-Solution-Templates/blob/main/enterprise-knowledge-agent/scripts/provision.py>)

</details>

<details>
<summary>Pin prebuilt hosted-agent images by digest</summary>

- **Rule:** `IMG-001`
- **Level:** recommendation

#### Rationale

An immutable image digest makes hosted-agent deployments reproducible and prevents a mutable tag from silently selecting different image contents.

#### Source code

`azure.yaml:18-21`

#### Details

The selected service uses codeConfiguration with remote_build dependency resolution and does not consume a prebuilt image.

#### Guidance

- [Azure Container Registry image tagging and versioning](<https://learn.microsoft.com/azure/container-registry/container-registry-image-tag-version>)
- [Private-network hosted-agent existing ACR scenario](<https://github.com/microsoft/Foundry-Agent-Solution-Templates/tree/main/private-network-hosted-agent/scenarios/existing-private-acr>)

</details>

## Limitation

This is an automated, repository-based best-practice review. It is not Microsoft certification, a compliance attestation, penetration testing, or validation of the deployed Azure environment.
