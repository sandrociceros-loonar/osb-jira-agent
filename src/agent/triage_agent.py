"""Triage Agent orchestration logic using Azure AI Projects SDK."""

import json
import re
from contextlib import nullcontext

from pydantic import ValidationError

from src.agent.foundry_client import get_foundry_manager
from src.agent.prompts import TRIAGE_SYSTEM_PROMPT, format_triage_user_prompt
from src.config import get_settings
from src.jira.connector import get_jira_connector
from src.models.agent_result import (
    AgentExecutionResult,
    TriageDecision,
)
from src.models.jira_webhook import JiraWebhookPayload
from src.utils.logger import setup_logger

logger = setup_logger("triage-agent")


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

            user_prompt = format_triage_user_prompt(
                issue_key=issue_key,
                summary=issue.fields.summary,
                description=issue.fields.get_description_text(),
                reporter=reporter_name,
                current_priority=priority_name,
                current_status=status_name,
                issue_type=issuetype_name,
            )

            openai_client = self.foundry_manager.get_openai_client()
            jira_connector = get_jira_connector(self.settings)
            actions: list[str] = []
            with jira_connector if jira_connector is not None else nullcontext():
                if self.settings.model_provider in {"foundry-local", "ollama"}:
                    if jira_connector is None:
                        logger.info(
                            "Conector Jira não configurado; ferramentas Jira indisponíveis."
                        )
                    response, tool_actions = self._run_local_chat_completion(
                        openai_client,
                        user_prompt,
                        jira_connector,
                    )
                    actions.extend(tool_actions)
                    assistant_content = response.choices[0].message.content or ""
                else:
                    if jira_connector is None:
                        logger.info(
                            "Conector Jira não configurado; ferramentas Jira indisponíveis."
                        )
                        response = openai_client.responses.create(
                            model=self.settings.azure_ai_model_deployment_name,
                            instructions=TRIAGE_SYSTEM_PROMPT,
                            input=user_prompt,
                        )
                    else:
                        tool_schemas = jira_connector.available_tool_schemas()
                        response = openai_client.responses.create(
                            model=self.settings.azure_ai_model_deployment_name,
                            instructions=TRIAGE_SYSTEM_PROMPT,
                            input=user_prompt,
                            tools=tool_schemas,
                            tool_choice="auto",
                            parallel_tool_calls=False,
                            max_tool_calls=self.settings.azure_ai_max_tool_calls,
                        )
                        response, tool_actions = self._run_jira_tool_calls(
                            openai_client,
                            response,
                            jira_connector,
                            tool_schemas,
                        )
                        actions.extend(tool_actions)

                    assistant_content = getattr(response, "output_text", "")
                if not assistant_content:
                    raise ValueError("O modelo retornou uma resposta sem texto.")
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

    def _run_jira_tool_calls(
        self,
        openai_client: object,
        response: object,
        jira_connector: object,
        tool_schemas: list[dict[str, object]],
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
                raise ValueError("O agente excedeu o limite configurado de chamadas de ferramentas.")

            tool_outputs = []
            for call in calls:
                name = getattr(call, "name", "")
                call_id = getattr(call, "call_id", "")
                try:
                    arguments = json.loads(getattr(call, "arguments", ""))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"O agente enviou JSON inválido para a ferramenta '{name}'.") from exc
                if not isinstance(arguments, dict):
                    raise ValueError(f"Os argumentos da ferramenta '{name}' devem ser um objeto JSON.")

                result = jira_connector.execute_tool(name, arguments)
                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result, ensure_ascii=False),
                    }
                )
                completed_tool_actions.append(f"Ferramenta Jira executada: {name}.")
                calls_used += 1

            response = openai_client.responses.create(
                model=self.settings.azure_ai_model_deployment_name,
                instructions=TRIAGE_SYSTEM_PROMPT,
                previous_response_id=response.id,
                input=tool_outputs,
                tools=tool_schemas,
                tool_choice="auto",
                parallel_tool_calls=False,
                max_tool_calls=self.settings.azure_ai_max_tool_calls,
            )

    def _run_local_chat_completion(
        self,
        openai_client: object,
        user_prompt: str,
        jira_connector: object | None,
    ) -> tuple[object, list[str]]:
        """Executa o ciclo Chat Completions usado pelos modelos locais."""
        messages: list[dict[str, object]] = [
            {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
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
            }
            if self.settings.model_provider == "ollama":
                request.update(max_tokens=1024, extra_body={"think": False})
            if tools:
                request.update(tools=tools, tool_choice="auto")
            response = openai_client.chat.completions.create(**request)
            message = response.choices[0].message
            calls = message.tool_calls or []
            if not calls:
                return response, completed_tool_actions
            if jira_connector is None:
                raise ValueError("O modelo local solicitou ferramentas sem conector Jira.")
            if calls_used + len(calls) > self.settings.azure_ai_max_tool_calls:
                raise ValueError("O agente excedeu o limite configurado de chamadas de ferramentas.")

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

                result = jira_connector.execute_tool(name, arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                completed_tool_actions.append(f"Ferramenta Jira executada: {name}.")
                calls_used += 1
