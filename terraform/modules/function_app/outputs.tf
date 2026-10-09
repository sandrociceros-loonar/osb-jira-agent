output "function_app_id" {
  description = "ID da Function App"
  value       = azurerm_linux_function_app.function.id
}

output "function_app_name" {
  description = "Nome da Function App"
  value       = azurerm_linux_function_app.function.name
}

output "default_hostname" {
  description = "Hostname padrão da Function App"
  value       = azurerm_linux_function_app.function.default_hostname
}

output "webhook_endpoint_url" {
  description = "URL completa para o Webhook do Jira"
  value       = "https://${azurerm_linux_function_app.function.default_hostname}/api/jira-webhook"
}

output "principal_id" {
  description = "Principal ID da Managed Identity"
  value       = azurerm_linux_function_app.function.identity[0].principal_id
}
