#!/usr/bin/env python3
"""Interactive and CLI utility to test the Confluence Knowledge Base, Cache, and RAG search."""

import argparse
import json
import sys
from pathlib import Path

# Garante que a raiz do repositório esteja no PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings
from src.kb import get_confluence_client, get_kb_cache_manager, get_rag_engine


def cmd_status() -> None:
    """Exibe o estado atual do cache da Base de Conhecimento."""
    settings = get_settings()
    cache = get_kb_cache_manager(settings)
    print("=== Status da Base de Conhecimento Confluence ===")
    print(f"Espaço configurado : {settings.confluence_space_key}")
    print(f"URL Confluence     : {settings.confluence_space_url}")
    print(f"Diretório de cache : {cache.cache_dir}")
    print(f"Arquivo de cache   : {cache.cache_file}")
    print(f"Existe em disco?   : {cache.cache_file.exists()}")
    print(f"Está atualizando?  : {cache.is_updating()}")
    print(f"Cache válido?      : {cache.is_valid()}")

    chunks = cache.get_chunks()
    print(f"Total de chunks    : {len(chunks)}")
    pages = cache.get_pages()
    print(f"Total de páginas   : {len(pages)}")
    if pages:
        print("\nPáginas indexadas:")
        for p in pages[:10]:
            print(f" - [{p.id}] {p.title} (v{p.version}) -> {p.url}")
        if len(pages) > 10:
            print(f"   ... e mais {len(pages) - 10} página(s)")


def cmd_sync(force: bool) -> None:
    """Dispara a sincronização do cache da base de conhecimento a partir do Confluence."""
    settings = get_settings()
    print(f"Iniciando sincronização com espaço '{settings.confluence_space_key}'...")
    rag = get_rag_engine(settings)
    res = rag.sync_cache(force=force)
    print("Resultado da sincronização:")
    print(json.dumps(res, indent=2, ensure_ascii=False))


def cmd_search(query: str, top_k: int = 3) -> None:
    """Executa uma busca RAG e exibe a relevância dos artigos."""
    settings = get_settings()
    print(f"Pesquisando na KB: '{query}' (top_k={top_k})...\n")
    rag = get_rag_engine(settings)
    result = rag.search(query=query, top_k=top_k)

    print(f"Encontrado?       : {result.found}")
    print(f"Score de confiança: {result.confidence_score} (mínimo: {settings.kb_min_confidence_score})")
    print(f"Fallback direto?  : {result.fallback_used}")
    print(f"Origem da resposta: {result.source}")
    print(f"Mensagem          : {result.message}\n")

    if result.matches:
        print("Trechos / Artigos encontrados:")
        for i, m in enumerate(result.matches, 1):
            print(f"\n[{i}] {m.title} (Score: {m.score:.3f})")
            print(f"    URL: {m.url}")
            print("    Conteúdo:")
            for line in m.content.splitlines():
                print(f"      {line}")
    else:
        print("Nenhum trecho correspondente foi encontrado.")


def cmd_direct_search(query: str, limit: int = 3) -> None:
    """Testa a consulta direta CQL ao Confluence (fallback)."""
    settings = get_settings()
    print(f"Testando busca direta Confluence CQL: '{query}'...")
    client = get_confluence_client(settings)
    matches = client.search_space_direct(query, limit=limit)
    print(f"Resultados encontrados: {len(matches)}")
    for i, m in enumerate(matches, 1):
        print(f"\n[{i}] {m.title} (Score: {m.score:.3f})")
        print(f"    URL: {m.url}")
        print(f"    Trecho: {m.content[:200]}...")


def main() -> None:
    parser = argparse.ArgumentParser(description="Utilitário de Teste da Base de Conhecimento (KB/RAG)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    subparsers.add_parser("status", help="Exibe status do cache e do espaço Confluence")

    # sync
    sync_p = subparsers.add_parser("sync", help="Sincroniza o cache Confluence localmente")
    sync_p.add_argument("--force", action="store_true", help="Força a recriação do cache")

    # search
    search_p = subparsers.add_parser("search", help="Executa busca RAG simulada")
    search_p.add_argument("--query", "-q", required=True, help="Dúvida a ser consultada")
    search_p.add_argument("--top-k", "-k", type=int, default=3, help="Número máximo de chunks")

    # direct
    direct_p = subparsers.add_parser("direct", help="Consulta direta CQL no Confluence (fallback)")
    direct_p.add_argument("--query", "-q", required=True, help="Termo de pesquisa direta")
    direct_p.add_argument("--limit", "-l", type=int, default=3, help="Limite de resultados")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
    elif args.command == "sync":
        cmd_sync(force=args.force)
    elif args.command == "search":
        cmd_search(query=args.query, top_k=args.top_k)
    elif args.command == "direct":
        cmd_direct_search(query=args.query, limit=args.limit)


if __name__ == "__main__":
    main()
