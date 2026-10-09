"""Triage Agent orchestration logic using Azure AI Projects SDK."""

import json
import re
from typing import Any

from src.agent.foundry_client import get_foundry_manager
from src.agent.prompts import TRIAGE_SYSTEM_PROMPT, format_triage_user_prompt
from src.config import get_settings
from src.models.agent_result import (
    AgentExecutionResult,
    TriageCategory,
    TriageDecision,
    TriagePriority,
)
from src.models.jira_webhook import JiraWebhookPayload
from src.utils.logger import setup_logger

logger = setup_logger("triage-agent")


class JiraTriageAgent:
    """Orquestrador do Agente de Triagem no Azure AI Foundry."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.foundry_manager = get_foundry_manager()

    def get_or_create_agent(self, client: Any) -> Any:
        """Obtém o agente configurado ou cria um novo com as instruções de ITSM."""
        if self.settings.azure_ai_agent_id:
            logger.info("Recuperando agente existente por ID: %s", self.settings.azure_ai_agent_id)
            return client.agents.get_agent(self.settings.azure_ai_agent_id)

        # Procura por agente com o nome padrão na lista
        try:
            agents_list = client.agents.list_agents()
            for agent in getattr(agents_list, "data", []):
                if getattr(agent, "name", "") == "osb-jira-triage-agent":
                    logger.info("Agente 'osb-jira-triage-agent' encontrado (ID: %s)", agent.id)
                    return agent
        except Exception as exc:
            logger.warning("Não foi possível listar agentes existentes: %s", exc)

        # Cria um novo agente
        logger.info(
            "Criando novo agente 'osb-jira-triage-agent' com modelo '%s'",
            self.settings.azure_ai_model_deployment_name,
        )
        agent = client.agents.create_agent(
            model=self.settings.azure_ai_model_deployment_name,
            name="osb-jira-triage-agent",
            instructions=TRIAGE_SYSTEM_PROMPT,
        )
        return agent

    def parse_decision_from_text(self, text: str) -> TriageDecision:
        """Extrai e valida o JSON de decisão da resposta textual do modelo."""
        # Remove blocos markdown como ```json ... ```
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        clean_text = json_match.group(1) if json_match else text.strip()

        try:
            data = json.loads(clean_text)
            return TriageDecision(**data)
        except Exception as exc:
            logger.warning(
                "Falha ao deserializar JSON da resposta do agente: %s. Texto: %s", exc, text
            )
            # Fallback seguro
            return TriageDecision(
                category=TriageCategory.GENERAL_SUPPORT,
                priority=TriagePriority.MEDIUM,
                assigned_team="ServiceDesk-L1",
                reasoning=f"Classificação baseada em texto livre do agente: {text[:200]}",
                internal_comment="Triagem automatizada via Azure Foundry Agent.",
            )

    def process_ticket(self, webhook_payload: JiraWebhookPayload) -> AgentExecutionResult:
        """Processa a issue do webhook, invoca o agente e retorna a decisão estruturada."""
        issue = webhook_payload.issue
        issue_key = issue.key

        logger.info("Iniciando processamento do chamado: %s", issue_key)

        try:
            client = self.foundry_manager.get_client()
            agent = self.get_or_create_agent(client)

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

            # Cria thread e mensagem
            thread = client.agents.create_thread()
            logger.debug("Thread criada: %s para issue %s", thread.id, issue_key)

            client.agents.create_message(
                thread_id=thread.id,
                role="user",
                content=user_prompt,
            )

            # Executa a thread até finalização
            run = client.agents.create_and_process_run(
                thread_id=thread.id,
                assistant_id=agent.id,
            )

            # Coleta as mensagens geradas
            messages = client.agents.list_messages(thread_id=thread.id)
            assistant_content = ""

            for msg in reversed(getattr(messages, "data", [])):
                if getattr(msg, "role", "") == "assistant":
                    for block in getattr(msg, "content", []):
                        text_val = getattr(getattr(block, "text", None), "value", None)
                        if text_val:
                            assistant_content += text_val + "\n"

            decision = self.parse_decision_from_text(assistant_content)

            actions = [
                f"Classificado como '{decision.category.value}' com prioridade '{decision.priority.value}'",
                f"Encaminhado para a fila/equipe: '{decision.assigned_team}'",
            ]
            if decision.suggested_status:
                actions.append(f"Status sugerido para transição: '{decision.suggested_status}'")
            if decision.should_auto_close:
                actions.append("Marcado para encerramento automático")

            return AgentExecutionResult(
                issue_key=issue_key,
                success=True,
                decision=decision,
                actions_taken=actions,
                thread_id=thread.id,
                run_id=getattr(run, "id", None),
            )

        except Exception as exc:
            logger.error(
                "Erro ao processar chamado %s com o agente Foundry: %s",
                issue_key,
                exc,
                exc_info=True,
            )
            return AgentExecutionResult(
                issue_key=issue_key,
                success=False,
                error_message=str(exc),
            )
