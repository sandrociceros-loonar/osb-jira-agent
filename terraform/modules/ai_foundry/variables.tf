variable "resource_group_name" {
  description = "Nome do Resource Group onde os recursos serão criados"
  type        = string
}

variable "location" {
  description = "Região da Azure (ex: eastus2, westeurope)"
  type        = string
}

variable "hub_name" {
  description = "Nome do Azure AI Foundry Hub"
  type        = string
}

variable "project_name" {
  description = "Nome do Projeto dentro do Azure AI Foundry"
  type        = string
}

variable "model_deployment_name" {
  description = "Nome do deployment do modelo"
  type        = string
  default     = "gpt-5"
}

variable "model_name" {
  description = "Modelo base da OpenAI no Foundry"
  type        = string
  default     = "gpt-5"
}

variable "model_version" {
  description = "Versão do modelo no Foundry"
  type        = string
  default     = "2025-08-07"
}

variable "model_capacity" {
  description = "Capacidade GlobalStandard em milhares de tokens por minuto"
  type        = number
  default     = 50
}

variable "tags" {
  description = "Tags para governança de recursos"
  type        = map(string)
  default     = {}
}
