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


def test_rag_engine_read_link_from_cache_and_enforces_domain(tmp_path):
    cache = KBCacheManager(cache_dir=tmp_path, space_key="osbjiraage")
    mock_client = MagicMock()
    mock_client.base_url = "https://loonar-osb.atlassian.net/wiki"

    engine = RAGEngine(
        confluence_client=mock_client,
        cache_manager=cache,
        min_confidence_score=0.2,
    )

    page = KBPage(
        id="5001",
        title="Política de Licenças e Suporte",
        url="https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/5001",
        space_key="osbjiraage",
        text="Licenças do Produto X incluem 1 ano de atualização e suporte prioritário.",
    )
    cache.save_cache([page], engine.chunk_page(page))

    # Leitura do link que está no cache em memória
    res = engine.read_link("https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/5001")
    assert res["success"] is True
    assert res["same_domain"] is True
    assert res["title"] == "Política de Licenças e Suporte"
    assert "suporte prioritário" in res["content"]
    # Não precisou chamar o cliente Confluence porque estava em cache
    mock_client.read_link.assert_not_called()

    # Leitura de link externo deve ser bloqueada
    res_ext = engine.read_link("https://external-vendor.com/docs")
    assert res_ext["success"] is False
    assert res_ext["same_domain"] is False
    assert "apenas links no mesmo domínio" in res_ext["error"]


def test_rag_engine_search_enriches_matches_with_same_domain_links(tmp_path):
    cache = KBCacheManager(cache_dir=tmp_path, space_key="osbjiraage")
    mock_client = MagicMock()
    mock_client.base_url = "https://loonar-osb.atlassian.net/wiki"

    engine = RAGEngine(
        confluence_client=mock_client,
        cache_manager=cache,
        min_confidence_score=0.2,
    )

    # Página principal com link para outra página de suporte
    linked_page = KBPage(
        id="7002",
        title="Detalhes Técnicos de Suporte",
        url="https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/7002",
        space_key="osbjiraage",
        text="Atendimento 24/7 com tempo de resposta de até 30 minutos.",
    )

    main_page = KBPage(
        id="7001",
        title="FAQ Geral de Produtos",
        url="https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/7001",
        space_key="osbjiraage",
        text="Para suporte ao produto consulte Detalhes Técnicos (https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/7002).",
        same_domain_links=[
            {
                "text": "Detalhes Técnicos",
                "url": "https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/7002",
            }
        ],
    )

    all_pages = [main_page, linked_page]
    all_chunks = []
    for p in all_pages:
        all_chunks.extend(engine.chunk_page(p))
    cache.save_cache(all_pages, all_chunks)

    # Ao buscar pela dúvida, o match enriquece com o conteúdo do link do mesmo domínio
    res = engine.search("suporte ao produto")
    assert res.found is True
    assert len(res.matches) >= 1
    match = res.matches[0]
    assert len(match.same_domain_links) == 1
    link_info = match.same_domain_links[0]
    assert link_info["url"] == "https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/7002"
    assert "Atendimento 24/7 com tempo de resposta" in link_info["content"]


def test_rag_engine_search_with_direct_same_domain_url(tmp_path):
    cache = KBCacheManager(cache_dir=tmp_path, space_key="osbjiraage")
    mock_client = MagicMock()
    mock_client.base_url = "https://loonar-osb.atlassian.net/wiki"

    engine = RAGEngine(
        confluence_client=mock_client,
        cache_manager=cache,
        min_confidence_score=0.2,
    )

    page = KBPage(
        id="8001",
        title="Guia de Integração",
        url="https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/8001",
        space_key="osbjiraage",
        text="Documentação da API de integração para clientes.",
    )
    cache.save_cache([page], engine.chunk_page(page))

    # Query com URL direta do mesmo domínio
    res = engine.search("https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/8001")
    assert res.found is True
    assert res.confidence_score == 1.0
    assert len(res.matches) == 1
    assert "Documentação da API" in res.matches[0].content

    # Query com URL direta externa deve falhar
    res_ext = engine.search("https://external.com/hacker")
    assert res_ext.found is False
    assert "apenas links no mesmo domínio" in res_ext.message
