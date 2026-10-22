"""Triage Agent orchestration logic using Azure AI Projects SDK."""

import json
import re
from contextlib import nullcontext

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import ValidationError

from src.agent.foundry_client import get_foundry_manager
from src.agent.prompts import (
    SNAPSHOT_OFFLINE_SYSTEM_PROMPT,
    TRIAGE_SYSTEM_PROMPT,
    format_triage_user_prompt,
)
from src.config import get_settings
from src.jira.connector import JiraConnector, JiraConnectorError, get_jira_connector
from src.models.agent_result import (
    AgentExecutionResult,
    TriageDecision,
)
from src.models.jira_webhook import JiraComment, JiraWebhookPayload
from src.utils.logger import log_debug_content, setup_logger

logger = setup_logger("triage-agent")
tracer = trace.get_tracer(__name__)


class JiraTriageAgent:
    """Orquestrador do Agente de Triagem no Azure AI Foundry."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.foundry_manager = get_foundry_manager()

    def parse_decision_from_text(self, text: str) -> TriageDecision:
        """Extrai e valida o JSON de decisão da resposta textual do modelo."""
        # Remove blocos markdown como ```json ... ```
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        clean_text = json_match.group(1) if json_match else text.strip()

        try:
            data = json.loads(clean_text)
            return TriageDecision(**data)
        except (json.JSONDecodeError, ValidationError):
            logger.warning("Resposta do agente não corresponde ao schema comercial.")
            raise ValueError(
                "A resposta do agente não contém um resultado comercial válido."
            ) from None

    def process_ticket(self, webhook_payload: JiraWebhookPayload) -> AgentExecutionResult:
        """Processa a issue comercial recebida no webhook e retorna o resultado estruturado."""
        issue = webhook_payload.issue
        issue_key = issue.key

        logger.info("Iniciando processamento da issue comercial: %s", issue_key)

        try:
            # Prepara prompt
            reporter_name = issue.fields.reporter.display_name if issue.fields.reporter else None
            priority_name = issue.fields.priority.name if issue.fields.priority else None
            status_name = issue.fields.status.name if issue.fields.status else None
            issuetype_name = issue.fields.issuetype.name if issue.fields.issuetype else None
            incoming_comment = (
                webhook_payload.comment.get_body_text() if webhook_payload.comment else None
            )
            request_details = issue.fields.get_request_details_text(
                self.settings.jira_request_details_field_id
            )

            user_prompt = format_triage_user_prompt(
                issue_key=issue_key,
                summary=issue.fields.summary,
                description=issue.fields.get_description_text(),
                reporter=reporter_name,
                current_priority=priority_name,
                current_status=status_name,
                issue_type=issuetype_name,
                webhook_event=webhook_payload.webhook_event,
                incoming_comment=incoming_comment,
                request_details=request_details,
                custom_fields={
                    field_name: (
                        value[:300] + "..."
                        if isinstance(value, str) and len(value) > 300
                        else value
                    )
                    for field_name, value in (issue.fields.model_extra or {}).items()
                    if field_name.startswith("customfield_")
                    and value is not None
                    and value != []
                    and value != {}
                    and value != "{}"
                    and not (
                        isinstance(value, str)
                        and (not value.strip() or value.strip().startswith("{panel:"))
                    )
                },
            )
            self._log_debug_content(
                issue_key,
                "model_input",
                {"instructions": TRIAGE_SYSTEM_PROMPT, "input": user_prompt},
            )

            if self._is_agent_comment(webhook_payload.comment):
                return self._skipped_agent_comment(issue_key)

            jira_connector = get_jira_connector(self.settings)
            actions: list[str] = []
            with jira_connector if jira_connector is not None else nullcontext():
                if (
                    jira_connector is not None
                    and issue_key.split("-", maxsplit=1)[0].upper()
                    == self.settings.jira_lead_project_key.upper()
                    and self._is_lead_issue(
                        issuetype_name,
                        issue.fields.issuetype.id if issue.fields.issuetype else None,
                    )
                ):
                    latest_comment_result = jira_connector.get_latest_issue_comment(issue_key)
                    self._log_debug_content(
                        issue_key,
                        "jira_latest_comment",
                        latest_comment_result,
                    )
                    latest_comment = latest_comment_result.get("latest_comment")
                    if self._is_agent_comment(latest_comment, jira_connector):
                        return self._skipped_agent_comment(issue_key)

                openai_client = self.foundry_manager.get_openai_client()
                if self.settings.model_provider in {"foundry-local", "ollama"}:
                    if jira_connector is None:
                        logger.info(
                            "Conector Jira não configurado; ferramentas Jira indisponíveis."
                        )
                    response, tool_actions = self._run_local_chat_completion(
                        openai_client,
                        user_prompt,
                        jira_connector,
                        issue_key,
                    )
                    actions.extend(tool_actions)
                    assistant_content = response.choices[0].message.content or ""
                else:
                    if jira_connector is None:
                        logger.info(
                            "Conector Jira não configurado; ferramentas Jira indisponíveis."
                        )
                        self._log_debug_content(
                            issue_key,
                            "model_request",
                            {
                                "model": self.settings.azure_ai_model_deployment_name,
                                "instructions": SNAPSHOT_OFFLINE_SYSTEM_PROMPT,
                                "input": user_prompt,
                            },
                        )
                        response = openai_client.responses.create(
                            model=self.settings.azure_ai_model_deployment_name,
                            instructions=SNAPSHOT_OFFLINE_SYSTEM_PROMPT,
                            input=user_prompt,
                            max_output_tokens=6000,
                            reasoning={"effort": "low"},
                        )
                    else:
                        tool_schemas = jira_connector.available_tool_schemas()
                        self._log_debug_content(
                            issue_key,
                            "model_request",
                            {
                                "model": self.settings.azure_ai_model_deployment_name,
                                "instructions": TRIAGE_SYSTEM_PROMPT,
                                "input": user_prompt,
                                "tools": tool_schemas,
                            },
                        )
                        response = openai_client.responses.create(
                            model=self.settings.azure_ai_model_deployment_name,
                            instructions=TRIAGE_SYSTEM_PROMPT,
                            input=user_prompt,
                            tools=tool_schemas,
                            tool_choice="auto",
                            parallel_tool_calls=False,
                            max_tool_calls=self.settings.azure_ai_max_tool_calls,
                            max_output_tokens=6000,
                            reasoning={"effort": "low"},
                        )
                        response, tool_actions = self._run_jira_tool_calls(
                            openai_client,
                            response,
                            jira_connector,
                            tool_schemas,
                            issue_key,
                        )
                        actions.extend(tool_actions)

                    usage = getattr(response, "usage", None)
                    if usage:
                        logger.info(
                            "Tokens consumidos (Foundry/OpenAI): input=%s, output=%s, total=%s",
                            getattr(usage, "input_tokens", None),
                            getattr(usage, "output_tokens", None),
                            getattr(usage, "total_tokens", None),
                        )

                    assistant_content = getattr(response, "output_text", "")
                if not assistant_content:
                    raise ValueError("O modelo retornou uma resposta sem texto.")
                self._log_debug_content(issue_key, "model_output", assistant_content)
                decision = self.parse_decision_from_text(assistant_content)

                actions = [
                    f"Solicitação comercial classificada como '{decision.category.value}'."
                ] + actions
                if decision.priority is not None:
                    actions.append(
                        f"Prioridade sugerida para a issue: '{decision.priority.value}'."
                    )
                if decision.assigned_team:
                    actions.append(f"Equipe sugerida para a issue: '{decision.assigned_team}'.")
                if decision.suggested_status:
                    actions.append(
                        f"Status sugerido para transição: '{decision.suggested_status}'."
                    )
                if decision.should_auto_close:
                    actions.append("A decisão sugere encerramento automático.")

                if jira_connector is None:
                    logger.info(
                        "Conector Jira não configurado; nenhuma alteração aplicada à issue."
                    )
                    actions.append(
                        "Conector Jira não configurado; nenhuma alteração foi aplicada à issue."
                    )
                elif self.settings.jira_allow_write_operations:
                    actions.extend(jira_connector.apply_decision(issue_key, decision))
                else:
                    actions.append(
                        "Escritas de metadados desabilitadas; "
                        "configure JIRA_ENABLE_WRITE_OPERATIONS para habilitá-las."
                    )

            return AgentExecutionResult(
                issue_key=issue_key,
                success=True,
                decision=decision,
                actions_taken=actions,
                run_id=getattr(response, "id", None),
            )

        except Exception as exc:
            logger.error(
                "Erro ao processar issue %s com o agente Foundry: %s",
                issue_key,
                exc,
                exc_info=True,
            )
            return AgentExecutionResult(
                issue_key=issue_key,
                success=False,
                error_message=str(exc),
            )

    def _is_agent_comment(
        self,
        comment: object,
        jira_connector: JiraConnector | None = None,
    ) -> bool:
        if isinstance(comment, JiraComment):
            author_id = comment.author.account_id if comment.author else None
            body = comment.get_body_text()
        elif isinstance(comment, dict):
            author = comment.get("author")
            author_id = (
                author.get("accountId") or author.get("account_id")
                if isinstance(author, dict)
                else None
            )
            try:
                body = JiraComment.model_validate(comment).get_body_text()
            except ValidationError:
                body = ""
        else:
            return False

        if self.settings.jira_agent_account_id and author_id:
            return author_id == self.settings.jira_agent_account_id
        if body.startswith(JiraConnector.AGENT_COMMENT_PREFIX):
            return True
        if author_id and jira_connector is not None:
            return jira_connector.is_authenticated_user_comment(comment)
        return False

    def _is_lead_issue(self, issue_type_name: str | None, issue_type_id: str | None) -> bool:
        return issue_type_id == self.settings.jira_lead_issue_type_id or (
            issue_type_name is not None and issue_type_name.casefold().startswith("lead")
        )

    @staticmethod
    def _skipped_agent_comment(issue_key: str) -> AgentExecutionResult:
        return AgentExecutionResult(
            issue_key=issue_key,
            success=True,
            actions_taken=["Evento ignorado: o comentário mais recente foi publicado pelo agente."],
        )

    def _run_jira_tool_calls(
        self,
        openai_client: object,
        response: object,
        jira_connector: object,
        tool_schemas: list[dict[str, object]],
        issue_key: str,
    ) -> tuple[object, list[str]]:
        """Executes only registered Jira functions and continues the Responses turn."""
        completed_tool_actions: list[str] = []
        calls_used = 0
        while True:
            calls = [
                item
                for item in getattr(response, "output", [])
                if getattr(item, "type", None) == "function_call"
            ]
            if not calls:
                return response, completed_tool_actions
            if calls_used + len(calls) > self.settings.azure_ai_max_tool_calls:
                raise ValueError(
                    "O agente excedeu o limite configurado de chamadas de ferramentas."
                )

            tool_outputs = []
            for call in calls:
                name = getattr(call, "name", "")
                call_id = getattr(call, "call_id", "")
                try:
                    arguments = json.loads(getattr(call, "arguments", ""))
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"O agente enviou JSON inválido para a ferramenta '{name}'."
                    ) from exc
                if not isinstance(arguments, dict):
                    raise ValueError(
                        f"Os argumentos da ferramenta '{name}' devem ser um objeto JSON."
                    )

                self._log_debug_content(
                    issue_key,
                    "tool_call",
                    {"name": name, "arguments": arguments},
                )
                result = self._execute_jira_tool(jira_connector, name, arguments)
                self._log_debug_content(
                    issue_key,
                    "tool_result",
                    {"name": name, "result": result},
                )
                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result, ensure_ascii=False),
                    }
                )
                if (
                    name == "add_public_comment"
                    and isinstance(result, dict)
                    and result.get("transition_id")
                ):
                    completed_tool_actions.append(
                        f"Ação Jira executada: Mensagem para o Cliente (Transição {result['transition_id']})."
                    )
                elif isinstance(result, dict) and result.get("pending"):
                    completed_tool_actions.append(
                        "Campo Fabricante não atualizado; continuar o fluxo sem bloqueio."
                    )
                else:
                    completed_tool_actions.append(f"Ferramenta Jira executada: {name}.")
                calls_used += 1

            self._log_debug_content(
                issue_key,
                "model_request",
                {
                    "model": self.settings.azure_ai_model_deployment_name,
                    "instructions": TRIAGE_SYSTEM_PROMPT,
                    "previous_response_id": response.id,
                    "input": tool_outputs,
                    "tools": tool_schemas,
                },
            )
            response = openai_client.responses.create(
                model=self.settings.azure_ai_model_deployment_name,
                instructions=TRIAGE_SYSTEM_PROMPT,
                previous_response_id=response.id,
                input=tool_outputs,
                tools=tool_schemas,
                tool_choice="auto",
                parallel_tool_calls=False,
                max_tool_calls=self.settings.azure_ai_max_tool_calls,
                max_output_tokens=6000,
                reasoning={"effort": "low"},
            )
            usage = getattr(response, "usage", None)
            if usage:
                logger.info(
                    "Tokens consumidos (Foundry/OpenAI tool loop): input=%s, output=%s, total=%s",
                    getattr(usage, "input_tokens", None),
                    getattr(usage, "output_tokens", None),
                    getattr(usage, "total_tokens", None),
                )

    def _run_local_chat_completion(
        self,
        openai_client: object,
        user_prompt: str,
        jira_connector: object | None,
        issue_key: str,
    ) -> tuple[object, list[str]]:
        """Executa o ciclo Chat Completions usado pelos modelos locais."""
        system_content = (
            SNAPSHOT_OFFLINE_SYSTEM_PROMPT if jira_connector is None else TRIAGE_SYSTEM_PROMPT
        )
        messages: list[dict[str, object]] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_prompt},
        ]
        tools: list[dict[str, object]] = []
        if jira_connector is not None:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": schema["name"],
                        "description": schema["description"],
                        "parameters": schema["parameters"],
                    },
                }
                for schema in jira_connector.available_tool_schemas()
            ]

        completed_tool_actions: list[str] = []
        calls_used = 0
        model_name = (
            self.settings.ollama_model_name
            if self.settings.model_provider == "ollama"
            else self.settings.foundry_local_model_alias
        )
        while True:
            request: dict[str, object] = {
                "model": model_name,
                "messages": messages,
                "max_tokens": 1500,
                "n": 1,
            }
            if self.settings.model_provider == "ollama":
                request.update(max_tokens=1024, extra_body={"think": False})
            if tools:
                request.update(tools=tools, tool_choice="auto")
            self._log_debug_content(issue_key, "model_request", request)
            response = openai_client.chat.completions.create(**request)
            message = response.choices[0].message
            dump_message = getattr(message, "model_dump", None)
            if callable(dump_message):
                response_content = dump_message(exclude_none=True)
            else:
                response_content = {
                    "content": getattr(message, "content", None),
                    "tool_calls": [
                        {
                            "id": getattr(call, "id", None),
                            "name": getattr(getattr(call, "function", None), "name", None),
                            "arguments": getattr(
                                getattr(call, "function", None),
                                "arguments",
                                None,
                            ),
                        }
                        for call in getattr(message, "tool_calls", []) or []
                    ],
                }
            self._log_debug_content(
                issue_key,
                "model_response",
                response_content,
            )
            calls = message.tool_calls or []
            if not calls:
                return response, completed_tool_actions
            if jira_connector is None:
                raise ValueError("O modelo local solicitou ferramentas sem conector Jira.")
            if calls_used + len(calls) > self.settings.azure_ai_max_tool_calls:
                raise ValueError(
                    "O agente excedeu o limite configurado de chamadas de ferramentas."
                )

            messages.append(message.model_dump(exclude_none=True))
            for call in calls:
                name = call.function.name
                try:
                    arguments = json.loads(call.function.arguments)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"O agente enviou JSON inválido para a ferramenta '{name}'."
                    ) from exc
                if not isinstance(arguments, dict):
                    raise ValueError(
                        f"Os argumentos da ferramenta '{name}' devem ser um objeto JSON."
                    )

                self._log_debug_content(
                    issue_key,
                    "tool_call",
                    {"name": name, "arguments": arguments},
                )
                result = self._execute_jira_tool(jira_connector, name, arguments)
                self._log_debug_content(
                    issue_key,
                    "tool_result",
                    {"name": name, "result": result},
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                if (
                    name == "add_public_comment"
                    and isinstance(result, dict)
                    and result.get("transition_id")
                ):
                    completed_tool_actions.append(
                        f"Ação Jira executada: Mensagem para o Cliente (Transição {result['transition_id']})."
                    )
                elif isinstance(result, dict) and result.get("pending"):
                    completed_tool_actions.append(
                        "Campo Fabricante não atualizado; continuar o fluxo sem bloqueio."
                    )
                else:
                    completed_tool_actions.append(f"Ferramenta Jira executada: {name}.")
                calls_used += 1

    def _log_debug_content(self, issue_key: str, stage: str, content: object) -> None:
        log_debug_content(
            logger,
            issue_key=issue_key,
            stage=stage,
            content=content,
            enabled=self.settings.jira_debug_log_content,
            configured_issue_key=self.settings.jira_debug_log_content_issue_key,
            expires_at=self.settings.jira_debug_log_content_until,
        )

    @staticmethod
    def _execute_jira_tool(
        jira_connector: JiraConnector,
        name: str,
        arguments: dict[str, object],
    ) -> object:
        with tracer.start_as_current_span(
            "jira.execute_tool",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("gen_ai.operation.name", "execute_tool")
            span.set_attribute("gen_ai.tool.name", name)
            try:
                return jira_connector.execute_tool(name, arguments)
            except JiraConnectorError as exc:
                span.set_status(Status(StatusCode.ERROR))
                issue_key = arguments.get("issue_key", "-") if isinstance(arguments, dict) else "-"
                logger.warning(
                    "Erro ao executar ferramenta Jira '%s' (%s): %s", name, issue_key, exc
                )
                return {"error": str(exc), "success": False}
            except Exception:
                span.set_status(Status(StatusCode.ERROR))
                raise
