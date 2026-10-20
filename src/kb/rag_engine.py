"""Retrieval-Augmented Generation (RAG) engine for Confluence Knowledge Base."""

import math
import re
import unicodedata
from collections import Counter
from typing import Any
from urllib.parse import urlparse

from src.kb.cache import KBCacheManager
from src.kb.confluence_client import ConfluenceClient, is_same_domain, resolve_url
from src.kb.models import KBChunk, KBChunkMatch, KBPage, KBSearchResult
from src.utils.logger import setup_logger

logger = setup_logger("kb-rag")

PORTUGUESE_STOP_WORDS = {
    "a",
    "ao",
    "aos",
    "aquela",
    "aquelas",
    "aquele",
    "aqueles",
    "aquilo",
    "as",
    "ate",
    "com",
    "como",
    "da",
    "das",
    "de",
    "dela",
    "delas",
    "dele",
    "deles",
    "depois",
    "do",
    "dos",
    "e",
    "ela",
    "elas",
    "ele",
    "eles",
    "em",
    "entre",
    "era",
    "eram",
    "eramos",
    "essa",
    "essas",
    "esse",
    "esses",
    "esta",
    "estamos",
    "estas",
    "estava",
    "estavam",
    "este",
    "estes",
    "estou",
    "eu",
    "foi",
    "fomos",
    "foram",
    "isso",
    "isto",
    "ja",
    "lhe",
    "lhes",
    "mais",
    "mas",
    "me",
    "mesmo",
    "meu",
    "meus",
    "minha",
    "minhas",
    "muito",
    "na",
    "nas",
    "nao",
    "nem",
    "no",
    "nos",
    "nossa",
    "nossas",
    "nosso",
    "nossos",
    "num",
    "numa",
    "o",
    "os",
    "ou",
    "para",
    "pela",
    "pelas",
    "pelo",
    "pelos",
    "por",
    "qual",
    "quando",
    "que",
    "quem",
    "se",
    "seja",
    "sejam",
    "sem",
    "ser",
    "sera",
    "serao",
    "seu",
    "seus",
    "so",
    "sua",
    "suas",
    "tambem",
    "te",
    "tem",
    "temos",
    "tenho",
    "ter",
    "teu",
    "teus",
    "tinha",
    "tinham",
    "tu",
    "tua",
    "tuas",
    "um",
    "uma",
    "umas",
    "uns",
    "voce",
    "voces",
    "vos",
    "sobre",
    "qualquer",
    "pode",
    "podem",
    "duvida",
}


def normalize_text(text: str) -> str:
    """Normaliza texto removendo acentos, convertendo para minúsculas e pontuações."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return without_accents.lower()


def tokenize(text: str) -> list[str]:
    """Extrai tokens significativos do texto em português."""
    normalized = normalize_text(text)
    words = re.findall(r"[a-z0-9_]{2,}", normalized)
    return [w for w in words if w not in PORTUGUESE_STOP_WORDS]


class RAGEngine:
    """Orquestrador RAG: chunking, indexação BM25, busca em cache e fallback direto Confluence."""

    def __init__(
        self,
        confluence_client: ConfluenceClient,
        cache_manager: KBCacheManager,
        min_confidence_score: float = 0.15,
        space_key: str = "osbjiraage",
    ) -> None:
        self.confluence_client = confluence_client
        self.cache_manager = cache_manager
        self.min_confidence_score = min_confidence_score
        self.space_key = space_key.strip()

    def chunk_page(
        self,
        page: KBPage,
        chunk_size: int = 600,
        overlap: int = 120,
    ) -> list[KBChunk]:
        """Divide o texto da página em chunks coerentes preservando o contexto do título."""
        text = page.text.strip()
        if not text:
            return []

        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        chunks: list[KBChunk] = []

        current_text = ""
        chunk_index = 0

        for p in paragraphs:
            if len(current_text) + len(p) + 1 <= chunk_size:
                current_text = f"{current_text}\n{p}".strip() if current_text else p
            else:
                if current_text:
                    content = f"[Artigo: {page.title}]\n{current_text}"
                    chunks.append(
                        KBChunk(
                            chunk_id=f"{page.id}_{chunk_index}",
                            page_id=page.id,
                            page_title=page.title,
                            page_url=page.url,
                            content=content,
                            chunk_index=chunk_index,
                            same_domain_links=page.same_domain_links,
                        )
                    )
                    chunk_index += 1

                # Mantém o overlap pegando o final do chunk anterior
                if overlap > 0 and len(current_text) > overlap:
                    tail = current_text[-overlap:]
                    current_text = f"{tail}\n{p}".strip()
                else:
                    current_text = p

        if current_text:
            content = f"[Artigo: {page.title}]\n{current_text}"
            chunks.append(
                KBChunk(
                    chunk_id=f"{page.id}_{chunk_index}",
                    page_id=page.id,
                    page_title=page.title,
                    page_url=page.url,
                    content=content,
                    chunk_index=chunk_index,
                    same_domain_links=page.same_domain_links,
                )
            )

        return chunks

    def read_link(self, url: str) -> dict[str, Any]:
        """Lê o conteúdo de um link (Confluence ou suporte web) com verificação e consulta em cache."""
        base_url = self.confluence_client.base_url
        resolved_url = resolve_url(url, base_url)

        # 1. Verificar se a página consta no cache em memória
        for page in self.cache_manager.get_pages():
            if page.url == resolved_url or (
                re.search(r"/pages/(\d+)", resolved_url)
                and page.id == re.search(r"/pages/(\d+)", resolved_url).group(1)
            ):
                return {
                    "success": True,
                    "url": resolved_url,
                    "title": page.title,
                    "content": page.text,
                    "same_domain": True,
                    "same_domain_links": getattr(page, "same_domain_links", []),
                }

        # 2. Se pertencer ao domínio Confluence
        if is_same_domain(resolved_url, base_url):
            return self.confluence_client.read_link(resolved_url)

        # 3. Se for link referenciado em páginas em cache (ou mesmo domínio de link de suporte)
        cached_pages = self.cache_manager.get_pages()
        parsed_target = urlparse(resolved_url)
        is_allowed = False
        if parsed_target.netloc:
            for p in cached_pages:
                for lk in getattr(p, "same_domain_links", []):
                    lk_url = lk.get("url", "")
                    if lk_url == resolved_url or (
                        urlparse(lk_url).netloc
                        and urlparse(lk_url).netloc.lower() == parsed_target.netloc.lower()
                    ):
                        is_allowed = True
                        break
                if is_allowed:
                    break

        if is_allowed:
            return self.confluence_client.read_link(resolved_url)

        # 4. Caso contrário, bloquear link externo não autorizado
        return {
            "success": False,
            "url": resolved_url,
            "error": "Acesso negado: apenas links no mesmo domínio da base de conhecimento Confluence são permitidos.",
            "same_domain": False,
            "content": "",
        }

    def _enrich_matches_with_link_contents(self, matches: list[KBChunkMatch]) -> None:
        """Carrega o conteúdo dos links do mesmo domínio presentes nos matches."""
        for match in matches:
            resolved_links: list[dict[str, Any]] = []
            for link_info in getattr(match, "same_domain_links", [])[:3]:
                link_url = link_info.get("url")
                if link_url:
                    link_res = self.read_link(link_url)
                    if link_res.get("success"):
                        raw_content = link_res.get("content", "")
                        # Limita o trecho do link a 800 caracteres para poupar consumo de tokens no prompt do modelo
                        preview_content = (
                            raw_content[:800] if len(raw_content) > 800 else raw_content
                        )
                        resolved_links.append(
                            {
                                "text": link_info.get("text", ""),
                                "title": link_res.get("title") or link_info.get("text", ""),
                                "url": link_url,
                                "content": preview_content,
                            }
                        )
                    else:
                        resolved_links.append(link_info)
            if resolved_links:
                match.same_domain_links = resolved_links

    def sync_cache(self, force: bool = False) -> dict[str, Any]:
        """Sincroniza o cache buscando todas as páginas do Confluence e gerando chunks."""
        self.cache_manager.set_updating(True)
        try:
            logger.info("Iniciando sincronização de cache para o espaço '%s'...", self.space_key)
            pages = self.confluence_client.get_space_pages(self.space_key)
            all_chunks: list[KBChunk] = []
            enriched_pages: list[KBPage] = list(pages)

            for page in pages:
                chunks = self.chunk_page(page)
                all_chunks.extend(chunks)

                # Buscar e indexar páginas de suporte de produtos referenciadas na KB
                for link_item in page.same_domain_links:
                    link_url = link_item.get("url")
                    if not link_url or is_same_domain(link_url, self.confluence_client.base_url):
                        continue
                    try:
                        logger.info("Indexando documentação de produto vinculada: %s", link_url)
                        link_res = self.confluence_client.read_link(link_url)
                        if link_res.get("success") and link_res.get("content"):
                            doc_title = link_res.get("title") or link_item.get("text") or link_url
                            doc_page = KBPage(
                                id=f"doc_{abs(hash(link_url))}",
                                title=doc_title,
                                url=link_url,
                                space_key=self.space_key,
                                text=link_res["content"],
                                same_domain_links=link_res.get("same_domain_links", []),
                            )
                            enriched_pages.append(doc_page)
                            doc_chunks = self.chunk_page(doc_page)
                            all_chunks.extend(doc_chunks)
                    except Exception as err:
                        logger.warning(
                            "Falha ao indexar documentação externa %s: %s", link_url, err
                        )

            self.cache_manager.save_cache(enriched_pages, all_chunks)
            logger.info(
                "Sincronização concluída: %d páginas, %d chunks no espaço '%s'.",
                len(enriched_pages),
                len(all_chunks),
                self.space_key,
            )
            return {
                "success": True,
                "space_key": self.space_key,
                "pages_count": len(enriched_pages),
                "chunks_count": len(all_chunks),
            }
        except Exception as exc:
            logger.error("Erro durante sincronização do cache Confluence: %s", exc, exc_info=True)
            return {
                "success": False,
                "error": str(exc),
                "space_key": self.space_key,
            }
        finally:
            self.cache_manager.set_updating(False)

    def search(self, query: str, top_k: int = 3) -> KBSearchResult:
        """Realiza busca RAG com suporte a fallback direto quando o cache estiver em atualização."""
        query_clean = query.strip()
        if not query_clean:
            return KBSearchResult(
                query=query,
                found=False,
                confidence_score=0.0,
                matches=[],
                fallback_used=False,
                source="empty_query",
                message="Consulta vazia fornecida.",
            )

        # Se a query for uma URL direta
        if re.match(r"^(https?://|/wiki/|/spaces/)", query_clean, re.IGNORECASE):
            link_res = self.read_link(query_clean)
            if not link_res.get("same_domain"):
                return KBSearchResult(
                    query=query,
                    found=False,
                    confidence_score=0.0,
                    matches=[],
                    fallback_used=False,
                    source="direct_link",
                    message="Acesso negado: apenas links no mesmo domínio da base de conhecimento Confluence são permitidos.",
                )
            if link_res.get("success"):
                match = KBChunkMatch(
                    chunk_id="link_direct",
                    title=link_res.get("title") or "Página Confluence Vinculada",
                    url=link_res.get("url", query_clean),
                    content=link_res.get("content", ""),
                    score=1.0,
                    same_domain_links=[],
                )
                return KBSearchResult(
                    query=query,
                    found=True,
                    confidence_score=1.0,
                    matches=[match],
                    fallback_used=False,
                    source="direct_link",
                    message="Conteúdo do link do mesmo domínio carregado com sucesso.",
                )
            return KBSearchResult(
                query=query,
                found=False,
                confidence_score=0.0,
                matches=[],
                fallback_used=False,
                source="direct_link",
                message=link_res.get("error", "Não foi possível carregar o conteúdo do link."),
            )

        # 1. Fallback se o cache estiver em atualização
        if self.cache_manager.is_updating():
            logger.info(
                "Cache da base de conhecimento está em atualização. "
                "Executando fallback: consulta direta ao Confluence."
            )
            return self._query_confluence_direct_fallback(query_clean, top_k)

        # 2. Obter chunks do cache
        chunks = self.cache_manager.get_chunks()
        if not chunks:
            # Se não houver chunks e não estiver atualizando, tenta carregar ou sincronizar
            logger.info("Cache vazio. Tentando sincronização sob demanda...")
            sync_res = self.sync_cache()
            if not sync_res.get("success"):
                logger.warning("Falha ao sincronizar cache sob demanda. Usando fallback direto.")
                return self._query_confluence_direct_fallback(query_clean, top_k)
            chunks = self.cache_manager.get_chunks()

        if not chunks:
            # Fallback direto caso ainda não existam chunks
            return self._query_confluence_direct_fallback(query_clean, top_k)

        # 3. Ranqueamento BM25 nos chunks cacheados
        matches = self._rank_chunks_bm25(query_clean, chunks, top_k=top_k)
        if not matches:
            return KBSearchResult(
                query=query,
                found=False,
                confidence_score=0.0,
                matches=[],
                fallback_used=False,
                source="cache",
                message="Nenhuma resposta encontrada na base de conhecimento para a dúvida.",
            )

        top_score = matches[0].score
        found = top_score >= self.min_confidence_score
        if found:
            self._enrich_matches_with_link_contents(matches)

        message = (
            f"Encontrados {len(matches)} artigo(s) relevante(s) na base de conhecimento."
            if found
            else "A base de conhecimento não possui informações conclusivas com confiança suficiente."
        )

        return KBSearchResult(
            query=query,
            found=found,
            confidence_score=round(top_score, 3),
            matches=matches if found else matches[:1],
            fallback_used=False,
            source="cache",
            message=message,
        )

    def _query_confluence_direct_fallback(self, query: str, limit: int = 3) -> KBSearchResult:
        """Executa consulta direta no Confluence via CQL quando o cache está em atualização."""
        direct_matches = self.confluence_client.search_space_direct(
            query=query,
            space_key=self.space_key,
            limit=limit,
        )

        if not direct_matches:
            return KBSearchResult(
                query=query,
                found=False,
                confidence_score=0.0,
                matches=[],
                fallback_used=True,
                source="direct_confluence_fallback",
                message="Nenhum resultado obtido na consulta direta ao Confluence (fallback).",
            )

        top_score = direct_matches[0].score
        found = top_score >= self.min_confidence_score
        if found:
            self._enrich_matches_with_link_contents(direct_matches)
        return KBSearchResult(
            query=query,
            found=found,
            confidence_score=round(top_score, 3),
            matches=direct_matches,
            fallback_used=True,
            source="direct_confluence_fallback",
            message=(
                "Resultado obtido via fallback direto no Confluence (cache em atualização)."
                if found
                else "Confluence consultado diretamente (fallback), mas sem relevância suficiente."
            ),
        )

    def _rank_chunks_bm25(
        self,
        query: str,
        chunks: list[KBChunk],
        top_k: int = 3,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> list[KBChunkMatch]:
        """Ranqueia chunks com BM25 + boost de título e correspondência de frase."""
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        query_normalized = normalize_text(query)
        num_chunks = len(chunks)

        # Pré-computar tokenização dos chunks e comprimentos
        chunk_tokens_list: list[list[str]] = [tokenize(c.content) for c in chunks]
        doc_lens = [len(toks) for toks in chunk_tokens_list]
        avgdl = max(sum(doc_lens) / num_chunks, 1.0)

        # Calcular document frequency (df) para cada termo da query
        df: Counter[str] = Counter()
        for toks in chunk_tokens_list:
            unique_terms = set(toks)
            for qt in query_tokens:
                if qt in unique_terms:
                    df[qt] += 1

        scored_matches: list[tuple[float, KBChunk]] = []

        for idx, chunk in enumerate(chunks):
            tokens = chunk_tokens_list[idx]
            doc_len = doc_lens[idx]
            if doc_len == 0:
                continue

            tf_counter = Counter(tokens)
            bm25_score = 0.0

            for qt in query_tokens:
                freq = tf_counter.get(qt, 0)
                if freq == 0:
                    continue
                doc_freq = df.get(qt, 0)
                # Fórmula IDF com suavização
                idf = math.log((num_chunks - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
                numerator = freq * (k1 + 1.0)
                denominator = freq + k1 * (1.0 - b + b * (doc_len / avgdl))
                bm25_score += idf * (numerator / denominator)

            if bm25_score <= 0.0:
                continue

            # Boost se os termos estiverem presentes no título do artigo
            title_norm = normalize_text(chunk.page_title)
            title_matches = sum(1 for qt in query_tokens if qt in title_norm)
            if title_matches > 0:
                bm25_score *= 1.0 + (0.5 * (title_matches / len(query_tokens)))

            # Boost se a frase exata ou substantivos contínuos constarem no texto
            content_norm = normalize_text(chunk.content)
            if query_normalized in content_norm:
                bm25_score *= 1.4

            # Normalização suave para intervalo [0.0, 1.0]
            normalized_score = bm25_score / (bm25_score + 4.0)

            scored_matches.append((normalized_score, chunk))

        scored_matches.sort(key=lambda x: x[0], reverse=True)

        results: list[KBChunkMatch] = []
        for score, chunk in scored_matches[:top_k]:
            results.append(
                KBChunkMatch(
                    chunk_id=chunk.chunk_id,
                    title=chunk.page_title,
                    url=chunk.page_url,
                    content=chunk.content,
                    score=score,
                    same_domain_links=chunk.same_domain_links,
                )
            )

        return results
