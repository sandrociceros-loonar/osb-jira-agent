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
  description = "Nome do deployment do modelo (ex: gpt-4o)"
  type        = string
  default     = "gpt-4o"
}

variable "model_name" {
  description = "Modelo base da OpenAI no Foundry (ex: gpt-4o)"
  type        = string
  default     = "gpt-4o"
}

variable "model_version" {
  description = "Versão do modelo no Foundry"
  type        = string
  default     = "2024-08-06"
}

variable "tags" {
  description = "Tags para governança de recursos"
  type        = map(string)
  default     = {}
}
