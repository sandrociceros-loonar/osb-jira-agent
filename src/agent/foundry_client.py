"""Azure AI Foundry Projects Client integration."""

from urllib.parse import quote, urlparse

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai import OpenAI

from src.config import get_settings
from src.utils.logger import setup_logger

logger = setup_logger("foundry-client")


class FoundryClientManager:
    """Gerenciador de conexão com o Azure AI Foundry utilizando DefaultAzureCredential."""

    def __init__(
        self,
        connection_string: str | None = None,
        project_endpoint: str | None = None,
    ) -> None:
        self.settings = get_settings()
        self.connection_string = (
            connection_string or self.settings.azure_ai_project_connection_string
        )
        self.project_endpoint = project_endpoint or self.settings.azure_ai_project_endpoint
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
            endpoint = self.project_endpoint or self._endpoint_from_legacy_connection_string()
            if not endpoint:
                raise ValueError(
                    "AZURE_AI_PROJECT_ENDPOINT não foi configurado e não há string legada válida. "
                    "Verifique o .env ou as variáveis de ambiente."
                )
            parsed_endpoint = urlparse(endpoint)
            if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc:
                raise ValueError("AZURE_AI_PROJECT_ENDPOINT deve ser uma URL HTTPS.")
            logger.info("Inicializando AIProjectClient com DefaultAzureCredential...")
            self._client = AIProjectClient(
                endpoint=endpoint.rstrip("/"),
                credential=self.credential,
            )
        return self._client

    def get_openai_client(self) -> OpenAI:
        """Retorna um cliente para o provedor de modelo configurado."""
        if self.settings.model_provider == "foundry-local":
            return self._get_local_openai_client()
        if self.settings.model_provider == "ollama":
            return self._get_ollama_openai_client()
        return self.get_client().get_openai_client()

    def _get_ollama_openai_client(self) -> OpenAI:
        """Conecta ao endpoint OpenAI-compatible local do Ollama."""
        endpoint = self.settings.ollama_base_url.rstrip("/")
        parsed_endpoint = urlparse(endpoint)
        if parsed_endpoint.scheme not in ("http", "https") or not parsed_endpoint.netloc:
            raise ValueError("OLLAMA_BASE_URL deve ser uma URL HTTP(S) válida.")
        return OpenAI(base_url=endpoint, api_key="ollama")

    def _get_local_openai_client(self) -> OpenAI:
        """Inicializa o modelo local e expõe o servidor OpenAI-compatible."""
        from foundry_local_sdk import Configuration, FoundryLocalManager

        endpoint = self.settings.foundry_local_base_url.rstrip("/")
        parsed_endpoint = urlparse(endpoint)
        if parsed_endpoint.scheme not in ("http", "https") or not parsed_endpoint.netloc:
            raise ValueError("FOUNDRY_LOCAL_BASE_URL deve ser uma URL HTTP(S) válida.")

        service_url = endpoint.removesuffix("/v1")
        manager = FoundryLocalManager.instance
        if manager is None:
            configuration = Configuration(
                app_name="osb-jira-agent",
                web=Configuration.WebService(urls=service_url),
            )
            FoundryLocalManager.initialize(configuration)
            manager = FoundryLocalManager.instance

        if manager is None:
            raise RuntimeError("O SDK não inicializou o Foundry Local.")

        model = manager.catalog.get_model(self.settings.foundry_local_model_alias)
        if model is None:
            raise RuntimeError(
                f"Modelo Foundry Local '{self.settings.foundry_local_model_alias}' "
                "não está disponível no catálogo."
            )
        if not model.is_cached:
            raise RuntimeError(
                f"Modelo Foundry Local '{self.settings.foundry_local_model_alias}' não está "
                "instalado. Execute scripts/check-local-prereqs.sh --provider foundry-local."
            )
        if not model.is_loaded:
            model.load()
        if manager.urls is None:
            manager.start_web_service()

        logger.info(
            "Usando Foundry Local em %s com o modelo %s",
            self.settings.foundry_local_base_url,
            self.settings.foundry_local_model_alias,
        )
        return OpenAI(
            base_url=self.settings.foundry_local_base_url,
            api_key="foundry-local",
        )

    def _endpoint_from_legacy_connection_string(self) -> str | None:
        """Converte o formato legado host;subscription;resource-group;project em endpoint."""
        if not self.connection_string:
            return None
        parts = self.connection_string.split(";")
        if len(parts) != 4 or not all(part.strip() for part in parts):
            raise ValueError(
                "AZURE_AI_PROJECT_CONNECTION_STRING legada deve conter "
                "<host>;<subscription>;<resource-group>;<project>."
            )
        host, _, _, project_name = (part.strip() for part in parts)
        if "://" in host:
            parsed_host = urlparse(host)
            if parsed_host.scheme != "https" or not parsed_host.netloc or parsed_host.path not in (
                "",
                "/",
            ):
                raise ValueError("O host da string legada do projeto deve ser HTTPS.")
            host = parsed_host.netloc
        return f"https://{host}/api/projects/{quote(project_name, safe='')}"


_manager_instance: FoundryClientManager | None = None


def get_foundry_manager() -> FoundryClientManager:
    """Retorna instância singleton do FoundryClientManager."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = FoundryClientManager()
    return _manager_instance
