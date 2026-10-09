output "resource_group_name" {
  description = "Nome do Resource Group criado"
  value       = azurerm_resource_group.rg.name
}

output "ai_services_endpoint" {
  description = "Endpoint do serviço Azure AI Foundry"
  value       = module.ai_foundry.ai_services_endpoint
}

output "function_app_name" {
  description = "Nome da Function App que recebe os webhooks"
  value       = module.function_app.function_app_name
}

output "webhook_endpoint_url" {
  description = "URL que deve ser configurada nos Webhooks do Jira Service Management"
  value       = module.function_app.webhook_endpoint_url
}

output "key_vault_uri" {
  description = "URI do Azure Key Vault"
  value       = module.key_vault.key_vault_uri
}
