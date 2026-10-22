terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.2"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

# Gerador de sufixo aleatório para nomes globais únicos (Storage, KeyVault)
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

# Resource Group principal
resource "azurerm_resource_group" "rg" {
  name     = var.resource_group_name
  location = var.location
  tags     = var.tags
}

# Módulo 1: Azure AI Foundry
module "ai_foundry" {
  source                = "./modules/ai_foundry"
  resource_group_name   = azurerm_resource_group.rg.name
  location              = var.location
  hub_name              = "${var.prefix}-ai-${random_string.suffix.result}"
  project_name          = "${var.prefix}-proj-${var.environment}"
  model_deployment_name = var.azure_ai_model_deployment_name
  model_name            = var.azure_ai_model_name
  model_version         = var.azure_ai_model_version
  model_capacity        = var.azure_ai_model_capacity
  tags                  = var.tags
}

# Módulo 2: Azure Key Vault (Segurança e segredos)
module "key_vault" {
  source                    = "./modules/key_vault"
  resource_group_name       = azurerm_resource_group.rg.name
  location                  = var.location
  key_vault_name            = "${var.prefix}kv${random_string.suffix.result}"
  jira_webhook_secret       = var.jira_webhook_secret
  jira_api_token            = var.jira_api_token
  jira_assets_access_token  = var.jira_assets_access_token
  confluence_api_token      = var.confluence_api_token
  confluence_webhook_secret = var.confluence_webhook_secret
  tags                      = var.tags
}

# Módulo 3: Azure Functions (Python v2 Webhook Receiver com Managed Identity)
module "function_app" {
  source               = "./modules/function_app"
  resource_group_name  = azurerm_resource_group.rg.name
  location             = var.location
  function_app_name    = "${var.prefix}-func-${random_string.suffix.result}"
  storage_account_name = "${var.prefix}sa${random_string.suffix.result}"
  ai_services_id       = module.ai_foundry.ai_services_id
  key_vault_id         = module.key_vault.key_vault_id

  app_settings = {
    "AZURE_AI_PROJECT_ENDPOINT"                          = module.ai_foundry.project_endpoint
    "AZURE_AI_MODEL_DEPLOYMENT_NAME"                     = module.ai_foundry.model_deployment_name
    "AZURE_AI_MAX_TOOL_CALLS"                            = tostring(var.azure_ai_max_tool_calls)
    "SCM_DO_BUILD_DURING_DEPLOYMENT"                     = "true"
    "JIRA_WEBHOOK_SECRET"                                = "@Microsoft.KeyVault(VaultName=${module.key_vault.key_vault_name};SecretName=${module.key_vault.secret_jira_webhook_name})"
    "JIRA_WEBHOOK_SECRET_HEADER"                         = var.jira_webhook_secret_header
    "JIRA_INSTANCE_URL"                                  = var.jira_instance_url
    "JIRA_PROJECT_KEY"                                   = var.jira_project_key
    "JIRA_ALLOWED_PROJECT_KEYS"                          = jsonencode(var.jira_allowed_project_keys)
    "JIRA_LEAD_PROJECT_KEY"                              = var.jira_lead_project_key
    "JIRA_LEAD_ISSUE_TYPE_ID"                            = var.jira_lead_issue_type_id
    "JIRA_MANUFACTURER_FIELD_ID"                         = var.jira_manufacturer_field_id
    "JIRA_SKIP_MANUFACTURER_UPDATE_IF_NOT_EDITABLE"      = tostring(var.jira_skip_manufacturer_update_if_not_editable)
    "JIRA_ENABLE_WRITE_OPERATIONS"                       = tostring(var.jira_enable_write_operations)
    "JIRA_TRANSITION_IDS"                                = jsonencode(var.jira_transition_ids)
    "JIRA_API_EMAIL"                                     = var.jira_api_email
    "JIRA_API_TOKEN"                                     = var.jira_api_token == "" ? "" : "@Microsoft.KeyVault(VaultName=${module.key_vault.key_vault_name};SecretName=${module.key_vault.secret_jira_api_token_name})"
    "JIRA_TEAM_ACCOUNT_IDS"                              = jsonencode(var.jira_team_account_ids)
    "JIRA_ASSETS_ACCESS_TOKEN"                           = var.jira_assets_access_token == "" ? "" : "@Microsoft.KeyVault(VaultName=${module.key_vault.key_vault_name};SecretName=${module.key_vault.secret_jira_assets_access_token_name})"
    "JIRA_ASSETS_CLOUD_ID"                               = var.jira_assets_cloud_id
    "JIRA_ASSETS_WORKSPACE_ID"                           = var.jira_assets_workspace_id
    "JIRA_ASSETS_PRODUCT_OBJECT_TYPE_ID"                 = var.jira_assets_product_object_type_id
    "JIRA_ATTACHMENT_MAX_BYTES"                          = tostring(var.jira_attachment_max_bytes)
    "CONFLUENCE_SPACE_URL"                               = var.confluence_space_url
    "CONFLUENCE_BASE_URL"                                = var.confluence_base_url
    "CONFLUENCE_SPACE_KEY"                               = var.confluence_space_key
    "CONFLUENCE_API_EMAIL"                               = var.confluence_api_email
    "CONFLUENCE_API_TOKEN"                               = var.confluence_api_token == "" ? "" : "@Microsoft.KeyVault(VaultName=${module.key_vault.key_vault_name};SecretName=${module.key_vault.secret_confluence_api_token_name})"
    "CONFLUENCE_WEBHOOK_SECRET"                          = "@Microsoft.KeyVault(VaultName=${module.key_vault.key_vault_name};SecretName=${module.key_vault.secret_confluence_webhook_name})"
    "CONFLUENCE_WEBHOOK_SECRET_HEADER"                   = var.confluence_webhook_secret_header
    "LOG_LEVEL"                                          = var.log_level
    "ENVIRONMENT"                                        = var.environment
    "JIRA_DEBUG_LOG_CONTENT"                             = tostring(var.jira_debug_log_content)
    "JIRA_DEBUG_LOG_CONTENT_ISSUE_KEY"                   = var.jira_debug_log_content_issue_key
    "JIRA_DEBUG_LOG_CONTENT_UNTIL"                       = var.jira_debug_log_content_until
    "AzureFunctionsJobHost__logging__logLevel__default"  = upper(var.log_level) == "DEBUG" ? "Debug" : "Information"
    "AzureFunctionsJobHost__logging__logLevel__Function" = upper(var.log_level) == "DEBUG" ? "Debug" : "Information"
  }

  tags = var.tags
}
