# Storage Account requerida para o host do Azure Functions
resource "azurerm_storage_account" "storage" {
  name                     = var.storage_account_name
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  min_tls_version = "TLS1_2"
  tags            = var.tags
}

# Plano de Consumo Serverless Linux
resource "azurerm_service_plan" "plan" {
  name                = "${var.function_app_name}-plan"
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = "Y1"

  tags = var.tags
}

# Function App Linux com Python 3.11 e Managed Identity
resource "azurerm_linux_function_app" "function" {
  name                = var.function_app_name
  resource_group_name = var.resource_group_name
  location            = var.location

  storage_account_name       = azurerm_storage_account.storage.name
  storage_account_access_key = azurerm_storage_account.storage.primary_access_key
  service_plan_id            = azurerm_service_plan.plan.id

  # Habilita Managed Identity atribuída pelo sistema
  identity {
    type = "SystemAssigned"
  }

  site_config {
    application_stack {
      python_version = "3.11"
    }
    cors {
      allowed_origins = ["*"]
    }
  }

  app_settings = merge(
    {
      "FUNCTIONS_WORKER_RUNTIME"       = "python"
      "AzureWebJobsFeatureFlags"       = "EnableWorkerIndexing"
      "SCM_DO_BUILD_DURING_DEPLOYMENT" = "true"
    },
    var.app_settings
  )

  tags = var.tags
}

# Atribuição de permissão RBAC: Cognitive Services OpenAI User para o Foundry
resource "azurerm_role_assignment" "ai_services_role" {
  scope                = var.ai_services_id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_linux_function_app.function.identity[0].principal_id
}

# Atribuição de permissão RBAC: Key Vault Secrets User para ler segredos
resource "azurerm_role_assignment" "key_vault_role" {
  scope                = var.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_function_app.function.identity[0].principal_id
}
