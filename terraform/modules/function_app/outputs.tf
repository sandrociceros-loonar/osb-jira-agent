output "function_app_id" {
  description = "ID da Function App"
  value       = azapi_resource.function.id
}

output "function_app_name" {
  description = "Nome da Function App"
  value       = var.function_app_name
}

output "default_hostname" {
  description = "Hostname padrão da Function App"
  value       = azapi_resource.function.output.properties.defaultHostName
}

output "webhook_endpoint_url" {
  description = "URL completa para o Webhook do Jira"
  value       = "https://${azapi_resource.function.output.properties.defaultHostName}/api/jira-webhook"
}

output "principal_id" {
  description = "Principal ID da Managed Identity"
  value       = azapi_resource.function.identity[0].principal_id
}
