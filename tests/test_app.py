from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlencode
from xml.etree import ElementTree

import pytest
from chirp.data import DataError, MigrationError, QueryError
from chirp.testing import TestClient

import app as changelog_app
from app import create_app

pytestmark = pytest.mark.issue(810)
_CSRF_RE = re.compile(r'name="_csrf_token" value="([^"]+)"')


def _cookie(response) -> str:
    value = response.header("set-cookie", "")
    assert value.startswith("chirp_session=")
    return value.split(";", 1)[0]


async def _page_context(client: TestClient, path: str = "/") -> tuple[str, str]:
    response = await client.get(path)
    match = _CSRF_RE.search(response.text)
    assert match is not None
    return match.group(1), _cookie(response)


async def _login(client: TestClient) -> tuple[str, str]:
    token, cookie = await _page_context(client)
    login = await client.post(
        "/admin/login",
        body=urlencode({"token": "test-owner-token", "_csrf_token": token}).encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": cookie,
            "HX-Request": "true",
            "HX-Target": "timeline",
        },
    )
    assert "Owner studio unlocked" in login.text
    owner_cookie = login.header("set-cookie", "").split(";", 1)[0] or cookie
    page = await client.get("/", headers={"Cookie": owner_cookie})
    token_match = _CSRF_RE.search(page.text)
    assert token_match is not None
    return token_match.group(1), owner_cookie


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        admin_token="test-owner-token",
        secret_key="test-signing-key-with-enough-entropy",
        public_url="https://changelog.example",
    )


def _release_body(token: str, **changes: str) -> bytes:
    values = {
        "title": "1.0.0",
        "summary": "A durable release note for every visitor.",
        "body": "## Highlights\n\n- Safer publishing\n- Faster pages",
        "release_date": "2026-07-14",
        "tags": "launch, Platform",
        "action": "draft",
        "_csrf_token": token,
    }
    values.update(changes)
    return urlencode(values).encode()


def _form_headers(cookie: str, *, htmx: bool = True) -> dict[str, str]:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": cookie,
    }
    if htmx:
        headers.update({"HX-Request": "true", "HX-Target": "timeline"})
    return headers


async def test_full_page_health_readiness_asset_detail_and_docs_link(tmp_path: Path) -> None:
    application = _application(tmp_path / "changelog.db")
    async with TestClient(application) as client:
        page = await client.get("/")
        detail = await client.get("/notes/0-9-0")
        health = await client.get("/health")
        ready = await client.get("/ready")
        css = await client.get("/styles.css")
        favicon = await client.get("/favicon.svg")

    assert page.status == detail.status == health.status == ready.status == css.status == 200
    assert favicon.status == 200
    assert favicon.content_type == "image/svg+xml"
    assert '<link rel="icon" href="/favicon.svg" type="image/svg+xml">' in page.text
    assert '<link rel="icon" href="/favicon.svg" type="image/svg+xml">' in detail.text
    assert '<meta name="htmx-config" content=\'{"includeIndicatorStyles": false}\'>' in page.text
    assert "htmx.org@2.0.8" not in page.text
    assert page.text.count('data-chirp="htmx"') == 1
    csp = page.header("content-security-policy", "")
    nonce_match = re.search(r"'nonce-([^']+)'", csp)
    assert nonce_match is not None
    assert f'nonce="{nonce_match.group(1)}"' in page.text
    assert "Follow what" in page.text
    assert "A faster path from idea to production" in page.text
    assert 'href="https://lbliii.github.io/chirp/"' in page.text
    assert "Typed mutation results" in detail.text
    assert "--coral:" in css.text
    assert "Release archive" in page.text


async def test_search_tag_filter_and_empty_state_support_htmx(tmp_path: Path) -> None:
    application = _application(tmp_path / "search.db")
    async with TestClient(application) as client:
        search = await client.get(
            "/?q=readiness", headers={"HX-Request": "true", "HX-Target": "timeline"}
        )
        tagged = await client.get(
            "/?tag=forms", headers={"HX-Request": "true", "HX-Target": "timeline"}
        )
        empty = await client.get(
            "/?q=does-not-exist",
            headers={"HX-Request": "true", "HX-Target": "timeline"},
        )

    assert "A faster path from idea to production" in search.text
    assert "Calmer forms, clearer failures" in tagged.text
    assert "One template, every response shape" not in tagged.text
    assert "No releases found" in empty.text
    assert "hx-swap-oob" in search.text
    for response in (search, tagged, empty):
        assert "<!doctype html>" not in response.text.lower()
        assert 'class="site-header' not in response.text
        assert 'class="hero' not in response.text
        assert 'id="timeline"' not in response.text


async def test_owner_draft_is_private_then_publish_makes_it_public(tmp_path: Path) -> None:
    application = _application(tmp_path / "drafts.db")
    async with TestClient(application) as client:
        token, owner_cookie = await _login(client)
        draft = await client.post(
            "/admin/notes",
            body=_release_body(token),
            headers=_form_headers(owner_cookie),
        )
        release_id = await application.db.fetch_val(
            "SELECT id FROM release_notes WHERE title = ?", "1.0.0"
        )
        owner_page = await client.get("/", headers={"Cookie": owner_cookie})
        visitor_page = await client.get("/")
        visitor_detail = await client.get("/notes/1-0-0")
        owner_token = _CSRF_RE.search(owner_page.text)
        assert owner_token is not None
        published = await client.post(
            f"/admin/notes/{release_id}/publish",
            body=urlencode({"_csrf_token": owner_token.group(1)}).encode(),
            headers=_form_headers(owner_cookie),
        )
        public_after = await client.get("/")

    assert "Draft saved" in draft.text
    assert "1.0.0" in owner_page.text
    assert "draft-tag" in owner_page.text
    assert "1.0.0" not in visitor_page.text
    assert visitor_detail.status == 404
    assert "Release published" in published.text
    assert "1.0.0" in public_after.text


async def test_publish_directly_supports_plain_html_redirect(tmp_path: Path) -> None:
    application = _application(tmp_path / "plain.db")
    async with TestClient(application) as client:
        token, owner_cookie = await _login(client)
        response = await client.post(
            "/admin/notes",
            body=_release_body(token, title="1.1.0", action="publish"),
            headers=_form_headers(owner_cookie, htmx=False),
        )
        page = await client.get("/")

    assert response.status == 303
    assert response.header("location") == "/"
    assert "1.1.0" in page.text


async def test_malformed_edit_keeps_permalink_and_delete_removes_note(tmp_path: Path) -> None:
    application = _application(tmp_path / "edit.db")
    async with TestClient(application) as client:
        token, owner_cookie = await _login(client)
        malformed = await client.post(
            "/admin/notes",
            body=_release_body(token, summary="short"),
            headers=_form_headers(owner_cookie),
        )
        created = await client.post(
            "/admin/notes",
            body=_release_body(token, action="publish"),
            headers=_form_headers(owner_cookie),
        )
        assert "Release published" in created.text
        release_id = await application.db.fetch_val(
            "SELECT id FROM release_notes WHERE title = ?", "1.0.0"
        )
        owner_page = await client.get("/", headers={"Cookie": owner_cookie})
        owner_token = _CSRF_RE.search(owner_page.text)
        assert owner_token is not None
        edited = await client.post(
            f"/admin/notes/{release_id}/edit",
            body=_release_body(
                owner_token.group(1),
                title="A new display title",
                summary="The title changed while the original permalink remained durable.",
            ),
            headers=_form_headers(owner_cookie),
        )
        old_permalink = await client.get("/notes/1-0-0")
        owner_page = await client.get("/", headers={"Cookie": owner_cookie})
        owner_token = _CSRF_RE.search(owner_page.text)
        assert owner_token is not None
        deleted = await client.post(
            f"/admin/notes/{release_id}/delete",
            body=urlencode({"_csrf_token": owner_token.group(1)}).encode(),
            headers=_form_headers(owner_cookie),
        )
        gone = await client.get("/notes/1-0-0")

    assert "summary of at least 10" in malformed.text
    assert "permalink stayed the same" in edited.text
    assert old_permalink.status == 200
    assert "A new display title" in old_permalink.text
    assert "Release deleted" in deleted.text
    assert gone.status == 404


async def test_markdown_is_sanitized_and_atom_feed_is_valid(tmp_path: Path) -> None:
    application = _application(tmp_path / "feed.db")
    async with TestClient(application) as client:
        token, owner_cookie = await _login(client)
        await client.post(
            "/admin/notes",
            body=_release_body(
                token,
                title="Security release",
                body="## Safe body\n\n<script>alert('no')</script>\n\n[bad](javascript:alert(1))",
                action="publish",
            ),
            headers=_form_headers(owner_cookie),
        )
        detail = await client.get("/notes/security-release")
        feed = await client.get("/feed.xml")

    assert "<h2" in detail.text and "Safe body</h2>" in detail.text
    assert "<script>" not in detail.text
    assert "javascript:" not in detail.text
    assert feed.status == 200
    assert feed.content_type.startswith("application/atom+xml")
    root = ElementTree.fromstring(feed.body)
    assert root.tag == "{http://www.w3.org/2005/Atom}feed"
    links = root.findall("{http://www.w3.org/2005/Atom}entry")
    assert any(
        entry.findtext("{http://www.w3.org/2005/Atom}title") == "Security release"
        for entry in links
    )
    assert b"javascript:" not in feed.body


async def test_atom_feed_uses_railway_public_domain_automatically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "changelog-production.up.railway.app")
    application = create_app(
        f"sqlite:///{tmp_path / 'railway-domain.db'}",
        admin_token="test-owner-token",
        secret_key="test-signing-key-with-enough-entropy",
    )
    async with TestClient(application) as client:
        feed = await client.get(
            "/feed.xml", headers={"Host": "changelog-production.up.railway.app"}
        )

    assert "https://changelog-production.up.railway.app/notes/0-9-0" in feed.text


async def test_restart_preserves_release_and_ordering(tmp_path: Path) -> None:
    database = tmp_path / "persistent.db"
    first = _application(database)
    async with TestClient(first) as client:
        token, owner_cookie = await _login(client)
        await client.post(
            "/admin/notes",
            body=_release_body(token, title="2.0.0", release_date="2027-01-03", action="publish"),
            headers=_form_headers(owner_cookie),
        )

    second = _application(database)
    async with TestClient(second) as client:
        page = await client.get("/")
        detail = await client.get("/notes/2-0-0")

    assert "2.0.0" in detail.text
    assert page.text.index("2.0.0") < page.text.index("0.9.0")


async def test_database_unavailable_at_startup_is_actionable() -> None:
    application = create_app(
        "postgresql://postgres:postgres@127.0.0.1:1/railway",
        admin_token="test-owner-token",
        secret_key="test-signing-key-with-enough-entropy",
    )
    with pytest.raises(DataError, match=r"could not connect to 127\.0\.0\.1:1"):
        async with TestClient(application):
            pass


async def test_migration_failure_names_the_broken_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_broken.sql").write_text("CREATE TABL broken (", encoding="utf-8")
    monkeypatch.setattr(changelog_app, "MIGRATIONS", migrations)
    application = _application(tmp_path / "broken.db")
    with pytest.raises(MigrationError, match="Migration 001_broken failed"):
        async with TestClient(application):
            pass


async def test_schema_mismatch_fails_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_wrong.sql").write_text(
        "CREATE TABLE release_notes (id TEXT PRIMARY KEY);",
        encoding="utf-8",
    )
    monkeypatch.setattr(changelog_app, "MIGRATIONS", migrations)
    application = _application(tmp_path / "wrong.db")
    with pytest.raises(QueryError, match="no column named slug"):
        async with TestClient(application):
            pass


def test_app_contracts_pass(tmp_path: Path) -> None:
    application = _application(tmp_path / "contracts.db")
    assert application.config.workers == 1
    application.freeze()
    assert any(check.name == "database" for check in application._mutable_state.health_checks)
    application.check()
