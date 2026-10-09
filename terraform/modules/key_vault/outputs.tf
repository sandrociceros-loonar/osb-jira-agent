output "key_vault_id" {
  description = "ID do Azure Key Vault"
  value       = azurerm_key_vault.kv.id
}

output "key_vault_name" {
  description = "Nome do Azure Key Vault"
  value       = azurerm_key_vault.kv.name
}

output "key_vault_uri" {
  description = "URI do Azure Key Vault"
  value       = azurerm_key_vault.kv.vault_uri
}

output "secret_jira_webhook_name" {
  description = "Nome do segredo do webhook no Key Vault"
  value       = azurerm_key_vault_secret.jira_webhook_secret.name
}
