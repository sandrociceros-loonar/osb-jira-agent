variable "resource_group_name" {
  description = "Nome do Resource Group"
  type        = string
}

variable "location" {
  description = "Região da Azure"
  type        = string
}

variable "key_vault_name" {
  description = "Nome único do Azure Key Vault"
  type        = string
}

variable "jira_webhook_secret" {
  description = "Valor inicial do segredo do Webhook do Jira"
  type        = string
  sensitive   = true
  default     = "change-me-in-production"
}

variable "jira_api_token" {
  description = "Token opcional de API Atlassian para o conector Jira"
  type        = string
  sensitive   = true
  default     = ""
}

variable "tags" {
  description = "Tags para governança de recursos"
  type        = map(string)
  default     = {}
}
