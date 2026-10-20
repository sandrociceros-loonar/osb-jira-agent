variable "environment" {
  description = "Ambiente de deployment (ex: dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "subscription_id" {
  description = "ID da assinatura Azure onde os recursos da aplicação serão criados"
  type        = string
}

variable "location" {
  description = "Região da Azure para todos os recursos"
  type        = string
  default     = "eastus2"
}

variable "resource_group_name" {
  description = "Nome do Resource Group principal"
  type        = string
  default     = "rg-osb-jira-agent-dev"
}

variable "prefix" {
  description = "Prefixo único para nomeação dos recursos"
  type        = string
  default     = "osbjira"
}

variable "jira_instance_url" {
  description = "URL da instância Jira Service Management"
  type        = string
  default     = "https://your-domain.atlassian.net"
}

variable "jira_project_key" {
  description = "Chave do projeto Jira Service Management"
  type        = string
  default     = "ITSM"
}

variable "azure_ai_model_deployment_name" {
  description = "Nome do deployment GPT no Azure AI Foundry"
  type        = string
  default     = "gpt-5"
}

variable "azure_ai_model_name" {
  description = "Nome do modelo OpenAI implantado no Azure AI Foundry"
  type        = string
  default     = "gpt-5"
}

variable "azure_ai_model_version" {
  description = "Versão do modelo OpenAI implantado no Azure AI Foundry"
  type        = string
  default     = "2025-08-07"
}

variable "azure_ai_model_capacity" {
  description = "Capacidade GlobalStandard em milhares de tokens por minuto"
  type        = number
  default     = 50
}

variable "jira_allowed_project_keys" {
  description = "Projetos Jira que o agente pode consultar ou alterar"
  type        = list(string)
  default     = ["ITSM", "OP"]
}

variable "jira_lead_project_key" {
  description = "Projeto no qual a ferramenta pode criar leads"
  type        = string
  default     = "OP"
}

variable "jira_lead_issue_type_id" {
  description = "ID do tipo Jira usado para criação de lead"
  type        = string
  default     = "12716"
}

variable "jira_manufacturer_field_id" {
  description = "ID opcional do campo de fabricante editável no lead Jira"
  type        = string
  default     = ""
}

variable "jira_skip_manufacturer_update_if_not_editable" {
  description = "Permite webhook com fabricante pendente quando o campo não está editável; bloqueia a geração de proposta"
  type        = bool
  default     = false
}

variable "jira_enable_write_operations" {
  description = "Habilita operações Jira de criação, comentários, transições e write-back"
  type        = bool
  default     = false
}

variable "jira_transition_ids" {
  description = "IDs das transições Jira definidos nos manifestos; confirme no workflow de destino"
  type        = map(string)
  default = {
    start_lead_work                  = "2"
    transition_lead_to_proposal_item = "21"
    generate_new_proposal            = "3"
    send_item_to_purchasing          = "12"
    set_proposal_item_price          = "7"
  }
}

variable "jira_api_email" {
  description = "E-mail da conta Atlassian usada pelo conector Jira"
  type        = string

  validation {
    condition     = length(trimspace(var.jira_api_email)) > 0
    error_message = "jira_api_email deve ser informado para autenticar no Jira e no Confluence."
  }
}

variable "jira_api_token" {
  description = "Token de API Atlassian armazenado no Key Vault"
  type        = string
  sensitive   = true

  validation {
    condition     = length(trimspace(var.jira_api_token)) > 0
    error_message = "jira_api_token deve ser informado para autenticar no Jira e no Confluence."
  }
}

variable "jira_team_account_ids" {
  description = "Mapeamento das equipes sugeridas para accountIds do Jira"
  type        = map(string)
  default     = {}
}

variable "jira_webhook_secret" {
  description = "Segredo compartilhado para validação do webhook"
  type        = string
  sensitive   = true

  validation {
    condition     = length(trimspace(var.jira_webhook_secret)) >= 32
    error_message = "jira_webhook_secret deve ter pelo menos 32 caracteres."
  }
}

variable "jira_webhook_secret_header" {
  description = "Cabeçalho HTTP usado pelo Jira para enviar o segredo do webhook"
  type        = string
  default     = "X-Atlassian-Webhook-Secret"
}

variable "confluence_space_url" {
  description = "URL do espaço Confluence usado como base de conhecimento"
  type        = string
  default     = "https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage"
}

variable "confluence_base_url" {
  description = "URL base da API do Confluence Cloud"
  type        = string
  default     = "https://loonar-osb.atlassian.net/wiki"
}

variable "confluence_space_key" {
  description = "Chave do espaço Confluence usado como base de conhecimento"
  type        = string
  default     = "osbjiraage"
}

variable "confluence_api_email" {
  description = "E-mail Atlassian opcional para autenticação no Confluence; vazio usa o e-mail Jira"
  type        = string
  default     = ""
}

variable "confluence_api_token" {
  description = "Token opcional de API Confluence armazenado no Key Vault"
  type        = string
  sensitive   = true
  default     = ""
}

variable "confluence_webhook_secret" {
  description = "Segredo do webhook Confluence armazenado no Key Vault"
  type        = string
  sensitive   = true

  validation {
    condition     = length(trimspace(var.confluence_webhook_secret)) >= 32
    error_message = "confluence_webhook_secret deve ter pelo menos 32 caracteres."
  }
}

variable "confluence_webhook_secret_header" {
  description = "Cabeçalho HTTP usado pela automação do Confluence para enviar o segredo"
  type        = string
  default     = "X-Atlassian-Webhook-Secret"
}

variable "jira_assets_access_token" {
  description = "Token OAuth das APIs Jira Assets armazenado no Key Vault"
  type        = string
  sensitive   = true
  default     = ""
}

variable "jira_assets_cloud_id" {
  description = "Cloud ID do Jira usado pelo conector Assets"
  type        = string
  default     = ""
}

variable "jira_assets_workspace_id" {
  description = "Workspace ID do Jira Assets"
  type        = string
  default     = ""
}

variable "jira_assets_product_object_type_id" {
  description = "Object type ID de produtos consultado pela pesquisa AQL"
  type        = string
  default     = "157"
}

variable "azure_ai_max_tool_calls" {
  description = "Limite total de chamadas de ferramentas por execução"
  type        = number
  default     = 16
}

variable "jira_attachment_max_bytes" {
  description = "Limite de bytes para anexos disponibilizados ao modelo"
  type        = number
  default     = 65536
}

variable "log_level" {
  description = "Nível de logging da aplicação"
  type        = string
  default     = "INFO"
}

variable "tags" {
  description = "Tags padrão para governança"
  type        = map(string)
  default = {
    Project     = "OSB-Jira-Agent"
    ManagedBy   = "Terraform"
    Environment = "dev"
  }
}
