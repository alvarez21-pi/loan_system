"""Phase 2 item 8: security headers on every API response."""


def test_api_responses_carry_the_security_headers(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "Permissions-Policy" in response.headers
    # Not sent over plain HTTP — the test client's requests are never HTTPS.
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_is_added_when_the_request_is_marked_https(client):
    response = client.get("/api/health", headers={"X-Forwarded-Proto": "https"})
    assert response.status_code == 200
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_security_headers_present_even_on_an_error_response(client):
    # No auth header -> 401, but the headers must still be set regardless
    # of the response's status code.
    response = client.get("/api/borrowers/999999")
    assert response.status_code == 401
    assert response.headers["X-Frame-Options"] == "DENY"
