"""robots.txt and sitemap.xml, which differ by hostname."""

from fastapi.testclient import TestClient

MARKETING = {"host": "askgrey.app"}
PRODUCT = {"host": "lab.askgrey.app"}


def test_the_marketing_host_invites_crawlers_and_points_at_its_sitemap(
    client: TestClient,
) -> None:
    body = client.get("/robots.txt", headers=MARKETING).text
    assert "Allow: /" in body
    assert "Disallow: /api/" in body
    assert "Sitemap: https://askgrey.app/sitemap.xml" in body


def test_the_product_host_is_closed_to_crawlers(client: TestClient) -> None:
    body = client.get("/robots.txt", headers=PRODUCT).text
    assert body.strip() == "User-agent: *\nDisallow: /"


def test_the_sitemap_lists_the_public_pages_only(client: TestClient) -> None:
    body = client.get("/sitemap.xml", headers=MARKETING).text
    assert "<loc>https://askgrey.app/</loc>" in body
    assert "<loc>https://askgrey.app/security</loc>" in body
    assert "<loc>https://askgrey.app/terms</loc>" in body
    # Nothing behind the sign-in screen: those paths answer a crawler with a redirect.
    for private in ("/chat", "/literature", "/screening", "/settings", "/login"):
        assert f"<loc>https://askgrey.app{private}</loc>" not in body


def test_the_sitemap_is_xml(client: TestClient) -> None:
    response = client.get("/sitemap.xml", headers=MARKETING)
    assert response.headers["content-type"].startswith("application/xml")
    assert response.text.startswith('<?xml version="1.0"')
