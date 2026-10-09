data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "kv" {
  name                        = var.key_vault_name
  location                    = var.location
  resource_group_name         = var.resource_group_name
  enabled_for_disk_encryption = false
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  soft_delete_retention_days  = 7
  purge_protection_enabled    = false

  sku_name = "standard"

  # Habilita Azure RBAC para autorização fina
  enable_rbac_authorization = true

  tags = var.tags
}

# Segredo do Webhook do Jira armazenado com segurança
resource "azurerm_key_vault_secret" "jira_webhook_secret" {
  name         = "jira-webhook-secret"
  value        = var.jira_webhook_secret
  key_vault_id = azurerm_key_vault.kv.id
}

resource "azurerm_key_vault_secret" "jira_api_token" {
  count        = var.jira_api_token == "" ? 0 : 1
  name         = "jira-api-token"
  value        = var.jira_api_token
  key_vault_id = azurerm_key_vault.kv.id
}
