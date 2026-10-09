# Conta principal do Azure AI Services / AI Foundry
resource "azurerm_cognitive_account" "ai_services" {
  name                  = var.hub_name
  location              = var.location
  resource_group_name   = var.resource_group_name
  kind                  = "AIServices"
  sku_name              = "S0"
  custom_subdomain_name = lower(var.hub_name)

  public_network_access_enabled = true

  tags = var.tags
}

# Deployment do modelo GPT-4o no Azure AI Foundry
resource "azurerm_cognitive_deployment" "gpt" {
  name                 = var.model_deployment_name
  cognitive_account_id = azurerm_cognitive_account.ai_services.id

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = "GlobalStandard"
    capacity = 20
  }
}
