"""Confluence REST API client for Knowledge Base integration."""

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from src.kb.models import KBChunkMatch, KBPage
from src.utils.logger import setup_logger

logger = setup_logger("confluence-client")


def is_same_domain(url: str, base_url: str) -> bool:
    """Verifica se a URL indicada pertence estritamente ao mesmo domínio da base_url."""
    if not url or not base_url:
        return False
    parsed_base = urlparse(base_url)
    parsed_url = urlparse(url)

    # Esquemas não-HTTP (ex: javascript:, mailto:) são rejeitados
    if parsed_url.scheme and parsed_url.scheme not in ("http", "https"):
        return False

    # Links relativos (sem netloc e sem scheme) pertencem ao mesmo domínio
    if not parsed_url.netloc and not parsed_url.scheme:
        return True

    # Compara netloc em minúsculas
    base_host = parsed_base.netloc.lower()
    url_host = parsed_url.netloc.lower()
    return base_host == url_host


def resolve_url(url: str, base_url: str) -> str:
    """Resolve uma URL relativa para o endereço absoluto no domínio Confluence."""
    if not url:
        return base_url
    parsed_base = urlparse(base_url)
    parsed_url = urlparse(url)
    if parsed_url.netloc:
        return url

    base_root = f"{parsed_base.scheme}://{parsed_base.netloc}"
    path = parsed_url.path
    if path.startswith("/spaces/") and parsed_base.path.rstrip("/") == "/wiki":
        path = f"/wiki{path}"
    elif not path.startswith("/"):
        base_path = parsed_base.path.rstrip("/")
        path = f"{base_path}/{path}" if base_path else f"/{path}"

    resolved = f"{base_root}{path}"
    if parsed_url.query:
        resolved = f"{resolved}?{parsed_url.query}"
    if parsed_url.fragment:
        resolved = f"{resolved}#{parsed_url.fragment}"
    return resolved


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

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__()
        self.base_url = base_url
        self.text_parts: list[str] = []
        self._ignore_stack: list[str] = []
        self.same_domain_links: list[dict[str, str]] = []
        self._current_link: dict[str, Any] | None = None
        self._current_ac_link: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in self.IGNORED_TAGS:
            self._ignore_stack.append(tag_lower)
            return

        if self._ignore_stack:
            return

        attrs_dict = dict(attrs)

        if tag_lower == "a":
            href = attrs_dict.get("href")
            if href:
                full_url = resolve_url(href, self.base_url) if self.base_url else href
                self._current_link = {
                    "url": full_url,
                    "text_parts": [],
                }
        elif tag_lower == "ri:page":
            title = attrs_dict.get("ri:content-title")
            space = attrs_dict.get("ri:space-key")
            if title and self._current_ac_link is not None:
                self._current_ac_link["title"] = title
                if space:
                    self._current_ac_link["space"] = space
        elif tag_lower == "ac:link":
            self._current_ac_link = {"title": None, "space": None, "text_parts": []}
        elif tag_lower == "li":
            self.text_parts.append("\n- ")
        elif (
            tag_lower in self.BLOCK_TAGS
            and self.text_parts
            and not self.text_parts[-1].endswith("\n")
        ):
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if self._ignore_stack and self._ignore_stack[-1] == tag_lower:
            self._ignore_stack.pop()
            return

        if self._ignore_stack:
            return

        if tag_lower == "a":
            if self._current_link:
                link_text = "".join(self._current_link["text_parts"]).strip()
                url = self._current_link["url"]
                if url:
                    if url not in link_text:
                        self.text_parts.append(f" ({url})")
                    if not any(link_item["url"] == url for link_item in self.same_domain_links):
                        self.same_domain_links.append({"text": link_text, "url": url})
                self._current_link = None
        elif tag_lower == "ac:link":
            if self._current_ac_link:
                title = self._current_ac_link.get("title")
                link_text = "".join(self._current_ac_link["text_parts"]).strip() or title
                if title:
                    url_hint = (
                        f"{self.base_url}/display/{self._current_ac_link.get('space', '')}/{quote(title)}"
                        if self.base_url
                        else title
                    )
                    if not any(
                        link_item.get("title") == title for link_item in self.same_domain_links
                    ):
                        self.same_domain_links.append(
                            {"text": link_text or title, "title": title, "url": url_hint}
                        )
                self._current_ac_link = None
        elif (
            tag_lower in self.BLOCK_TAGS
            and self.text_parts
            and not self.text_parts[-1].endswith("\n")
        ):
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignore_stack:
            self.text_parts.append(data)
            if self._current_link:
                self._current_link["text_parts"].append(data)
            if self._current_ac_link:
                self._current_ac_link["text_parts"].append(data)

    def get_text(self) -> str:
        raw = "".join(self.text_parts)
        decoded = unescape(raw)
        # Normalizar espaços múltiplos e linhas vazias excessivas
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in decoded.splitlines()]
        cleaned = "\n".join(line for line in lines if line)
        return cleaned


def clean_confluence_html_with_links(
    html_content: str, base_url: str | None = None
) -> tuple[str, list[dict[str, str]]]:
    """Converte conteúdo HTML/XHTML do Confluence em texto limpo e extrai links do mesmo domínio."""
    if not html_content:
        return "", []
    parser = ConfluenceHTMLCleaner(base_url=base_url)
    parser.feed(html_content)
    return parser.get_text(), parser.same_domain_links


def clean_confluence_html(html_content: str, base_url: str | None = None) -> str:
    """Converte conteúdo HTML/XHTML do Confluence em texto limpo."""
    text, _ = clean_confluence_html_with_links(html_content, base_url=base_url)
    return text


class WebDocCleaner(HTMLParser):
    """Extrai texto e links internos estritamente do mesmo domínio de uma página web de suporte de produto."""

    def __init__(self, allowed_domain: str | None = None) -> None:
        super().__init__()
        self.allowed_domain = allowed_domain.lower() if allowed_domain else None
        self.texts: list[str] = []
        self.same_domain_links: list[dict[str, str]] = []
        self._current_link: dict[str, Any] | None = None
        self.ignore_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in ("script", "style", "nav", "header", "footer", "noscript", "svg", "button"):
            self.ignore_depth += 1
            return
        if self.ignore_depth > 0:
            return

        if tag_lower == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href")
            if href:
                p = urlparse(href)
                is_same = not p.netloc or p.netloc.lower() == self.allowed_domain
                if is_same and not p.netloc and self.allowed_domain:
                    href = f"https://{self.allowed_domain}{href if href.startswith('/') else '/' + href}"
                self._current_link = {
                    "url": href,
                    "is_same": is_same,
                    "text_parts": [],
                }
        elif tag_lower in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "div", "tr", "br"):
            if self.texts and not self.texts[-1].endswith("\n"):
                self.texts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in ("script", "style", "nav", "header", "footer", "noscript", "svg", "button"):
            self.ignore_depth = max(0, self.ignore_depth - 1)
            return
        if self.ignore_depth > 0:
            return

        if tag_lower == "a" and self._current_link:
            if self._current_link["is_same"]:
                u = self._current_link["url"]
                t = "".join(self._current_link["text_parts"]).strip()
                if u and not any(link_item["url"] == u for link_item in self.same_domain_links):
                    self.same_domain_links.append({"text": t, "url": u})
            self._current_link = None
        elif tag_lower in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "div", "tr", "br"):
            if self.texts and not self.texts[-1].endswith("\n"):
                self.texts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.ignore_depth == 0:
            self.texts.append(data)
            if self._current_link:
                self._current_link["text_parts"].append(data)

    def get_text(self) -> str:
        raw = "".join(self.texts)
        decoded = unescape(raw)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in decoded.splitlines()]
        return "\n".join(line for line in lines if line)


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
        if parsed_url.scheme != "https" or not parsed_url.netloc:
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
                text, links = clean_confluence_html_with_links(body_storage, base_url=self.base_url)
                webui = item.get("_links", {}).get(
                    "webui", f"/spaces/{target_space}/pages/{page_id}"
                )
                full_url = resolve_url(webui, self.base_url)

                pages.append(
                    KBPage(
                        id=page_id,
                        title=title,
                        url=full_url,
                        space_key=target_space,
                        version=version,
                        text=text,
                        same_domain_links=links,
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
            full_url = resolve_url(webui, self.base_url)
            text, links = clean_confluence_html_with_links(body_storage, base_url=self.base_url)

            return KBPage(
                id=page_id,
                title=title,
                url=full_url,
                space_key=space_key,
                version=version,
                text=text,
                same_domain_links=links,
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
                text, links = clean_confluence_html_with_links(body_storage, base_url=self.base_url)
                webui = item.get("_links", {}).get(
                    "webui", f"/spaces/{target_space}/pages/{page_id}"
                )
                full_url = resolve_url(webui, self.base_url)

                # Extrai trecho mais relevante em torno do termo pesquisado se possível
                snippet = self._extract_snippet(text, query)

                matches.append(
                    KBChunkMatch(
                        chunk_id=f"direct_{page_id}_{idx}",
                        title=title,
                        url=full_url,
                        content=snippet or text[:500],
                        score=0.85 - (idx * 0.1),
                        same_domain_links=links,
                    )
                )

            return matches
        except Exception as exc:
            logger.error("Erro na busca direta do Confluence (fallback): %s", exc)
            return []

    def read_link(self, url: str) -> dict[str, Any]:
        """Lê o conteúdo de um link (Confluence ou documentação web de produto), restrito ao mesmo domínio do link."""
        parsed_url = urlparse(url)
        if parsed_url.scheme and parsed_url.scheme not in ("http", "https"):
            return {
                "success": False,
                "url": url,
                "error": "Esquema de URL inválido.",
                "same_domain": False,
                "content": "",
            }

        resolved_url = resolve_url(url, self.base_url)

        # 1. Se for link do Confluence
        if is_same_domain(resolved_url, self.base_url):
            page_id_match = re.search(r"/pages/(\d+)", resolved_url) or re.search(
                r"pageId=(\d+)", resolved_url
            )
            if page_id_match:
                page_id = page_id_match.group(1)
                page = self.get_page(page_id)
                if page:
                    return {
                        "success": True,
                        "url": resolved_url,
                        "title": page.title,
                        "content": page.text,
                        "same_domain": True,
                        "same_domain_links": page.same_domain_links,
                    }

            try:
                parsed = urlparse(resolved_url)
                path = parsed.path
                if parsed.query:
                    path = f"{path}?{parsed.query}"

                base_parsed = urlparse(self.base_url)
                base_path = base_parsed.path.rstrip("/")
                if base_path and path.startswith(base_path):
                    rel_path = path[len(base_path) :]
                    if not rel_path.startswith("/"):
                        rel_path = f"/{rel_path}"
                else:
                    rel_path = path

                response = self._client.get(rel_path)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    data = response.json()
                    body = data.get("body", {}).get("storage", {}).get("value", "")
                    title = data.get("title", "")
                    text, links = (
                        clean_confluence_html_with_links(body, base_url=self.base_url)
                        if body
                        else (str(data), [])
                    )
                else:
                    title = ""
                    text, links = clean_confluence_html_with_links(
                        response.text, base_url=self.base_url
                    )

                return {
                    "success": True,
                    "url": resolved_url,
                    "title": title,
                    "content": text,
                    "same_domain": True,
                    "same_domain_links": links,
                }
            except Exception as exc:
                logger.error("Erro ao ler link do Confluence %s: %s", resolved_url, exc)
                return {
                    "success": False,
                    "url": resolved_url,
                    "error": f"Erro ao acessar conteúdo do link: {exc}",
                    "same_domain": True,
                    "content": "",
                }

        # 2. Se for link web de documentação externa de produto
        try:
            target_domain = parsed_url.netloc.lower()
            resp = httpx.get(
                resolved_url,
                follow_redirects=True,
                timeout=12.0,
                headers={"User-Agent": "Mozilla/5.0 (compatible; OSB-Jira-Agent/1.0)"},
            )
            resp.raise_for_status()
            cleaner = WebDocCleaner(allowed_domain=target_domain)
            cleaner.feed(resp.text)
            text = cleaner.get_text()
            title_match = re.search(r"<title[^>]*>([^<]+)</title>", resp.text, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else resolved_url
            return {
                "success": True,
                "url": resolved_url,
                "title": title,
                "content": text,
                "same_domain": True,
                "same_domain_links": cleaner.same_domain_links,
            }
        except Exception as exc:
            logger.error("Erro ao ler documentação externa %s: %s", resolved_url, exc)
            return {
                "success": False,
                "url": resolved_url,
                "error": f"Erro ao acessar conteúdo do link: {exc}",
                "same_domain": True,
                "content": "",
            }

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
