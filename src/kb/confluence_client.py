"""Confluence REST API client for Knowledge Base integration."""

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import quote, urlparse

import httpx

from src.kb.models import KBChunkMatch, KBPage
from src.utils.logger import setup_logger

logger = setup_logger("confluence-client")


class ConfluenceHTMLCleaner(HTMLParser):
    """Extrai texto legível de XHTML do formato de armazenamento do Confluence."""

    BLOCK_TAGS = {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "tr",
        "div",
        "blockquote",
        "pre",
        "br",
    }
    IGNORED_TAGS = {"script", "style", "ac:structured-macro"}

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self._ignore_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in self.IGNORED_TAGS:
            self._ignore_stack.append(tag_lower)
        elif tag_lower == "li":
            self.text_parts.append("\n- ")
        elif tag_lower in self.BLOCK_TAGS and self.text_parts and not self.text_parts[-1].endswith("\n"):
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if self._ignore_stack and self._ignore_stack[-1] == tag_lower:
            self._ignore_stack.pop()
        elif tag_lower in self.BLOCK_TAGS and self.text_parts and not self.text_parts[-1].endswith("\n"):
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignore_stack:
            self.text_parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self.text_parts)
        decoded = unescape(raw)
        # Normalizar espaços múltiplos e linhas vazias excessivas
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in decoded.splitlines()]
        cleaned = "\n".join(line for line in lines if line)
        return cleaned


def clean_confluence_html(html_content: str) -> str:
    """Converte conteúdo HTML/XHTML do Confluence em texto limpo."""
    if not html_content:
        return ""
    parser = ConfluenceHTMLCleaner()
    parser.feed(html_content)
    return parser.get_text()


class ConfluenceClient:
    """Cliente HTTP para a API REST do Confluence Cloud."""

    def __init__(
        self,
        base_url: str,
        space_key: str,
        email: str = "",
        token: str = "",
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        parsed_url = urlparse(base_url.rstrip("/"))
        if (
            parsed_url.scheme != "https"
            or not parsed_url.netloc
        ):
            raise ValueError("CONFLUENCE_BASE_URL deve ser uma URL HTTPS válida.")

        # Garantir que /wiki seja parte da base para Confluence Cloud se não estiver especificado
        path = parsed_url.path.rstrip("/")
        if not path:
            path = "/wiki"
        elif path.startswith("/wiki/spaces"):
            path = "/wiki"

        self.base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{path}"
        self.space_key = space_key.strip()
        self.email = email
        self.token = token
        self._transport = transport

        auth = httpx.BasicAuth(email, token) if email and token else None
        self._client = httpx.Client(
            base_url=self.base_url,
            auth=auth,
            headers={"Accept": "application/json"},
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ConfluenceClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get_space_pages(self, space_key: str | None = None, limit: int = 50) -> list[KBPage]:
        """Obtém todas as páginas do espaço Confluence indicado."""
        target_space = (space_key or self.space_key).strip()
        pages: list[KBPage] = []
        start = 0

        while True:
            params = {
                "spaceKey": target_space,
                "type": "page",
                "status": "current",
                "expand": "body.storage,version,title",
                "limit": limit,
                "start": start,
            }
            response = self._client.get("/rest/api/content", params=params)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not isinstance(results, list) or not results:
                break

            for item in results:
                page_id = str(item.get("id", ""))
                title = item.get("title", "")
                version = item.get("version", {}).get("number", 1)
                body_storage = item.get("body", {}).get("storage", {}).get("value", "")
                text = clean_confluence_html(body_storage)
                webui = item.get("_links", {}).get("webui", f"/spaces/{target_space}/pages/{page_id}")
                full_url = f"{self.base_url}{webui}" if webui.startswith("/") else webui

                pages.append(
                    KBPage(
                        id=page_id,
                        title=title,
                        url=full_url,
                        space_key=target_space,
                        version=version,
                        text=text,
                    )
                )

            size = data.get("size", len(results))
            if size < limit:
                break
            start += size

        logger.info(
            "Confluence: %d páginas carregadas com sucesso para o espaço '%s'.",
            len(pages),
            target_space,
        )
        return pages

    def get_page(self, page_id: str) -> KBPage | None:
        """Obtém uma página específica pelo ID."""
        try:
            response = self._client.get(
                f"/rest/api/content/{quote(page_id)}",
                params={"expand": "body.storage,version,title,space"},
            )
            response.raise_for_status()
            item = response.json()
            title = item.get("title", "")
            version = item.get("version", {}).get("number", 1)
            body_storage = item.get("body", {}).get("storage", {}).get("value", "")
            space_key = item.get("space", {}).get("key", self.space_key)
            webui = item.get("_links", {}).get("webui", f"/spaces/{space_key}/pages/{page_id}")
            full_url = f"{self.base_url}{webui}" if webui.startswith("/") else webui

            return KBPage(
                id=page_id,
                title=title,
                url=full_url,
                space_key=space_key,
                version=version,
                text=clean_confluence_html(body_storage),
            )
        except Exception as exc:
            logger.warning("Falha ao buscar página %s no Confluence: %s", page_id, exc)
            return None

    def search_space_direct(
        self,
        query: str,
        space_key: str | None = None,
        limit: int = 5,
    ) -> list[KBChunkMatch]:
        """Consulta direta no Confluence via CQL (utilizada como fallback durante atualização de cache)."""
        target_space = (space_key or self.space_key).strip()
        escaped_query = query.replace('"', '\\"').replace("'", "\\'")
        cql = f'space = "{target_space}" AND type = "page" AND text ~ "{escaped_query}"'

        logger.info("Executando busca direta Confluence CQL (fallback): %s", cql)
        try:
            response = self._client.get(
                "/rest/api/content/search",
                params={
                    "cql": cql,
                    "expand": "body.storage,version,title",
                    "limit": limit,
                },
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])

            matches: list[KBChunkMatch] = []
            for idx, item in enumerate(results):
                page_id = str(item.get("id", ""))
                title = item.get("title", "")
                body_storage = item.get("body", {}).get("storage", {}).get("value", "")
                text = clean_confluence_html(body_storage)
                webui = item.get("_links", {}).get("webui", f"/spaces/{target_space}/pages/{page_id}")
                full_url = f"{self.base_url}{webui}" if webui.startswith("/") else webui

                # Extrai trecho mais relevante em torno do termo pesquisado se possível
                snippet = self._extract_snippet(text, query)

                matches.append(
                    KBChunkMatch(
                        chunk_id=f"direct_{page_id}_{idx}",
                        title=title,
                        url=full_url,
                        content=snippet or text[:500],
                        score=0.85 - (idx * 0.1),
                    )
                )

            return matches
        except Exception as exc:
            logger.error("Erro na busca direta do Confluence (fallback): %s", exc)
            return []

    def _extract_snippet(self, text: str, query: str, window: int = 400) -> str:
        """Localiza a ocorrência de termos da consulta no texto e retorna trecho ao redor."""
        if not text:
            return ""
        words = [w for w in re.split(r"\W+", query) if len(w) > 3]
        if not words:
            return text[:window]

        pattern = "|".join(re.escape(w) for w in words)
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return text[:window]

        start = max(0, match.start() - 100)
        end = min(len(text), start + window)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        return snippet
