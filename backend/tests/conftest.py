import os
import secrets
import sys
import tempfile
import time
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="ams_test_")
os.environ.update({"DATABASE_URL": f"sqlite:///{_tmp}/test.db", "AMS_TEST_MODE": "1", "APP_ENV": "test",
                   "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "T3st-" + secrets.token_urlsafe(16),
                   "SECRET_KEY": secrets.token_hex(16)})
for k in ("LLM_API_KEY", "COMPANIES_HOUSE_API_KEY", "AMS_SSRF_ALLOW_CIDRS"):
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import security  # noqa: E402
from app.main import app  # noqa: E402

ADMIN_PW = os.environ["ADMIN_PASSWORD"]
ALL_PROVIDERS_DOWN = {p: "simulated outage" for p in ("google_news", "gdelt", "bing_news", "govuk", "doj", "sec_litigation",
                                                      "companies_house", "courtlistener", "newsapi", "gnews", "brave", "serper",
                                                      "bing_web")}


@pytest.fixture(scope="session")
def client():
    with TestClient(app, base_url="http://testserver") as c:
        yield c


@pytest.fixture(autouse=True)
def _no_login_limit(monkeypatch, request):
    if "real_limiter" not in request.keywords:
        monkeypatch.setattr(security.login_limiter, "allow", lambda k: True)


class Session_:
    def __init__(self, client, csrf):
        self.c, self.csrf = client, csrf

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers={"X-CSRF-Token": self.csrf, **kw.pop("headers", {})}, **kw)

    def put(self, url, json=None):
        return self.c.put(url, json=json, headers={"X-CSRF-Token": self.csrf})

    def patch(self, url, json=None):
        return self.c.patch(url, json=json, headers={"X-CSRF-Token": self.csrf})

    def delete(self, url):
        return self.c.delete(url, headers={"X-CSRF-Token": self.csrf})


def login(client, username, password):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return Session_(client, r.json()["csrf"])


@pytest.fixture
def admin(client):
    return login(client, "admin", ADMIN_PW)


def wait_done(s: Session_, sid: str, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        p = s.get(f"/api/screenings/{sid}/progress").json()
        if p.get("job_status") in ("done", "failed", "completed"):
            break
        time.sleep(0.3)
    return s.get(f"/api/screenings/{sid}").json()
