# Guia de implantação — OSB Jira Commercial CRM Agent

Este guia descreve como publicar uma nova versão do código deste repositório. O projeto tem
**duas entradas independentes** que compartilham o processamento comercial:

1. **Azure Function** (`function_app.py`): entrada normal dos webhooks do Jira. Se o Jira aponta
   para essa Function, publique-a para que eventos novos e respostas a comentários usem o código
   atualizado.
2. **Microsoft Foundry Hosted Agent** (`azure.yaml`): entrada adicional pelo protocolo
   `invocations`. Publique-o somente se essa entrada também for utilizada.

Publicar um deles **não** atualiza o outro. A Function chama o modelo do projeto Foundry; ela não
é automaticamente substituída pelo Hosted Agent.

## 1. Pré-requisitos

- Acesso de implantação à subscription, ao Resource Group e aos recursos já criados.
- Azure CLI autenticada (`az login`).
- Para o Hosted Agent: Azure Developer CLI `azd` **1.27.1 ou superior** e extensão
  `azure.ai.agents` **1.0.0-beta.9 ou superior**.
- Para a Azure Function: Azure Functions Core Tools v4 (`func`) e permissão de publicação na
  Function App.
- `uv` e Python 3.11–3.13 para instalar dependências e rodar as verificações locais.
- Um ambiente `azd` existente para o deployment Foundry, caso o Hosted Agent seja usado.
- Uma issue **de teste** no Jira, em um ambiente não produtivo, para validar comentários e
  transições. Não use uma issue comercial real para smoke tests com escritas habilitadas.

Execute comandos `azd` na raiz deste projeto. O prefixo
`AZURE_DEV_USER_AGENT=microsoft_foundry_skill` abaixo é local ao comando: não o grave no código,
em `.env`, nem no ambiente persistente do `azd`.

## 2. Validar o código e a configuração

Na raiz do repositório:

```bash
uv sync --all-extras --group dev
uv run pytest -q
uv run ruff check src tests
git diff --check
```

O Hosted Agent usa `dependencyResolution: remote_build`: se alguma dependência de runtime mudou,
sincronize `requirements.txt` com o lockfile antes de publicar:

```bash
uv export --format requirements-txt --no-dev --no-hashes --no-emit-project -o requirements.txt
```

Confira também:

- [azure.yaml](./azure.yaml) aponta para o projeto correto, o entry point
  `src/hosted_agent/main.py` e o protocolo `invocations`.
- [requirements.txt](./requirements.txt) reflete as dependências de runtime atuais.
- Nenhum `.env`, `local.settings.json`, token, senha ou arquivo Terraform de state será incluído
  no pacote ou commit.
- As configurações de produção estão no ambiente Azure/`azd` correto; não copie segredos para os
  comandos nem compartilhe a saída de `azd env get-values`.

## 3. Confirmar as configurações de produção

### 3.1 Hosted Agent

Selecione o ambiente existente e confira a configuração:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env list
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env select <nome-do-ambiente>
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env get-values
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd ai project show --output json
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd ai agent show --output json
```

Confirme que o ambiente selecionado é o destino pretendido e que o projeto Foundry e o deployment
do agente existem. Para uma atualização apenas de código, **não execute `azd provision`**: esse
comando é para criação/alteração de infraestrutura.

O serviço do Hosted Agent recebe variáveis não secretas pelo [azure.yaml](./azure.yaml). Confira
que o ambiente `azd` contém todos os valores referenciados pelo `azure.yaml`. O Terraform não
sincroniza automaticamente suas variáveis para o ambiente `azd`; portanto, copie os valores de
configuração não secretos do `terraform.tfvars` para o ambiente `azd` selecionado. O URI do
Key Vault vem do output `key_vault_uri`:

```bash
terraform -chdir=terraform output -raw key_vault_uri
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set JIRA_KEY_VAULT_URL "<key-vault-uri>"
```

Preencha no ambiente `azd`:

- `AZURE_AI_MODEL_DEPLOYMENT_NAME`, `ENVIRONMENT`, `JIRA_KEY_VAULT_URL`,
  `AZURE_AI_MAX_TOOL_CALLS` e `LOG_LEVEL`;
- `CONFLUENCE_SPACE_URL`, `CONFLUENCE_BASE_URL` e `CONFLUENCE_SPACE_KEY` são definidos no
  `azure.yaml` para o espaço deste projeto; `CONFLUENCE_API_EMAIL` reutiliza `JIRA_API_EMAIL`;
- `JIRA_WEBHOOK_SECRET_HEADER`, `JIRA_INSTANCE_URL`, `JIRA_API_EMAIL`, `JIRA_PROJECT_KEY`,
  `JIRA_ALLOWED_PROJECT_KEYS`, `JIRA_LEAD_PROJECT_KEY` e `JIRA_LEAD_ISSUE_TYPE_ID`;
- `JIRA_TRANSITION_IDS`, `JIRA_ENABLE_WRITE_OPERATIONS`, `JIRA_TEAM_ACCOUNT_IDS` e
  `JIRA_ATTACHMENT_MAX_BYTES`;
- `JIRA_ASSETS_CLOUD_ID`, `JIRA_ASSETS_WORKSPACE_ID`,
  `JIRA_ASSETS_PRODUCT_OBJECT_TYPE_ID`;
- `JIRA_MANUFACTURER_FIELD_ID` como substituição opcional quando o nome do campo não puder ser
  encontrado; `JIRA_AGENT_ACCOUNT_ID` é recomendado para identificar com precisão comentários
  feitos pela conta do agente.
- `JIRA_SKIP_MANUFACTURER_UPDATE_IF_NOT_EDITABLE` para permitir que o webhook continue com a
  atualização do fabricante registrada como pendente quando o campo existir, mas não puder ser
  editado. O valor padrão é `false`; mesmo habilitado, o agente não pode gerar proposta enquanto
  essa pendência não for resolvida.

Não configure `JIRA_API_TOKEN`, `CONFLUENCE_API_TOKEN` nem `CONFLUENCE_WEBHOOK_SECRET` no ambiente
`azd`. O token Jira é lido do Key Vault pelo Hosted Agent e reutilizado para o Confluence;
`CONFLUENCE_WEBHOOK_SECRET` é exclusivo da Function.

Se o ambiente ainda não tiver esses dois valores opcionais, configure-os antes do deploy:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set JIRA_MANUFACTURER_FIELD_ID "customfield_12345"
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd env set JIRA_AGENT_ACCOUNT_ID "<account-id-da-conta-do-agente>"
```

Use o ID real do campo consultado no Jira e o account ID da conta de automação. A configuração
do ID não torna o campo editável: o campo de fabricante também precisa estar no ecrã de edição do
tipo Lead e a conta de integração precisa ter permissão para editá-lo. Para a Function provisionada
por Terraform, configure `jira_manufacturer_field_id` em `terraform.tfvars`; para o Hosted Agent,
configure `JIRA_MANUFACTURER_FIELD_ID` no ambiente azd. Habilite o bypass temporário com
`jira_skip_manufacturer_update_if_not_editable = true` no Terraform para a Function e
`JIRA_SKIP_MANUFACTURER_UPDATE_IF_NOT_EDITABLE=true` no ambiente azd para o Hosted Agent. Ative-o
somente se for aceitável continuar o fluxo sem atualizar o campo: a proposta permanece bloqueada
até o fabricante ser confirmado no Jira. Se o campo Fabricante for localizado pelo nome e o
account ID não estiver disponível, deixe os valores vazios e confirme a configuração correspondente
no Azure antes de publicar.

Os tokens Jira e Assets devem continuar no Azure Key Vault. A identidade gerenciada usada pelo
Hosted Agent precisa de permissão **Key Vault Secrets User** no vault e dos segredos esperados
`jira-api-token`; `jira-assets-access-token` é opcional. Não use `azd env set` para tokens ou outros
segredos. Por padrão, o runtime usa o token carregado de `jira-api-token` tanto no Jira quanto no
Confluence. Se no futuro o Confluence passar a usar token próprio, armazene-o em
`confluence-api-token` no mesmo vault; quando esse segredo não existir, o runtime mantém o fallback
para o token Jira. `CONFLUENCE_WEBHOOK_SECRET` não deve ser configurado no Hosted Agent: ele
protege exclusivamente a entrada de webhook da Function.

O Terraform deste repositório atribui **Key Vault Secrets User** à Function App, mas não à
identidade do Hosted Agent. Antes de usar/deployar o Hosted Agent, conceda essa função à identidade
de execução efetivamente usada pelo Hosted Agent no Key Vault correto; não presuma que a role
assignment da Function também o autoriza.

### 3.2 Azure Function

Identifique a Function App pelo output Terraform `function_app_name` ou pelo portal Azure.
Confirme que sua configuração contém os valores e referências ao Key Vault exigidos pela
aplicação. O Terraform define os App settings do espaço Confluence e, se os valores forem
preenchidos em `terraform.tfvars`, cria referências ao Key Vault para `CONFLUENCE_API_TOKEN` e
`CONFLUENCE_WEBHOOK_SECRET`. Em particular:

- `JIRA_WEBHOOK_SECRET` e `JIRA_WEBHOOK_SECRET_HEADER` devem corresponder ao segredo e header
  configurados no webhook Jira;
- `CONFLUENCE_SPACE_URL`, `CONFLUENCE_BASE_URL`, `CONFLUENCE_SPACE_KEY`,
  `CONFLUENCE_API_EMAIL` e `CONFLUENCE_WEBHOOK_SECRET_HEADER` devem identificar o espaço e
  corresponder à automação Confluence; `CONFLUENCE_API_EMAIL` pode ficar vazio para reutilizar o
  e-mail Jira e `CONFLUENCE_API_TOKEN` pode ficar vazio para reutilizar o token Jira;
- configure `confluence_webhook_secret` em `terraform.tfvars` para receber webhooks Confluence.
  Informe um segredo aleatório exclusivo com pelo menos 32 caracteres. O Terraform valida a
  presença/tamanho, grava o valor no Key Vault e configura a referência na Function App;
- `JIRA_ENABLE_WRITE_OPERATIONS` precisa permanecer `false` durante o primeiro teste sem
  escritas. Para o fluxo comercial completo, habilite escritas somente depois de validar
  permissões e IDs de transição no ambiente de teste;
- mantenha os tokens nos segredos do Key Vault e a identidade da Function autorizada a lê-los;
- mantenha o campo Fabricante editável para o tipo Lead no Jira e configure
  `jira_manufacturer_field_id` em `terraform.tfvars` se a descoberta pelo nome não for possível;
  `JIRA_AGENT_ACCOUNT_ID` também é recomendado para a Function quando disponível.

`JIRA_ENABLE_WRITE_OPERATIONS=true` habilita o conjunto de ferramentas de escrita do agente, não
apenas comentários de lead. Faça a validação inicial em ambiente não produtivo e limite as
permissões da conta Jira ao necessário.

### Ajustar capacidade e escala

As configurações versionadas e seus valores iniciais estão descritos na seção [Capacidade e
processamento paralelo](./README.md#capacidade-e-processamento-paralelo). Antes de alterar recursos,
identifique o gargalo usando métricas do Azure Functions, Foundry e Jira; os limites abaixo não
definem por si só uma taxa garantida de leads/minuto.

- **Azure Function:** altere `instanceMemoryMB` ou `maximumInstanceCount` em
  `terraform/modules/function_app/main.tf`. Em seguida, execute `terraform -chdir=terraform plan`,
  revise as alterações e aplique somente no state/ambiente correto conforme a seção seguinte. O
  máximo configurado no repositório é 10 instâncias de 2.048 MB.
- **Modelo Foundry:** altere `azure_ai_model_capacity` em `terraform/terraform.tfvars` (o exemplo
  usa 50, em milhares de tokens por minuto) e aplique via Terraform após confirmar quota, SKU,
  disponibilidade regional e limites para o modelo/deployment escolhido.
- **Hosted Agent:** altere `container.resources.cpu` e `memory` em `azure.yaml` e execute novamente
  `azd deploy osb-jira-agent --no-prompt` no ambiente selecionado. O projeto não define o máximo de
  réplicas/concorrência gerenciado pelo Foundry.
- **Chamadas de ferramentas:** `AZURE_AI_MAX_TOOL_CALLS` pode ser alterado na configuração de
  ambiente da Function e no ambiente `azd` do Hosted Agent. Esse limite restringe chamadas por
  triagem; não controla a concorrência de leads. As chamadas de ferramenta são sequenciais.

Reduzir os valores diminui a escala/capacidade correspondente, mas pode aumentar latência ou
throttling; aumentar valores pode elevar custos e precisa respeitar quotas. Valide cada mudança com
um teste de carga gradual, observando latência, falhas, throttling, consumo de tokens e limites de
requisição do Jira. Não configure o webhook para responder como se o trabalho estivesse concluído:
o processamento atual é síncrono e não usa fila.

### 3.3 Provisionar infraestrutura com Terraform

Terraform gerencia o Resource Group, a conta/projeto/deployment Foundry, Key Vault, Storage e
Function App. Antes de executar, confirme que está no workspace/state Terraform correspondente ao
ambiente pretendido. O state local contém valores sensíveis; não o copie para o repositório nem
execute `apply` a partir de um clone sem recuperar o state correto ou importar os recursos
existentes. Para trabalho compartilhado, configure um backend remoto Azure Storage.

```bash
test -f terraform/terraform.tfvars || cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Preencha subscription_id, configurações do Jira/Confluence e segredos em um meio local seguro.
terraform -chdir=terraform init
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate
terraform -chdir=terraform plan -input=false
```

Revise todo o plano antes de aplicar. Se ele propuser recriar ou destruir recursos existentes,
pare e corrija o state/configuração; não use `apply` como tentativa de diagnóstico. Após aprovação,
aplique com `terraform -chdir=terraform apply`. O Terraform provisiona/configura a infraestrutura,
mas não publica o pacote Python da Function nem a versão do Hosted Agent: publique a Function
separadamente com `func azure functionapp publish` e o Hosted Agent com `azd deploy`.

## 4. Publicar o Hosted Agent (se essa entrada estiver em uso)

O Hosted Agent está declarado em `azure.yaml` com `codeConfiguration` e `remote_build`; use
publicação de código com `azd deploy`, não um fluxo Docker/ACR. A implantação cria uma nova versão
imutável do agente:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd deploy osb-jira-agent --no-prompt
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd ai agent show --output json
```

Confirme que a versão nova aparece ativa e que o endpoint `invocations` está presente. Se o deploy
falhar, consulte `azd ai agent doctor --output json` e os logs do deployment antes de tentar de
novo; não rode `azd provision` como tentativa genérica de corrigir falhas de código.

### Smoke test de Invocations

Este agente espera o **corpo bruto de um webhook Jira**, não uma mensagem livre como `"Olá"`.
Use um arquivo JSON de uma issue de teste autorizada e não produtiva que siga o formato dos
fixtures em [tests/conftest.py](./tests/conftest.py). Por exemplo, crie localmente
`/tmp/jira-agent-smoke.json` com um payload de teste seguro e invoque:

```bash
AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd ai agent invoke \
  --protocol invocations \
  --input-file /tmp/jira-agent-smoke.json
```

Não use dados de cliente ou uma issue de produção nesse arquivo. Uma invocação remota pode gerar
custo de modelo. Para exercitar o fluxo completo, use um lead de teste e comentários de teste;
com escritas desabilitadas, espere que o agente não consiga adicionar comentários nem atualizar
campos.

## 5. Publicar a Azure Function (entrada normal do Jira)

Se os webhooks Jira apontam para a Function App, publique também a Function para que ela receba o
código atualizado:

```bash
func azure functionapp publish <nome-da-function-app>
```

O nome pode ser consultado no output Terraform `function_app_name`. Se a publicação indicar erro
de build remoto para Python, consulte `func azure functionapp publish --help` para a sintaxe
compatível com a versão instalada do Core Tools e com o plano Flex Consumption deste projeto.
Não publique artefatos de outra Function App por engano.

Após a publicação, verifique a saúde da Function:

```bash
curl --fail-with-body https://<nome-da-function-app>.azurewebsites.net/api/health
```

O resultado esperado contém `"status": "healthy"`. O endpoint `/api/jira-webhook` exige um evento
Jira válido e a autenticação configurada; não o use como health check.

## 6. Configurar e validar os webhooks do Jira

Configure o webhook Jira para apontar para a URL da Function:

```text
https://<nome-da-function-app>.azurewebsites.net/api/jira-webhook
```

Preserve o header secreto que já está configurado e habilite os eventos:

- `issue_created`;
- `issue_updated`;
- criação de comentário (`comment_created` / `jira:issue_comment_created`, conforme a opção
  disponibilizada pela versão do Jira).

O endpoint Hosted Agent Foundry **não** deve substituir a Function como URL de webhook: ele
exige autenticação Microsoft Entra e não verifica o segredo de webhook Jira.

Em um projeto Jira de teste:

1. Crie um lead de teste que contenha o software e apenas os dados comerciais disponíveis.
2. Confirme que o agente consulta o Jira Assets e atualiza Fabricante somente se a correspondência
   for inequívoca.
3. Confirme que dados faltantes geram um comentário público com perguntas específicas.
4. Verifique que o esquema de notificações Jira envia o comentário ao solicitante por e-mail. O
   código cria um comentário público cordial, sem repetir o nome da conta que o Jira já exibe como
   autora; o envio de e-mail depende da configuração Jira.
5. Responda ao comentário como usuário de teste e confirme que o novo evento retoma a avaliação,
   não duplica a pergunta anterior nem os dados já preenchidos e não responde ao próprio comentário
   da conta autenticada.
6. Só com todos os dados de proposta preenchidos, confirme que a transição foi realizada e que o
   comentário de conclusão corresponde ao resultado real do Jira.
7. Verifique logs da Function/Foundry e confirme que não há credenciais, tokens ou conteúdo
   sensível registrados.

## 7. Rollback e versões

- Cada `azd deploy` bem-sucedido registra uma versão imutável do Hosted Agent. Guarde o número da
  versão anterior e use o histórico de versões do projeto Foundry para restaurar a versão ativa
  anterior conforme o processo de release da sua organização. A opção `--version` em `azd ai
  agent invoke` serve para direcionar uma invocação de teste a uma versão; por si só, não reverte
  o endpoint ativo.
- Para a Azure Function, mantenha o artefato/revisão de código que estava em produção e publique
  novamente essa revisão usando o procedimento de release aprovado. O deploy do Hosted Agent não
  faz rollback da Function, nem o inverso.
- Após qualquer rollback, confira `/api/health`, a versão ativa do Hosted Agent e o recebimento de
  um webhook de teste antes de considerar o serviço recuperado.

## Resumo rápido

| Entrada em uso | Publicação necessária |
|---|---|
| Webhooks Jira apontam para Azure Function | `func azure functionapp publish <nome-da-function-app>` |
| Chamadas Foundry usam o protocolo `invocations` | `AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd deploy osb-jira-agent --no-prompt` |
| Ambas as entradas estão em uso | Publique e valide ambas separadamente |
