terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}
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

# Módulo 1: Azure AI Foundry (AIServices & GPT-4o Model Deployment)
module "ai_foundry" {
  source              = "./modules/ai_foundry"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  hub_name            = "${var.prefix}-ai-${random_string.suffix.result}"
  project_name        = "${var.prefix}-proj-${var.environment}"
  tags                = var.tags
}

# Módulo 2: Azure Key Vault (Segurança e segredos)
module "key_vault" {
  source              = "./modules/key_vault"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  key_vault_name      = "${var.prefix}kv${random_string.suffix.result}"
  jira_webhook_secret = var.jira_webhook_secret
  jira_api_token      = var.jira_api_token
  tags                = var.tags
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
    # O endpoint explícito é preferido; a string de conexão permanece para compatibilidade.
    "AZURE_AI_PROJECT_ENDPOINT"          = var.azure_ai_project_endpoint
    "AZURE_AI_PROJECT_CONNECTION_STRING" = "${module.ai_foundry.ai_services_endpoint};00000000-0000-0000-0000-000000000000;${azurerm_resource_group.rg.name};${var.prefix}-proj-${var.environment}"
    "AZURE_AI_MODEL_DEPLOYMENT_NAME"     = module.ai_foundry.model_deployment_name
    "AZURE_AI_MAX_TOOL_CALLS"            = "16"
    "JIRA_WEBHOOK_SECRET"                = "@Microsoft.KeyVault(VaultName=${module.key_vault.key_vault_name};SecretName=${module.key_vault.secret_jira_webhook_name})"
    "JIRA_WEBHOOK_SECRET_HEADER"         = "X-Atlassian-Webhook-Secret"
    "JIRA_INSTANCE_URL"                  = var.jira_instance_url
    "JIRA_PROJECT_KEY"                   = var.jira_project_key
    "JIRA_ALLOWED_PROJECT_KEYS"          = jsonencode(var.jira_allowed_project_keys)
    "JIRA_LEAD_PROJECT_KEY"              = var.jira_lead_project_key
    "JIRA_LEAD_ISSUE_TYPE_ID"            = var.jira_lead_issue_type_id
    "JIRA_ENABLE_WRITE_OPERATIONS"       = tostring(var.jira_enable_write_operations)
    "JIRA_TRANSITION_IDS"                = jsonencode(var.jira_transition_ids)
    "JIRA_API_EMAIL"                     = var.jira_api_email
    "JIRA_API_TOKEN"                     = var.jira_api_token == "" ? "" : "@Microsoft.KeyVault(VaultName=${module.key_vault.key_vault_name};SecretName=${module.key_vault.secret_jira_api_token_name})"
    "JIRA_TEAM_ACCOUNT_IDS"              = jsonencode(var.jira_team_account_ids)
    "ENVIRONMENT"                        = var.environment
  }

  tags = var.tags
}
