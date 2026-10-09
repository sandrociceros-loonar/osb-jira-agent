variable "resource_group_name" {
  description = "Nome do Resource Group"
  type        = string
}

variable "location" {
  description = "Região da Azure"
  type        = string
}

variable "function_app_name" {
  description = "Nome único da Function App"
  type        = string
}

variable "storage_account_name" {
  description = "Nome da Storage Account para a Function App"
  type        = string
}

variable "ai_services_id" {
  description = "ID do recurso Azure AI Services para atribuição de RBAC"
  type        = string
}

variable "key_vault_id" {
  description = "ID do Key Vault para atribuição de RBAC"
  type        = string
}

variable "app_settings" {
  description = "Configurações de ambiente adicionais para a Function App"
  type        = map(string)
  default     = {}
}

variable "tags" {
  description = "Tags para governança de recursos"
  type        = map(string)
  default     = {}
}
