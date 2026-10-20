"""Data models for Confluence Knowledge Base, Cache, and RAG."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class KBPage(BaseModel):
    """Representação de uma página obtida do Confluence."""

    id: str
    title: str
    url: str
    space_key: str
    version: int = 1
    text: str = ""
    same_domain_links: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KBChunk(BaseModel):
    """Chunk de texto indexado para busca RAG."""

    chunk_id: str
    page_id: str
    page_title: str
    page_url: str
    content: str
    chunk_index: int = 0
    same_domain_links: list[dict[str, Any]] = Field(default_factory=list)


class KBChunkMatch(BaseModel):
    """Resultado correspondente de um chunk na busca RAG."""

    chunk_id: str
    title: str
    url: str
    content: str
    score: float
    same_domain_links: list[dict[str, Any]] = Field(default_factory=list)


class KBSearchResult(BaseModel):
    """Resultado consolidado da busca na Base de Conhecimento."""

    query: str
    found: bool
    confidence_score: float
    matches: list[KBChunkMatch] = Field(default_factory=list)
    fallback_used: bool = False
    source: str = "cache"
    message: str = ""


class ConfluenceWebhookPayload(BaseModel):
    """Payload de webhook enviado pelo Confluence ou trigger de atualização."""

    event: str | None = None
    action: str | None = None
    space_key: str | None = None
    page_id: str | None = None
    page_title: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
