output "ai_services_id" {
  description = "ID do recurso Azure AI Services"
  value       = azurerm_cognitive_account.ai_services.id
}

output "ai_services_endpoint" {
  description = "Endpoint do recurso Azure AI Services"
  value       = azurerm_cognitive_account.ai_services.endpoint
}

output "project_endpoint" {
  description = "Endpoint do projeto Microsoft Foundry"
  value       = "https://${var.hub_name}.services.ai.azure.com/api/projects/${var.project_name}"
}

output "model_deployment_name" {
  description = "Nome do deployment do modelo criado"
  value       = azurerm_cognitive_deployment.gpt.name
}
