"""The tab icon is served at ``/favicon.ico`` for the pages that declare no ``<link rel="icon">``."""


def test_favicon_is_served_at_the_root(client):
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.mimetype in ("image/x-icon", "image/vnd.microsoft.icon")
    assert response.data[:4] == b"\x00\x00\x01\x00"  # ICO header
