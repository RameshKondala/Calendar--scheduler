"""Tests for the Week 6 frontend routes.

These only verify that Flask serves the customer and owner pages (and the
static assets they depend on) correctly -- they do not re-test business
logic, which stays covered by the existing API-level tests. There is no
separate JS test runner here; introducing one would add tooling the
project doesn't otherwise need (see the Week 6 constraint against
unnecessary frameworks). The pages themselves only call the same
`/api/v1/...` endpoints already covered elsewhere.
"""


def test_customer_page_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    body = resp.get_data(as_text=True)
    assert "Windsor Tuxedo" in body
    assert "api.js" in body
    assert "customer.js" in body


def test_owner_page_renders(client):
    resp = client.get("/owner")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    body = resp.get_data(as_text=True)
    assert "Staff Portal" in body
    assert "owner.js" in body
    assert '/auth/microsoft/login' in body  # real sign-in, not just a token box


def test_customer_page_links_to_owner_page(client):
    body = client.get("/").get_data(as_text=True)
    assert "/owner" in body


def test_owner_page_links_back_to_customer_page(client):
    body = client.get("/owner").get_data(as_text=True)
    assert 'href="/"' in body


def test_static_css_is_served(client):
    resp = client.get("/static/css/styles.css")
    assert resp.status_code == 200
    assert "text/css" in resp.content_type


def test_static_js_files_are_served(client):
    for filename in ("js/api.js", "js/customer.js", "js/owner.js"):
        resp = client.get(f"/static/{filename}")
        assert resp.status_code == 200, f"{filename} should be served"


def test_frontend_routes_do_not_affect_api_error_contract(client):
    """The catch-all 404 handler must still return the standard JSON error
    contract for unknown /api/v1 paths, unaffected by adding page routes."""
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "NOT_FOUND"
