output "ai_services_id" {
  description = "ID do recurso Azure AI Services"
  value       = azurerm_cognitive_account.ai_services.id
}

output "ai_services_endpoint" {
  description = "Endpoint do recurso Azure AI Services"
  value       = azurerm_cognitive_account.ai_services.endpoint
}

output "model_deployment_name" {
  description = "Nome do deployment do modelo criado"
  value       = azurerm_cognitive_deployment.gpt.name
}
