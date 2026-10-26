---
name: jira-lead-progress
description: "Diagnose full commercial lead progress, lifecycle timeline, and AI agent execution for Jira leads (e.g. OP-9023, OP-9046). Use when asked to diagnose lead progress, evaluate proposal generation evolution, audit agent reasoning/tools, investigate why a proposal was not created, or detect tool and workflow transition blockers in Application Insights."
argument-hint: "Jira issue key or URL (e.g. OP-9046), optional time range (default 30d)"
---

# Diagnóstico de Progresso e Ciclo de Vida de Leads Jira

Esta skill analisa o histórico completo e o progresso da atuação do Agente Comercial de IA sobre um lead Jira (ex.: `OP-9046`, `OP-9023`) a partir dos logs de execução e ferramentas gravados no Azure Application Insights.

---

## Quando Usar

- Diagnosticar até que ponto o agente evoluiu na qualificação ou geração de proposta de um lead comercial.
- Identificar o motivo técnico pelo qual uma proposta comercial não foi gerada ou não avançou no Jira.
- Auditar a sequência cronológica de eventos, raciocínios do modelo (`reasoning`) e ferramentas acionadas.
- Investigar recusas de transições de workflow do Jira (`TOOL_ERROR` / `transition not available`).
- Detectar falhas definitivas e validar se houve delegação para atendimento humano (`[AGENTE DE IA] ERRO NO PROCESSAMENTO`).

---

## Procedimento de Execução

### 1. Resolução dos Parâmetros
- **Chave da Issue**: Extraia a chave Jira do texto ou da URL (ex.: de `https://loonar-osb.atlassian.net/browse/OP-9046` extraia `OP-9046`).
- **Janela de Tempo**: Utilize `30d` por padrão para capturar todo o histórico do lead, ou utilize o período explicitado pelo usuário.

### 2. Coleta e Correlação via Script
Execute o script consolidado de telemetria do projeto:

```bash
bash scripts/parse_jira_transactions.sh --issue-key <ISSUE_KEY> --time-range <TIME_RANGE:-30d>
```

> [!TIP]
> O script correlaciona automaticamente cada transação aos seus respectivos eventos assíncronos (`WEBHOOK_RECEIVED` -> `WEBHOOK_ACCEPTED_ASYNC` -> `TOOL_ERROR` -> `WEBHOOK_RESULT`), capturando o raciocínio analítico (`reasoning`) e eventuais alertas de execução de ferramentas.

Se for necessária uma saída em formato estruturado para processamento posterior, utilize a opção `--format json`:
```bash
bash scripts/parse_jira_transactions.sh --issue-key <ISSUE_KEY> --time-range 30d --format json
```

---

## Roteiro de Avaliação do Ciclo de Vida do Lead

Compare o progresso do lead contra as etapas obrigatórias do fluxo comercial da Loonar (Coleção Bruno):

| Etapa | Operação | Critério de Sucesso | Ponto Típico de Falha |
|---|---|---|---|
| **1. Qualificação & Dúvidas** | `query_knowledge_base` | Dúvidas de produto/licença esclarecidas via RAG; critérios de dimensionamento solicitados. | Dúvida não encontrada na base (deve acionar `escalate_to_human_group`). |
| **2. Iniciar Trabalho (`Lead_02`)** | `start_lead_work` | Transição `2` executada em `Open Lead`, enviando `customfield_14975: {"value": "N.B. Licença nova"}`. | Issue não transicionada para `Working Lead`. |
| **3. Coleta de 9 Dados** | `add_public_comment` | Todos os 9 dados confirmados: forecast, probabilidade, próximo follow-up, prioridade, faturamento (Razão Social/CNPJ), prazo de pagamento, forma de pagamento, validade e dados do produto. | Faltam dados cadastrais (ex.: CNPJ) ou cliente não respondeu a todas as perguntas. |
| **4. Item da Proposta (`Lead_03`)** | `transition_lead_to_proposal_item` | Transição `21` acionada no lead para disparar a inclusão dos itens da proposta. | Agente tenta pular direto para a transição `3` sem acionar a transição `21`. |
| **5. Monitora Item (`Lead_04`)** | `find_proposal_items` | Consulta JQL `parent={{Key}}` confirma que o item de proposta filho foi criado. | Timeout ou tentativa de gerar proposta antes do item filho existir no Jira. |
| **6. Gerar Proposta (`Lead_05`)** | `generate_new_proposal` | Transição `3` acionada com sucesso no Jira com os campos comerciais preenchidos. | Erro `Configured Jira transition '3' is not available for this issue.` (ocorre se as etapas 4 e 5 não foram concluídas). |
| **7. Tratamento de Falha** | `escalate_to_human_group` | Comentário `[AGENTE DE IA] ERRO NO PROCESSAMENTO` registrado e issue atribuída à equipe humana. | Agente mascara o erro e afirma ao cliente que a proposta está em emissão. |

---

## Formato Padrão da Resposta

Apresente sempre o diagnóstico estruturado em língua portuguesa com as seguintes seções:

1. **Cabeçalho**: Chave da issue com link, ambiente do Application Insights e status atual.
2. **Linha do Tempo das Execuções**:
   - Cada execução agrupada cronologicamente (Data/Hora UTC, Categoria, Duração e Ferramentas).
   - Resumo claro do raciocínio (`reasoning`) do agente naquele ciclo.
   - Registro destacado de qualquer aviso ou erro de ferramenta (`ALERTA FERRAMENTA`).
3. **Estágio de Evolução Atingido**: Indicação exata de até onde o agente conseguiu avançar no funil (ex.: qualificação concluída, dados coletados, falha na transição).
4. **Causa Raiz do Bloqueio**: Explicação técnica e clara do motivo pelo qual a proposta não foi gerada ou o fluxo estagnou.
5. **Recomendações e Próximos Passos**: Instruções acionáveis para o operador comercial ou engenheiro destravar o lead no Jira.

---

## Diretrizes de Segurança

- Este é um fluxo exclusivamente de diagnóstico e leitura de telemetria.
- Nunca exiba tokens, credenciais, segredos, assinaturas ou headers confidenciais.
- Não dispare webhooks de produção nem modifique o Jira durante o diagnóstico.

