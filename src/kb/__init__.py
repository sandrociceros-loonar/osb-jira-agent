"""Knowledge Base and RAG integration for OSB Jira Agent."""

from src.config import Settings, get_settings
from src.kb.cache import KBCacheManager
from src.kb.confluence_client import ConfluenceClient
from src.kb.rag_engine import RAGEngine

_rag_engine: RAGEngine | None = None
_cache_manager: KBCacheManager | None = None
_confluence_client: ConfluenceClient | None = None


def get_confluence_client(settings: Settings | None = None) -> ConfluenceClient:
    """Retorna o cliente Confluence configurado."""
    global _confluence_client
    if _confluence_client is None:
        cfg = settings or get_settings()
        email = cfg.confluence_api_email or cfg.jira_api_email
        token = cfg.confluence_api_token or cfg.jira_api_token
        _confluence_client = ConfluenceClient(
            base_url=cfg.confluence_base_url,
            space_key=cfg.confluence_space_key,
            email=email,
            token=token,
        )
    return _confluence_client


def get_kb_cache_manager(settings: Settings | None = None) -> KBCacheManager:
    """Retorna o gerenciador de cache da base de conhecimento."""
    global _cache_manager
    if _cache_manager is None:
        cfg = settings or get_settings()
        _cache_manager = KBCacheManager(
            cache_dir=cfg.kb_cache_dir,
            space_key=cfg.confluence_space_key,
            ttl_seconds=cfg.kb_cache_ttl_seconds,
        )
    return _cache_manager


def get_rag_engine(settings: Settings | None = None) -> RAGEngine:
    """Retorna a instância singleton do motor RAG."""
    global _rag_engine
    if _rag_engine is None:
        cfg = settings or get_settings()
        client = get_confluence_client(cfg)
        cache = get_kb_cache_manager(cfg)
        _rag_engine = RAGEngine(
            confluence_client=client,
            cache_manager=cache,
            min_confidence_score=cfg.kb_min_confidence_score,
            space_key=cfg.confluence_space_key,
        )
    return _rag_engine


__all__ = [
    "ConfluenceClient",
    "KBCacheManager",
    "RAGEngine",
    "get_confluence_client",
    "get_kb_cache_manager",
    "get_rag_engine",
]
