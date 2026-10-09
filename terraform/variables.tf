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
