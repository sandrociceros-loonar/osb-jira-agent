"""Tests for Confluence REST API client, HTML cleaner, and direct CQL search."""

import httpx
import pytest

import src.kb as kb
from src.config import Settings
from src.kb.confluence_client import ConfluenceClient, clean_confluence_html


def test_confluence_client_reuses_jira_credentials_by_default(monkeypatch):
    monkeypatch.setattr(kb, "_confluence_client", None)
    settings = Settings(
        CONFLUENCE_BASE_URL="https://loonar-osb.atlassian.net/wiki",
        CONFLUENCE_SPACE_KEY="osbjiraage",
        JIRA_API_EMAIL="agent@example.com",
        JIRA_API_TOKEN="jira-api-token",
    )

    client = kb.get_confluence_client(settings)

    assert client.email == "agent@example.com"
    assert client.token == "jira-api-token"
    client.close()
    monkeypatch.setattr(kb, "_confluence_client", None)


def test_clean_confluence_html_extracts_clean_text():
    html_sample = """
    <h1>Política Comercial</h1>
    <p>O prazo de entrega padrão é de <strong>5 dias úteis</strong> após a confirmação do pagamento.</p>
    <ul>
        <li>Garantia: 12 meses</li>
        <li>Suporte 24/7 incluso para mais de 50 licenças</li>
    </ul>
    <script>alert("ignore");</script>
    <p>Dúvidas? Entre em contato &amp; consulte nossa equipe.</p>
    """
    text = clean_confluence_html(html_sample)
    assert "Política Comercial" in text
    assert "5 dias úteis" in text
    assert "- Garantia: 12 meses" in text
    assert "Suporte 24/7 incluso para mais de 50 licenças" in text
    assert "ignore" not in text
    assert "Entre em contato & consulte nossa equipe" in text


def test_confluence_client_url_normalization():
    client = ConfluenceClient(
        base_url="https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/",
        space_key="osbjiraage",
        email="test@example.com",
        token="secret-token",
    )
    assert client.base_url == "https://loonar-osb.atlassian.net/wiki"
    assert client.space_key == "osbjiraage"
    client.close()

    with pytest.raises(ValueError, match="HTTPS"):
        ConfluenceClient(base_url="http://insecure.net", space_key="test")


def test_confluence_client_get_space_pages():
    mock_response = {
        "results": [
            {
                "id": "1001",
                "title": "FAQ de Vendas",
                "version": {"number": 2},
                "body": {
                    "storage": {
                        "value": "<p>Oferecemos desconto progressivo a partir de 20 licenças.</p>"
                    }
                },
                "_links": {"webui": "/spaces/osbjiraage/pages/1001/faq"},
            }
        ],
        "size": 1,
        "limit": 50,
    }

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=mock_response, request=request)
    )

    with ConfluenceClient(
        base_url="https://loonar-osb.atlassian.net/wiki",
        space_key="osbjiraage",
        email="test@example.com",
        token="token",
        transport=transport,
    ) as client:
        pages = client.get_space_pages()
        assert len(pages) == 1
        page = pages[0]
        assert page.id == "1001"
        assert page.title == "FAQ de Vendas"
        assert page.version == 2
        assert "desconto progressivo a partir de 20 licenças" in page.text
        assert "https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/1001/faq" in page.url


def test_confluence_client_search_space_direct_fallback():
    mock_search_response = {
        "results": [
            {
                "id": "2002",
                "title": "SLA e Suporte",
                "body": {
                    "storage": {
                        "value": "<p>O suporte 24/7 está disponível apenas para contratos Enterprise.</p>"
                    }
                },
                "_links": {"webui": "/spaces/osbjiraage/pages/2002/sla"},
            }
        ]
    }

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=mock_search_response, request=request)
    )

    with ConfluenceClient(
        base_url="https://loonar-osb.atlassian.net/wiki",
        space_key="osbjiraage",
        email="test@example.com",
        token="token",
        transport=transport,
    ) as client:
        matches = client.search_space_direct("suporte 24/7")
        assert len(matches) == 1
        assert matches[0].title == "SLA e Suporte"
        assert "suporte 24/7" in matches[0].content
        assert matches[0].score > 0.5


def test_is_same_domain_validation():
    from src.kb.confluence_client import is_same_domain

    base = "https://loonar-osb.atlassian.net/wiki"

    # Mesmo domínio (relativo e absoluto)
    assert is_same_domain("/wiki/spaces/osbjiraage/pages/100", base) is True
    assert is_same_domain("/spaces/osbjiraage/pages/100", base) is True
    assert (
        is_same_domain("https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/100", base)
        is True
    )
    assert is_same_domain("https://LOONAR-OSB.ATLASSIAN.NET/other", base) is True

    # Domínio diferente (externo)
    assert is_same_domain("https://external-vendor.com/docs", base) is False
    assert is_same_domain("https://other-company.atlassian.net/wiki", base) is False
    assert is_same_domain("https://google.com", base) is False

    # Links perigosos ou esquemas inválidos
    assert is_same_domain("javascript:alert(1)", base) is False
    assert is_same_domain("mailto:support@loonar.com", base) is False
    assert is_same_domain("", base) is False


def test_clean_confluence_html_extracts_links():
    from src.kb.confluence_client import clean_confluence_html_with_links

    base = "https://loonar-osb.atlassian.net/wiki"
    html_sample = """
    <p>Dúvidas sobre o produto? Acesse nosso <a href="https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/3001/faq">FAQ Interno</a>.</p>
    <p>Consulte também o <a href="/spaces/osbjiraage/pages/3002/guia">Guia Relativo</a> para instruções.</p>
    <p>Para o site do fabricante, acesse <a href="https://fabricante-externo.com/ajuda">Suporte Externo</a>.</p>
    """

    text, links = clean_confluence_html_with_links(html_sample, base_url=base)

    # Links com URLs preservadas no texto para consulta
    assert (
        "FAQ Interno (https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/3001/faq)"
        in text
    )
    assert (
        "Guia Relativo (https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/3002/guia)"
        in text
    )
    assert "Suporte Externo (https://fabricante-externo.com/ajuda)" in text

    # Todos os links de suporte referenciados na KB são extraídos
    assert len(links) == 3
    assert (
        links[0]["url"] == "https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/3001/faq"
    )
    assert (
        links[1]["url"] == "https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/3002/guia"
    )
    assert links[2]["url"] == "https://fabricante-externo.com/ajuda"


def test_web_doc_cleaner_strictly_enforces_same_domain():
    from src.kb.confluence_client import WebDocCleaner

    doc_html = """
    <html>
        <head><title>Documentação do Fabricante</title></head>
        <body>
            <header><a href="https://fabricante-externo.com/ignorado-header">Header</a></header>
            <h1>Guia de Licenciamento</h1>
            <p>A licença permite mobilidade de usuários.</p>
            <p>Veja mais em <a href="https://fabricante-externo.com/faq-licenca">FAQ Licenças</a></p>
            <p>Consulte o <a href="/relativo/detalhes">Detalhes</a></p>
            <p>Siga-nos no <a href="https://twitter.com/empresa">Twitter</a> e no <a href="https://facebook.com/empresa">Facebook</a></p>
        </body>
    </html>
    """

    cleaner = WebDocCleaner(allowed_domain="fabricante-externo.com")
    cleaner.feed(doc_html)

    text = cleaner.get_text()
    assert "Guia de Licenciamento" in text
    assert "A licença permite mobilidade de usuários." in text

    # Apenas links do mesmo domínio do produto (ou relativos) são mantidos
    allowed_urls = [lk["url"] for lk in cleaner.same_domain_links]
    assert "https://fabricante-externo.com/faq-licenca" in allowed_urls
    assert "https://fabricante-externo.com/relativo/detalhes" in allowed_urls
    # Links para outros domínios são estritamente excluídos
    assert "https://twitter.com/empresa" not in allowed_urls
    assert "https://facebook.com/empresa" not in allowed_urls


def test_confluence_client_read_link_internal_and_product_doc():
    base = "https://loonar-osb.atlassian.net/wiki"

    def confluence_handler(request: httpx.Request) -> httpx.Response:
        if "/pages/4001" in request.url.path or "/rest/api/content/4001" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "id": "4001",
                    "title": "Documentação Confluence Interna",
                    "version": {"number": 1},
                    "body": {
                        "storage": {
                            "value": "<p>SLA do produto é de 2 horas para criticidade alta.</p>"
                        }
                    },
                    "_links": {"webui": "/spaces/osbjiraage/pages/4001"},
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    with ConfluenceClient(
        base_url=base,
        space_key="osbjiraage",
        email="test@example.com",
        token="token",
        transport=httpx.MockTransport(confluence_handler),
    ) as client:
        # Link interno do Confluence lido com sucesso
        res = client.read_link("https://loonar-osb.atlassian.net/wiki/spaces/osbjiraage/pages/4001")
        assert res["success"] is True
        assert res["same_domain"] is True
        assert res["title"] == "Documentação Confluence Interna"
        assert "SLA do produto é de 2 horas" in res["content"]

        # Esquema inválido é rejeitado
        res_invalid = client.read_link("ftp://ftp.example.com/file")
        assert res_invalid["success"] is False
        assert res_invalid["same_domain"] is False
