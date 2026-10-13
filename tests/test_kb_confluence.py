"""Tests for Confluence REST API client, HTML cleaner, and direct CQL search."""

import httpx
import pytest

from src.kb.confluence_client import ConfluenceClient, clean_confluence_html


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
