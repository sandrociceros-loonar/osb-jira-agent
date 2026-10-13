# Storage Account usada pelo host e pelo pacote de implantação do Flex Consumption
terraform {
  required_providers {
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.0"
    }
  }
}

data "azurerm_client_config" "current" {}

resource "azurerm_storage_account" "storage" {
  name                     = var.storage_account_name
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  min_tls_version = "TLS1_2"
  tags            = var.tags
}

resource "azurerm_storage_container" "deployment" {
  name                  = "deploymentpackage"
  storage_account_id    = azurerm_storage_account.storage.id
  container_access_type = "private"
}

resource "azurerm_user_assigned_identity" "deployment" {
  name                = "${var.function_app_name}-deployment"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

# Flex Consumption accesses the deployment package through this identity.
resource "azurerm_role_assignment" "deployment_storage_role" {
  scope                = azurerm_storage_account.storage.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.deployment.principal_id
}

resource "azurerm_service_plan" "plan" {
  name                = "${var.function_app_name}-plan"
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = "FC1"

  tags = var.tags
}

resource "azapi_resource" "function" {
  type      = "Microsoft.Web/sites@2024-04-01"
  name      = var.function_app_name
  parent_id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${var.resource_group_name}"
  location  = var.location

  identity {
    type         = "SystemAssigned, UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.deployment.id]
  }

  body = {
    kind = "functionapp,linux"
    properties = {
      httpsOnly = true
      serverFarmId = replace(
        azurerm_service_plan.plan.id,
        "serverFarms",
        "serverfarms"
      )
      functionAppConfig = {
        deployment = {
          storage = {
            type  = "blobContainer"
            value = azurerm_storage_container.deployment.url
            authentication = {
              type                           = "UserAssignedIdentity"
              userAssignedIdentityResourceId = azurerm_user_assigned_identity.deployment.id
            }
          }
        }
        runtime = {
          name    = "python"
          version = "3.13"
        }
        scaleAndConcurrency = {
          instanceMemoryMB     = 2048
          maximumInstanceCount = 10
        }
      }
      siteConfig = {
        appSettings = [
          for name, value in merge(
            {
              "AzureWebJobsStorage"         = azurerm_storage_account.storage.primary_connection_string
              "FUNCTIONS_EXTENSION_VERSION" = "~4"
              "AzureWebJobsFeatureFlags"    = "EnableWorkerIndexing"
            },
            var.app_settings
            ) : {
            name  = name
            value = value
          }
        ]
        cors = {
          allowedOrigins = ["*"]
        }
      }
    }
  }

  response_export_values = [
    "properties.defaultHostName"
  ]

  tags = var.tags

  depends_on = [
    azurerm_role_assignment.deployment_storage_role
  ]
}

# Atribuição de permissão RBAC: Cognitive Services OpenAI User para o Foundry
resource "azurerm_role_assignment" "ai_services_role" {
  scope                = var.ai_services_id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azapi_resource.function.identity[0].principal_id
}

# Atribuição de permissão RBAC: Key Vault Secrets User para ler segredos
resource "azurerm_role_assignment" "key_vault_role" {
  scope                = var.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azapi_resource.function.identity[0].principal_id
}
