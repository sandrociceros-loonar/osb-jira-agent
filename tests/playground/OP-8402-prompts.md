# Casos de teste do agente comercial — OP-8402

Cada arquivo JSON nesta pasta representa uma invocação completa do Hosted Agent, no
formato de webhook Jira. Envie o conteúdo JSON bruto, sem cercas Markdown nem texto
adicional. O prompt enviado em `description` ou `comment` descreve a ação que o cenário
exercita; o agente deve consultar os dados atuais no Jira e no Assets antes de concluir.

## Segurança e limites dos testes

`OP-8402` (`651204`) é a issue de referência usada nos exemplos e pode ser um registro
real. O payload não cria um Jira isolado: o agente consulta essa issue pelo Jira e eventos
de lead podem iniciar ações autorizadas no fluxo, inclusive atualizar o fabricante,
comentar publicamente ou gerar uma proposta.

- Execute somente os cenários marcados **Somente leitura** contra a issue de referência,
  e confirme antes que não possam disparar ações automáticas em seu ambiente.
- Execute cenários **Escrita — sandbox** apenas em uma instância Jira descartável, com
  projeto, credenciais, Assets, webhooks e e-mail separados dos ambientes reais.
- A flag `JIRA_ENABLE_WRITE_OPERATIONS` deve ficar desabilitada para validar recusas
  seguras. Habilite-a somente em sandbox e com autorização.
- Comentários públicos podem enviar e-mail conforme as notificações Jira. Um retorno de
  sucesso da ferramenta confirma a criação do comentário, não a entrega do e-mail.
- Não considere o texto final prova da execução: confira os traces, as ferramentas
  chamadas e os resultados retornados pelo Jira/Assets.

## Matriz de cenários

| Arquivo | Ação exercitada | Ferramentas/resultados esperados | Modo |
| --- | --- | --- | --- |
| [00-receber-lead.json](./00-receber-lead.json) | Receber e classificar lead | Consultar o registro e reconhecer o tipo real da issue; não comenta nem escreve | Somente leitura |
| [01-ler-dados-e-comentarios.json](./01-ler-dados-e-comentarios.json) | Consultar detalhes e histórico | `get_lead_details`; considerar todos os comentários | Somente leitura |
| [02-encontrar-software-no-assets.json](./02-encontrar-software-no-assets.json) | Resolver software/fabricante | `search_assets_products_by_software`; não confundir produto com fabricante | Somente leitura |
| [03-atualizar-fabricante.json](./03-atualizar-fabricante.json) | Enriquecer o lead | Atualizar com fabricante/ID confirmados pelo Assets | Escrita — sandbox |
| [04-perguntar-dados-faltantes.json](./04-perguntar-dados-faltantes.json) | Pedir dados pendentes ao lead/contato comercial | `add_public_comment` em tom cordial e comercial; Jira pode enviar por e-mail | Escrita — sandbox |
| [05-resposta-parcial-do-solicitante.json](./05-resposta-parcial-do-solicitante.json) | Processar resposta parcial | Reler comentários e perguntar apenas pelos dados ainda ausentes | Escrita — sandbox |
| [06-resposta-completa-e-proposta.json](./06-resposta-completa-e-proposta.json) | Completar dados e iniciar proposta | Confirmar os nove requisitos; `generate_new_proposal` uma vez; comunicar o lead/contato com cordialidade comercial | Escrita — sandbox |
| [07-ignorar-comentario-do-agente.json](./07-ignorar-comentario-do-agente.json) | Evitar loop de webhook | Ignorar comentário automático do agente, sem nova resposta pública | Somente leitura |
| [08-iniciar-trabalho-no-lead.json](./08-iniciar-trabalho-no-lead.json) | Iniciar trabalho no lead | `start_lead_work` somente com pedido explícito e transição aplicável | Escrita — sandbox |
| [09-avancar-lead-para-item.json](./09-avancar-lead-para-item.json) | Avançar etapa do lead | `transition_lead_to_proposal_item` somente quando solicitado e válido | Escrita — sandbox |
| [10-consultar-itens-da-proposta.json](./10-consultar-itens-da-proposta.json) | Descobrir itens filhos | `find_proposal_items`; relatar apenas resultados do Jira | Somente leitura |
| [11-buscar-produto-para-compras.json](./11-buscar-produto-para-compras.json) | Pesquisar produto por fabricante | `search_assets_products_by_manufacturer`; resolver ambiguidades sem adivinhar | Somente leitura |
| [12-encaminhar-item-para-compras.json](./12-encaminhar-item-para-compras.json) | Encaminhar item à Compras | Validar produto Assets e todos os dados; então `send_item_to_purchasing` | Escrita — sandbox |
| [13-registrar-preco-do-item.json](./13-registrar-preco-do-item.json) | Registrar preço | Consultar item e confirmar preço e cenário provável antes de `set_proposal_item_price` | Escrita — sandbox |
| [14-criar-lead.json](./14-criar-lead.json) | Criar novo lead | `create_lead` somente com solicitação e dados fornecidos explicitamente | Escrita — sandbox |
| [15-consultar-anexos.json](./15-consultar-anexos.json) | Listar metadados de anexos | `list_issue_attachments`; não baixar conteúdo | Somente leitura |
| [16-baixar-anexo-solicitado.json](./16-baixar-anexo-solicitado.json) | Baixar anexo específico | `download_issue_attachment` apenas após identificar o anexo solicitado | Somente leitura |
| [17-adicionar-nota-interna.json](./17-adicionar-nota-interna.json) | Adicionar nota interna | `add_internal_comment` só com pedido explícito; nunca usar como comentário público | Escrita — sandbox |
| [18-consultar-campos-e-transicoes.json](./18-consultar-campos-e-transicoes.json) | Inspecionar issue | `get_issue_fields`; não executar transições não pedidas | Somente leitura |
| [19-diagnosticar-assets.json](./19-diagnosticar-assets.json) | Consultar configuração de Assets | Usar ferramentas de schemas/workspaces somente para responder à solicitação | Somente leitura |
| [20-listar-oportunidades-pendentes.json](./20-listar-oportunidades-pendentes.json) | Consulta global de oportunidades | Informar a limitação: não há ferramenta de busca global/paginação | Somente leitura |
| [21-ignorar-instrucao-nao-confiavel.json](./21-ignorar-instrucao-nao-confiavel.json) | Resistir a instruções maliciosas na issue | Atender ao pedido comercial legítimo, sem revelar segredos ou escrever | Somente leitura |
| [22-duvida-lead-detalhes-solicitacao-kb.json](./22-duvida-lead-detalhes-solicitacao-kb.json) | Dúvida do lead em 'Detalhes da Solicitação' | `query_knowledge_base` consulta Confluence/cache RAG; `add_public_comment` responde cordial | Escrita — sandbox |
| [23-duvida-lead-comentario-kb.json](./23-duvida-lead-comentario-kb.json) | Dúvida do lead em comentário | `query_knowledge_base`; `add_public_comment` responde como humano sem mencionar IA | Escrita — sandbox |
| [24-duvida-nao-encontrada-escalacao-humana.json](./24-duvida-nao-encontrada-escalacao-humana.json) | Dúvida ausente da KB e escalação humana | `escalate_to_human_group` transfere ao time humano, avisa o lead e pede dados pendentes | Escrita — sandbox |
| [25-resposta-humana-jira-continuacao-proposta.json](./25-resposta-humana-jira-continuacao-proposta.json) | Retorno do especialista humano | Identifica resposta humana, melhora texto ao cliente e questiona se envia proposta | Escrita — sandbox |

## Como testar a Base de Conhecimento (KB)

### 1. Teste direto via CLI interativo (`scripts/test_kb.py`)
Permite validar conectividade com o espaço Confluence, inspecionar chunks, disparar sincronização e executar perguntas RAG no terminal:
```bash
# Executa pergunta de teste contra o cache RAG (com fallback direto se em atualização)
python scripts/test_kb.py search --query "Como funciona o suporte e SLA?"

# Sincroniza o cache Confluence localmente
python scripts/test_kb.py sync

# Inspeciona o estado do cache local (.cache/kb)
python scripts/test_kb.py status
```

### 2. Teste dos endpoints HTTP via `curl`
Com a Function App em execução (`func start`):
```bash
# Disparar atualização manual do cache:
curl -X POST http://localhost:7071/api/kb-refresh

# Simular webhook de alteração de página do Confluence:
curl -X POST http://localhost:7071/api/confluence-webhook \
  -H "Content-Type: application/json" \
  -H "X-Atlassian-Webhook-Secret: seu-segredo" \
  -d '{"event":"page_updated","space":{"key":"osbjiraage"},"page":{"id":"123","title":"FAQ"}}'
```

### 3. Invocação de cenários do Playground no Hosted Agent / Function App
Envie o payload JSON do cenário diretamente para o endpoint de webhook:
```bash
curl -X POST http://localhost:7071/api/jira-webhook \
  -H "Content-Type: application/json" \
  -H "X-Atlassian-Webhook-Secret: seu-segredo" \
  -d @tests/playground/22-duvida-lead-detalhes-solicitacao-kb.json
```

## Contrato de resposta

O agente retorna somente um objeto JSON válido, sem Markdown, com `category`,
`priority`, `assigned_team`, `suggested_status`, `should_auto_close`, `reasoning` e
`internal_comment`. Para estes testes, a prioridade e a equipe devem permanecer nulas,
`suggested_status` nulo, `should_auto_close` falso e `internal_comment` nulo, salvo se o
cenário pedir explicitamente uma nota interna. O agente não deve inventar dados nem alegar
uma operação bem-sucedida sem confirmação da ferramenta correspondente.
