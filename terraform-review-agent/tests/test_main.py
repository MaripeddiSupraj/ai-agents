import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app, _verify_github_signature
import app.main as _main_module


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestWebhookSignature:
    def _sign(self, body: bytes, secret: str) -> str:
        return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def test_valid_signature_accepted(self):
        secret = "my-webhook-secret"
        body = b'{"action": "opened"}'
        sig = self._sign(body, secret)
        assert _verify_github_signature(body, sig, secret) is True

    def test_wrong_signature_rejected(self):
        body = b'{"action": "opened"}'
        assert _verify_github_signature(body, "sha256=deadbeef", "real-secret") is False

    def test_missing_signature_rejected_when_secret_set(self):
        body = b'{"action": "opened"}'
        assert _verify_github_signature(body, "", "real-secret") is False

    def test_no_secret_bypasses_check(self):
        body = b'{"action": "opened"}'
        assert _verify_github_signature(body, "", "") is True

    def test_missing_sha256_prefix_rejected(self):
        body = b'{"action": "opened"}'
        assert _verify_github_signature(body, "deadbeef", "real-secret") is False

    def test_webhook_returns_401_on_bad_signature(self, client):
        body = json.dumps({"action": "opened"}).encode()
        mock_settings = MagicMock()
        mock_settings.github_webhook_secret = "real-secret"
        with patch.object(_main_module, "settings", mock_settings):
            response = client.post(
                "/webhook/github",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": "sha256=badsignature",
                },
            )
        assert response.status_code == 401

    def test_webhook_skips_non_tf_payload(self, client):
        payload = {
            "action": "opened",
            "pull_request": {"number": 1, "title": "test", "body": "", "files": []},
            "repository": {"full_name": "org/repo"},
        }
        body = json.dumps(payload).encode()
        response = client.post(
            "/webhook/github",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "skipped"


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "redis_connected" in data
