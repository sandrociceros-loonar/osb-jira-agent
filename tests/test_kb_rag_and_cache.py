"""Tests for Knowledge Base Cache and RAG Engine, including direct Confluence fallback."""

from unittest.mock import MagicMock

from src.kb.cache import KBCacheManager
from src.kb.models import KBChunk, KBChunkMatch, KBPage
from src.kb.rag_engine import RAGEngine, tokenize


def test_text_normalization_and_tokenization():
    raw = "Vocês têm suporte 24/7 e garantia de devolução?"
    tokens = tokenize(raw)
    assert "suporte" in tokens
    assert "24" in tokens
    assert "garantia" in tokens
    assert "devolucao" in tokens
    # stop words filtradas
    assert "tem" not in tokens
    assert "de" not in tokens


def test_cache_manager_save_load_and_invalidate(tmp_path):
    cache = KBCacheManager(cache_dir=tmp_path, space_key="osbjiraage", ttl_seconds=3600)
    assert not cache.is_valid()
    assert cache.get_chunks() == []

    pages = [
        KBPage(
            id="1",
            title="Página 1",
            url="https://wiki/1",
            space_key="osbjiraage",
            text="Conteúdo de teste para a base.",
        )
    ]
    chunks = [
        KBChunk(
            chunk_id="1_0",
            page_id="1",
            page_title="Página 1",
            page_url="https://wiki/1",
            content="Conteúdo de teste para a base.",
            chunk_index=0,
        )
    ]

    cache.save_cache(pages, chunks)
    assert cache.is_valid()
    loaded_chunks = cache.get_chunks()
    assert len(loaded_chunks) == 1
    assert loaded_chunks[0].chunk_id == "1_0"

    # Testar nova instância lendo do disco
    cache2 = KBCacheManager(cache_dir=tmp_path, space_key="osbjiraage", ttl_seconds=3600)
    loaded_from_disk = cache2.load_from_disk()
    assert loaded_from_disk is not None
    assert len(loaded_from_disk) == 1

    # Invalidação
    cache.invalidate()
    assert not cache.cache_file.exists()


def test_cache_manager_updating_state(tmp_path):
    cache = KBCacheManager(cache_dir=tmp_path, space_key="osbjiraage")
    assert not cache.is_updating()

    cache.set_updating(True)
    assert cache.is_updating()

    cache.set_updating(False)
    assert not cache.is_updating()


def test_rag_engine_chunking():
    page = KBPage(
        id="10",
        title="Termos de Licenciamento",
        url="https://wiki/10",
        space_key="osbjiraage",
        text="Primeiro parágrafo de regras.\n\nSegundo parágrafo com detalhes de preços.\n\nTerceiro parágrafo de suporte.",
    )
    mock_client = MagicMock()
    mock_cache = MagicMock()
    engine = RAGEngine(confluence_client=mock_client, cache_manager=mock_cache)

    chunks = engine.chunk_page(page, chunk_size=80, overlap=20)
    assert len(chunks) >= 2
    for c in chunks:
        assert "[Artigo: Termos de Licenciamento]" in c.content


def test_rag_engine_bm25_search_finds_relevant_answer(tmp_path):
    cache = KBCacheManager(cache_dir=tmp_path, space_key="osbjiraage")
    mock_client = MagicMock()
    engine = RAGEngine(
        confluence_client=mock_client,
        cache_manager=cache,
        min_confidence_score=0.35,
    )

    pages = [
        KBPage(
            id="1",
            title="Formas de Pagamento e Faturamento",
            url="https://wiki/1",
            space_key="osbjiraage",
            text="Aceitamos boleto bancário faturado em 28 dias e cartão de crédito corporativo.",
        ),
        KBPage(
            id="2",
            title="Política de Suporte e SLA",
            url="https://wiki/2",
            space_key="osbjiraage",
            text="O suporte padrão opera em horário comercial das 9h às 18h com SLA de 4 horas.",
        ),
    ]

    chunks = []
    for p in pages:
        chunks.extend(engine.chunk_page(p))
    cache.save_cache(pages, chunks)

    # Busca por formas de pagamento
    res = engine.search("Quais são as formas de pagamento aceitas e prazo de faturamento?")
    assert res.found
    assert res.confidence_score >= 0.35
    assert not res.fallback_used
    assert res.source == "cache"
    assert len(res.matches) >= 1
    assert "Formas de Pagamento" in res.matches[0].title
    assert "boleto bancário" in res.matches[0].content


def test_rag_engine_search_low_relevance_returns_not_found(tmp_path):
    cache = KBCacheManager(cache_dir=tmp_path, space_key="osbjiraage")
    mock_client = MagicMock()
    engine = RAGEngine(
        confluence_client=mock_client,
        cache_manager=cache,
        min_confidence_score=0.4,
    )

    pages = [
        KBPage(
            id="1",
            title="Guia do Software X",
            url="https://wiki/1",
            space_key="osbjiraage",
            text="Instruções técnicas para instalação do cliente VPN e drivers de impressora.",
        )
    ]
    chunks = engine.chunk_page(pages[0])
    cache.save_cache(pages, chunks)

    # Dúvida não abordada
    res = engine.search("Vocês têm filial física em Tóquio para visita presencial?")
    assert not res.found
    assert res.confidence_score < 0.4
    assert not res.fallback_used


def test_rag_engine_fallback_to_confluence_when_cache_updating(tmp_path):
    """Requisito crítico: quando o cache estiver em atualização, aciona fallback direto ao Confluence."""
    cache = KBCacheManager(cache_dir=tmp_path, space_key="osbjiraage")
    # Colocar o cache explicitamente em estado de atualização
    cache.set_updating(True)

    mock_client = MagicMock()
    mock_client.search_space_direct.return_value = [
        KBChunkMatch(
            chunk_id="direct_99_0",
            title="Artigo Confluence Direto",
            url="https://wiki/direct/99",
            content="Resposta obtida diretamente da API do Confluence durante atualização do cache.",
            score=0.85,
        )
    ]

    engine = RAGEngine(
        confluence_client=mock_client,
        cache_manager=cache,
        min_confidence_score=0.35,
    )

    res = engine.search("Qual é o prazo de entrega?")
    assert res.found
    assert res.fallback_used is True
    assert res.source == "direct_confluence_fallback"
    assert len(res.matches) == 1
    assert res.matches[0].title == "Artigo Confluence Direto"
    mock_client.search_space_direct.assert_called_once_with(
        query="Qual é o prazo de entrega?",
        space_key="osbjiraage",
        limit=3,
    )
