"""Azure AI Foundry Projects Client integration."""

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from src.config import get_settings
from src.utils.logger import setup_logger

logger = setup_logger("foundry-client")


class FoundryClientManager:
    """Gerenciador de conexão com o Azure AI Foundry utilizando DefaultAzureCredential."""

    def __init__(self, connection_string: str | None = None) -> None:
        self.settings = get_settings()
        self.connection_string = (
            connection_string or self.settings.azure_ai_project_connection_string
        )
        self._client: AIProjectClient | None = None
        self._credential: DefaultAzureCredential | None = None

    @property
    def credential(self) -> DefaultAzureCredential:
        """Retorna credencial Managed Identity / Azure CLI."""
        if self._credential is None:
            self._credential = DefaultAzureCredential()
        return self._credential

    def get_client(self) -> AIProjectClient:
        """Inicializa e retorna a instância do AIProjectClient."""
        if self._client is None:
            if not self.connection_string:
                raise ValueError(
                    "AZURE_AI_PROJECT_CONNECTION_STRING não foi configurada. "
                    "Verifique o .env ou as variáveis de ambiente."
                )
            logger.info("Inicializando AIProjectClient com DefaultAzureCredential...")
            self._client = AIProjectClient.from_connection_string(
                credential=self.credential,
                conn_str=self.connection_string,
            )
        return self._client


_manager_instance: FoundryClientManager | None = None


def get_foundry_manager() -> FoundryClientManager:
    """Retorna instância singleton do FoundryClientManager."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = FoundryClientManager()
    return _manager_instance
