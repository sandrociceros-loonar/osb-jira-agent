terraform {
  required_providers {
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.0"
    }
  }
}

resource "azurerm_cognitive_account" "ai_services" {
  name                  = var.hub_name
  location              = var.location
  resource_group_name   = var.resource_group_name
  kind                  = "AIServices"
  sku_name              = "S0"
  custom_subdomain_name = lower(var.hub_name)

  identity {
    type = "SystemAssigned"
  }

  project_management_enabled    = true
  public_network_access_enabled = true

  tags = var.tags
}

resource "azapi_resource" "project" {
  type      = "Microsoft.CognitiveServices/accounts/projects@2025-09-01"
  name      = var.project_name
  parent_id = azurerm_cognitive_account.ai_services.id
  location  = var.location

  identity {
    type = "SystemAssigned"
  }

  body = {
    properties = {
      description = "Microsoft Foundry project for the OSB Jira Agent"
      displayName = var.project_name
    }
  }

  tags = var.tags
}

resource "azurerm_cognitive_deployment" "gpt" {
  name                 = var.model_deployment_name
  cognitive_account_id = azurerm_cognitive_account.ai_services.id

  depends_on = [azapi_resource.project]

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = "GlobalStandard"
    capacity = var.model_capacity
  }
}
