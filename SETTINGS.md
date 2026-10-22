# Arquivos de configuração

Este documento descreve os principais arquivos de configuração do repositório e em que etapa
cada um é utilizado. Os exemplos com sufixo `.example` são modelos: copie-os para o nome de
destino e preencha os valores do seu ambiente. Arquivos locais com credenciais não devem ser
versionados.

## Configuração da aplicação

| Arquivo | Uso | Quando é lido |
|---|---|---|
| [`.env.example`](./.env.example) → `.env` | Modelo de variáveis de ambiente da aplicação: provedor e deployment do modelo, Jira, Confluence, base de conhecimento, logging e ambiente. | No desenvolvimento local. `src/config.py` carrega `.env` com Pydantic Settings; variáveis de ambiente do processo também podem fornecer os valores. |
| [`local.settings.json.example`](./local.settings.json.example) → `local.settings.json` | Valores sob `Values` para o runtime do Azure Functions, incluindo `AzureWebJobsStorage`, `FUNCTIONS_WORKER_RUNTIME` e configurações da aplicação. | Quando o Azure Functions Core Tools executa a Function localmente, por exemplo com `func start`. Não é usado pelo Hosted Agent nem é o mecanismo de configuração da Function publicada. |
| [`src/config.py`](./src/config.py) | Declara nomes, aliases, valores padrão e validações das configurações consumidas pelo código. | Durante a inicialização da aplicação, seja na Function ou no Hosted Agent. Além de `.env`, recebe configurações injetadas pelo ambiente de execução. |
| [`host.json`](./host.json) | Configura o host Azure Functions, incluindo logging, sampling do Application Insights e pacote de extensões. | Quando o host da Function inicia localmente ou na Azure. Não contém configurações específicas de credenciais da aplicação. |

Os dois arquivos locais (`.env` e `local.settings.json`) podem conter as mesmas variáveis de
aplicação, mas são consumidos por mecanismos diferentes: `.env` pelo carregador da aplicação e
`local.settings.json` pelo host local do Azure Functions. Para produção, configure as variáveis
nos *App settings* da Function App, nas variáveis do Hosted Agent ou use o Key Vault, conforme o
componente. Não publique segredos em arquivos versionados.

### Integrações Jira e Confluence

| Grupo de configurações | Exemplos | Finalidade |
|---|---|---|
| Foundry e modelos locais | `MODEL_PROVIDER`, `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_AI_MODEL_DEPLOYMENT_NAME`, `FOUNDRY_LOCAL_*`, `OLLAMA_*` | Selecionam Azure Foundry, Foundry Local ou Ollama e indicam o deployment ou endpoint do modelo. |
| Jira | `JIRA_INSTANCE_URL`, `JIRA_PROJECT_KEY`, `JIRA_ALLOWED_PROJECT_KEYS`, `JIRA_TRANSITION_IDS` | Identificam a instância, os projetos permitidos e as transições de workflow. Os IDs de transição variam por instância. |
| Credenciais e escrita Jira | `JIRA_API_EMAIL`, `JIRA_API_TOKEN`, `JIRA_ENABLE_WRITE_OPERATIONS`, `JIRA_WEBHOOK_SECRET` | Autenticam chamadas à API e validam o webhook. Operações de escrita ficam desabilitadas por padrão. |
| Jira Assets | `JIRA_ASSETS_ACCESS_TOKEN`, `JIRA_ASSETS_CLOUD_ID`, `JIRA_ASSETS_WORKSPACE_ID`, `JIRA_ASSETS_PRODUCT_OBJECT_TYPE_ID` | Configuram a autenticação e o escopo das pesquisas de produtos no Assets. Alguns identificadores podem ser descobertos automaticamente quando omitidos. |
| Base de conhecimento | `CONFLUENCE_SPACE_URL`, `CONFLUENCE_BASE_URL`, `CONFLUENCE_SPACE_KEY`, `CONFLUENCE_API_EMAIL`, `CONFLUENCE_API_TOKEN` | Identificam e autenticam o acesso ao espaço Confluence usado pela base de conhecimento. Sem credenciais Confluence próprias, são usadas as credenciais Jira. |
| Webhook Confluence e comportamento da KB | `CONFLUENCE_WEBHOOK_SECRET`, `CONFLUENCE_WEBHOOK_SECRET_HEADER`, `KB_ENABLED`, `KB_CACHE_*`, `KB_MIN_CONFIDENCE_SCORE`, `KB_HUMAN_ESCALATION_*` | Protegem a entrada de eventos do Confluence e controlam habilitação, cache, confiança mínima e escalação humana. O segredo do webhook é usado somente pela Function. |
| Ajustes gerais | `LOG_LEVEL`, `ENVIRONMENT`, `JIRA_ATTACHMENT_MAX_BYTES`, `AZURE_AI_MAX_TOOL_CALLS` | Ajustam logs, ambiente e limites de execução. |
| Debug de conteúdo | `JIRA_DEBUG_LOG_CONTENT`, `JIRA_DEBUG_LOG_CONTENT_ISSUE_KEY`, `JIRA_DEBUG_LOG_CONTENT_UNTIL` | Habilitam logs completos do payload Jira, entradas/saídas do modelo e chamadas/resultados de ferramentas até uma expiração explícita. O escopo pode ser uma issue ou `*` para todas as issues. Requer `LOG_LEVEL=DEBUG`; chaves de credenciais são redigidas. Desabilitado por padrão. |

Para uma issue, configure `JIRA_DEBUG_LOG_CONTENT=true` e
`JIRA_DEBUG_LOG_CONTENT_ISSUE_KEY=OP-1234`. Para capturar todas as invocações com issue Jira,
use `JIRA_DEBUG_LOG_CONTENT_ISSUE_KEY=*`. Em ambos os casos, configure
`JIRA_DEBUG_LOG_CONTENT_UNTIL=<data-hora-UTC-futura>` (por exemplo, formato
`AAAA-MM-DDTHH:MM:SSZ`) e `LOG_LEVEL=DEBUG` no runtime desejado. A data de expiração precisa incluir fuso horário; ao
expirar, o conteúdo deixa de ser emitido mesmo que a flag permaneça ligada. Desligue a flag depois
da investigação. O conteúdo pode conter dados pessoais/comerciais e será
enviado ao destino de logs configurado; mantenha acesso e retenção restritos. A expiração interrompe
novos logs, mas não apaga os registros já enviados; eles permanecem conforme a retenção configurada.
Para uma Function local, configure também as duas chaves
`AzureFunctionsJobHost__logging__logLevel__*` do `local.settings.json.example` para `Debug`.

Os nomes e defaults completos são mantidos em [`src/config.py`](./src/config.py); os exemplos
distribuídos estão em [`.env.example`](./.env.example) e
[`local.settings.json.example`](./local.settings.json.example). Os valores do espaço
`osbjiraage` também são definidos nos defaults do Terraform. O Terraform configura a Function App
com a URL, a chave e os cabeçalhos e guarda o segredo do webhook no Key Vault. O token de API
Confluence fica vazio por padrão e a aplicação reutiliza `JIRA_API_EMAIL`/`JIRA_API_TOKEN`.
`confluence-api-token` só é necessário se um token Confluence diferente for adicionado
explicitamente ao Key Vault. O `azure.yaml` encaminha a URL, a chave e o e-mail Jira ao Hosted
Agent.

O segredo `CONFLUENCE_WEBHOOK_SECRET` deve ser configurado somente para a Function e para a regra
de automação do Confluence — não é necessário no Hosted Agent. A identidade do Hosted Agent
precisa da função **Key Vault Secrets User** no vault para ler o token Jira e Assets opcional.

## Hosted Agent e deploy

| Arquivo | Uso | Quando é utilizado |
|---|---|---|
| [`azure.yaml`](./azure.yaml) | Declara o serviço Hosted Agent, runtime Python, ponto de entrada, protocolo Invocations, recursos e variáveis de ambiente. | Pelo Azure Developer CLI (`azd`) durante a preparação e publicação do Hosted Agent. |
| [`.azure/config.json`](./.azure/config.json) | Guarda a seleção do ambiente padrão do `azd`. | Quando `azd` precisa determinar qual ambiente local está ativo. |
| [`requirements.txt`](./requirements.txt), [`pyproject.toml`](./pyproject.toml) e [`uv.lock`](./uv.lock) | `pyproject.toml` declara dependências e configura ferramentas; `uv.lock` fixa as versões; `requirements.txt` fornece dependências ao build remoto do Hosted Agent. | `uv sync` usa o manifesto e lockfile no desenvolvimento. Como `azure.yaml` usa resolução remota, mantenha `requirements.txt` sincronizado ao alterar dependências de runtime. |
| [`.funcignore`](./.funcignore) | Exclui arquivos locais, de desenvolvimento e outros itens do pacote da Function. | Durante a publicação ou empacotamento da Azure Function. |

O Hosted Agent e a Azure Function são entradas separadas. O `azure.yaml` publica o Hosted Agent;
`host.json` e `local.settings.json` pertencem ao ciclo do Azure Functions. A configuração de
ambiente publicada deve ser fornecida pelo serviço correspondente, não presumida a partir dos
arquivos locais. O `azure.yaml` define `CONFLUENCE_SPACE_URL`, `CONFLUENCE_BASE_URL` e
`CONFLUENCE_SPACE_KEY` para o Hosted Agent e herda `CONFLUENCE_API_EMAIL` de `JIRA_API_EMAIL`; para
a Function, o Terraform gera os App settings a partir de `terraform.tfvars`.

## Infraestrutura como código

| Arquivo | Uso | Quando é utilizado |
|---|---|---|
| [`terraform/terraform.tfvars.example`](./terraform/terraform.tfvars.example) → `terraform.tfvars` | Modelo de valores para assinatura, região, recursos, modelo Foundry e integração Jira. | Antes de executar `terraform plan` e `terraform apply` no ambiente de destino. |
| [`terraform/variables.tf`](./terraform/variables.tf) | Declara tipos, defaults e validações das entradas aceitas pelo Terraform. | Ao validar ou planejar a infraestrutura. |
| [`terraform/main.tf`](./terraform/main.tf), [`terraform/outputs.tf`](./terraform/outputs.tf) e `terraform/modules/` | Definem recursos, módulos, dependências e saídas da infraestrutura. | Durante operações Terraform no diretório `terraform/`. |

`terraform.tfvars` e o state Terraform podem conter dados sensíveis e são ignorados pelo Git.
Proteja o state e revise o plano antes de aplicar alterações. O Terraform provisiona infraestrutura;
ele não substitui as configurações de runtime de cada aplicação.

## Avaliações, CI e desenvolvimento

| Arquivo ou grupo | Uso | Quando é utilizado |
|---|---|---|
| [`eval.yaml`](./eval.yaml), [`.agent_configs/baseline/metadata.yaml`](./.agent_configs/baseline/metadata.yaml), `datasets/` e `evaluators/` | Indicam o agente, dataset e critérios usados nas avaliações. | Ao executar avaliações do agente; não configuram o processamento normal dos webhooks. |
| [`.github/workflows/ci.yml`](./.github/workflows/ci.yml) | Define verificações de lint, formatação, testes e validação Terraform. | Automaticamente em eventos de push e pull request configurados no workflow. |
| [`.vscode/launch.json`](./.vscode/launch.json), [`.vscode/tasks.json`](./.vscode/tasks.json), [`.vscode/settings.json`](./.vscode/settings.json) | Configuram depuração, tarefas locais e opções do Azure Functions para o VS Code. | Ao usar as tarefas ou configurações de depuração do workspace. |

Arquivos `tests/playground/*.json` são entradas de cenários de teste/playground, não configurações de
runtime. Arquivos de build e configurações locais ignorados pelo Git também não são modelos de
configuração compartilhados.
