variable "environment" {
  description = "Ambiente de deployment (ex: dev, staging, prod)"
  type        = string
  default     = "dev"
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

variable "azure_ai_project_endpoint" {
  description = "Endpoint completo de um projeto Microsoft Foundry já criado"
  type        = string
  default     = ""
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
  default     = ""
}

variable "jira_api_token" {
  description = "Token de API Atlassian armazenado no Key Vault"
  type        = string
  sensitive   = true
  default     = ""
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
  default     = "change-me-in-production"
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
