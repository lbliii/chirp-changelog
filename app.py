"""Chirp Changelog: polished release notes for Railway."""

from __future__ import annotations

import hmac
import os
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4
from xml.etree.ElementTree import Element, SubElement, tostring

from chirp import OOB, App, AppConfig, Fragment, MutationResult, Page, Request, Response
from chirp.data import PageResult
from chirp.markdown import MarkdownRenderer, register_markdown_filter
from chirp.middleware.sessions import get_session
from chirp.middleware.stack import secure_stack

ROOT = Path(__file__).parent
MIGRATIONS = ROOT / "migrations"
PER_PAGE = 5
MAX_TITLE = 100
MAX_SUMMARY = 240
MAX_BODY = 20_000
MAX_TAGS = 6
_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class ReleaseRow:
    id: str
    slug: str
    title: str
    summary: str
    body_markdown: str
    status: str
    release_date: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ReleaseNote:
    id: str
    slug: str
    title: str
    summary: str
    body_markdown: str
    status: str
    release_date: str
    created_at: str
    updated_at: str
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TagRow:
    tag: str


SEED_RELEASES = (
    (
        "seed-090",
        "0.9.0",
        "A faster path from idea to production",
        "Chirp 0.9 turns typed returns, forms, and deployment checks into one coherent "
        "workflow.\n\n## What changed\n\n- Typed mutation results now share one handler across "
        "HTML and HTMX.\n- Readiness checks fail loudly before traffic arrives.\n- The data "
        "layer gained portable migrations and pagination.\n\n"
        "[Read the Chirp docs](https://lbliii.github.io/chirp/).",
        "2026-07-10",
        ("framework", "production"),
    ),
    (
        "seed-082",
        "0.8.2",
        "Calmer forms, clearer failures",
        "Validation messages now stay beside the work while out-of-band regions remain in sync."
        "\n\n## Highlights\n\nForms can return the same typed mutation for a plain browser "
        "redirect or a focused HTMX update. Error states remain useful without JavaScript.",
        "2026-06-26",
        ("forms", "htmx"),
    ),
    (
        "seed-070",
        "0.7.0",
        "One template, every response shape",
        "Named blocks now serve full pages, fragments, and streaming surfaces without a second "
        "frontend.\n\n## The idea\n\nWrite one semantic document. Chirp selects the named block "
        "required by the request and preserves the full-page path as the baseline.",
        "2026-06-04",
        ("templates", "hypermedia"),
    ),
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _positive_int(raw: str | None, default: int = 1) -> int:
    try:
        return max(1, int(raw or default))
    except ValueError:
        return default


def _clean_tags(raw: str) -> tuple[str, ...]:
    tags: list[str] = []
    for item in raw.split(","):
        tag = _SLUG_RE.sub("-", item.strip().lower()).strip("-")[:30]
        if tag and tag not in tags:
            tags.append(tag)
    return tuple(tags[:MAX_TAGS])


def _slug(value: str) -> str:
    return _SLUG_RE.sub("-", value.strip().lower()).strip("-")[:80] or "release"


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def create_app(
    database_url: str | None = None,
    *,
    admin_token: str | None = None,
    secret_key: str | None = None,
    public_url: str | None = None,
) -> App:
    """Build an isolated application for production or tests."""

    config = AppConfig.from_env(
        template_dir=ROOT / "templates",
        worker_mode="async",
        workers=1,
        htmx=True,
    )
    if secret_key:
        config = replace(config, secret_key=secret_key)
    if not config.secret_key:
        config = replace(config, secret_key="changelog-local-signing-key")

    resolved_admin_token = admin_token or os.environ.get("CHANGELOG_ADMIN_TOKEN")
    if not resolved_admin_token:
        if config.env != "development":
            raise RuntimeError("CHANGELOG_ADMIN_TOKEN is required outside development")
        resolved_admin_token = "changelog-local-admin"

    resolved_database_url = database_url or os.environ.get(
        "DATABASE_URL", f"sqlite:///{ROOT / 'changelog.db'}"
    )
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    default_public_url = f"https://{railway_domain}" if railway_domain else "http://localhost:8000"
    resolved_public_url = (public_url or default_public_url).rstrip("/")
    application = App(config, db=resolved_database_url, migrations=str(MIGRATIONS))
    for middleware in secure_stack(application.config):
        application.add_middleware(middleware)
    markdown: MarkdownRenderer = register_markdown_filter(application, sanitize=True)

    @application.on_startup
    async def seed_changelog() -> None:
        count = int(await application.db.fetch_val("SELECT COUNT(*) FROM release_notes") or 0)
        if count:
            return
        now = _now()
        for release_id, title, summary, body, release_date, tags in SEED_RELEASES:
            await application.db.execute(
                "INSERT INTO release_notes "
                "(id, slug, title, summary, body_markdown, status, release_date, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'published', ?, ?, ?)",
                release_id,
                _slug(title),
                title,
                summary,
                body,
                release_date,
                now,
                now,
            )
            await application.db.execute_many(
                "INSERT INTO release_tags (release_id, tag) VALUES (?, ?)",
                [(release_id, tag) for tag in tags],
            )

    def is_admin() -> bool:
        return get_session().get("changelog_admin") is True

    async def with_tags(rows: list[ReleaseRow]) -> list[ReleaseNote]:
        notes: list[ReleaseNote] = []
        for row in rows:
            tags = await application.db.fetch(
                TagRow, "SELECT tag FROM release_tags WHERE release_id = ? ORDER BY tag", row.id
            )
            notes.append(
                ReleaseNote(
                    id=row.id,
                    slug=row.slug,
                    title=row.title,
                    summary=row.summary,
                    body_markdown=row.body_markdown,
                    status=row.status,
                    release_date=row.release_date,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    tags=tuple(tag.tag for tag in tags),
                )
            )
        return notes

    async def find_note(slug: str, *, include_drafts: bool = False) -> ReleaseNote | None:
        where = "slug = ?" if include_drafts else "slug = ? AND status = 'published'"
        row = await application.db.fetch_one(
            ReleaseRow,
            "SELECT id, slug, title, summary, body_markdown, status, release_date, "
            f"created_at, updated_at FROM release_notes WHERE {where}",
            slug,
        )
        if row is None:
            return None
        return (await with_tags([row]))[0]

    async def release_page(
        q: str, tag: str, page: int, *, include_drafts: bool
    ) -> PageResult[ReleaseNote]:
        clauses = [] if include_drafts else ["status = 'published'"]
        params: list[Any] = []
        clean_query = q.strip()[:100]
        clean_tag = _clean_tags(tag)[0] if _clean_tags(tag) else ""
        if clean_query:
            clauses.append("LOWER(title || ' ' || summary || ' ' || body_markdown) LIKE ?")
            params.append(f"%{clean_query.lower()}%")
        if clean_tag:
            clauses.append(
                "EXISTS (SELECT 1 FROM release_tags rt "
                "WHERE rt.release_id = release_notes.id AND rt.tag = ?)"
            )
            params.append(clean_tag)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        total = int(
            await application.db.fetch_val(f"SELECT COUNT(*) FROM release_notes{where}", *params)
            or 0
        )
        pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        selected_page = min(max(1, page), pages)
        rows = await application.db.fetch(
            ReleaseRow,
            "SELECT id, slug, title, summary, body_markdown, status, release_date, "
            f"created_at, updated_at FROM release_notes{where} "
            "ORDER BY release_date DESC, created_at DESC, id ASC LIMIT ? OFFSET ?",
            *params,
            PER_PAGE,
            (selected_page - 1) * PER_PAGE,
        )
        return PageResult(await with_tags(rows), selected_page, PER_PAGE, total)

    async def all_tags() -> list[str]:
        rows = await application.db.fetch(
            TagRow,
            "SELECT DISTINCT rt.tag FROM release_tags rt "
            "JOIN release_notes rn ON rn.id = rt.release_id "
            "WHERE rn.status = 'published' ORDER BY rt.tag",
        )
        return [value.tag for value in rows]

    async def context(
        *, q: str = "", tag: str = "", page: int = 1, notice: str = ""
    ) -> dict[str, Any]:
        return {
            "admin": is_admin(),
            "note": None,
            "notice": notice,
            "page": await release_page(q, tag, page, include_drafts=is_admin()),
            "q": q.strip()[:100],
            "selected_tag": _clean_tags(tag)[0] if _clean_tags(tag) else "",
            "tags": await all_tags(),
            "today": date.today().isoformat(),
        }

    async def result(notice: str) -> MutationResult:
        current = await context(notice=notice)
        return MutationResult(
            "/",
            Fragment("index.html", "timeline", **current),
            Fragment("index.html", "owner", target="owner", **current),
            Fragment("index.html", "notice", target="notice", **current),
            trigger="changelogChanged",
        )

    @application.route("/", name="home")
    async def index(request: Request) -> Page | OOB:
        current = await context(
            q=request.query.get("q", "") or "",
            tag=request.query.get("tag", "") or "",
            page=_positive_int(request.query.get("page")),
        )
        if request.is_narrow_fragment:
            return OOB(
                Fragment("index.html", "timeline", **current),
                Fragment("index.html", "filter_meta", target="filter-meta", **current),
            )
        return Page("index.html", "timeline", page_block_name="page_root", **current)

    @application.route("/notes/{slug}", name="notes.detail")
    async def detail(slug: str) -> Page | Response:
        note = await find_note(slug, include_drafts=is_admin())
        if note is None:
            return Response("Release note not found", status=404, content_type="text/plain")
        current = await context()
        current["note"] = note
        return Page(
            "index.html",
            "note_detail",
            page_block_name="page_root",
            **current,
        )

    @application.route("/feed.xml", name="feed")
    async def feed() -> Response:
        rows = await application.db.fetch(
            ReleaseRow,
            "SELECT id, slug, title, summary, body_markdown, status, release_date, "
            "created_at, updated_at FROM release_notes WHERE status = 'published' "
            "ORDER BY release_date DESC, created_at DESC, id ASC LIMIT 20",
        )
        notes = await with_tags(rows)
        atom = "http://www.w3.org/2005/Atom"
        root = Element("feed", {"xmlns": atom})
        SubElement(root, "title").text = "Chirp Changelog"
        SubElement(root, "id").text = f"{resolved_public_url}/"
        SubElement(root, "link", {"href": f"{resolved_public_url}/feed.xml", "rel": "self"})
        SubElement(root, "link", {"href": f"{resolved_public_url}/"})
        SubElement(root, "updated").text = (
            f"{notes[0].release_date}T12:00:00Z" if notes else "1970-01-01T00:00:00Z"
        )
        for note in notes:
            entry = SubElement(root, "entry")
            url = f"{resolved_public_url}/notes/{quote(note.slug)}"
            SubElement(entry, "title").text = note.title
            SubElement(entry, "id").text = url
            SubElement(entry, "link", {"href": url})
            SubElement(entry, "updated").text = f"{note.release_date}T12:00:00Z"
            SubElement(entry, "summary").text = note.summary
            SubElement(entry, "content", {"type": "html"}).text = str(
                markdown.render(note.body_markdown)
            )
            for tag in note.tags:
                SubElement(entry, "category", {"term": tag})
        payload = tostring(root, encoding="utf-8", xml_declaration=True)
        return Response(payload, content_type="application/atom+xml; charset=utf-8")

    @application.route("/admin/login", methods=["POST"], name="admin.login")
    async def admin_login(request: Request) -> MutationResult:
        form = await request.form()
        if hmac.compare_digest(str(form.get("token") or ""), resolved_admin_token):
            get_session()["changelog_admin"] = True
            return await result("Owner studio unlocked for this browser.")
        return await result("That owner token was not accepted.")

    @application.route("/admin/logout", methods=["POST"], name="admin.logout")
    async def admin_logout() -> MutationResult:
        get_session().pop("changelog_admin", None)
        return await result("Owner studio locked.")

    def validate(form: Any) -> tuple[dict[str, str], str | None]:
        fields = {
            "title": str(form.get("title") or "").strip(),
            "summary": str(form.get("summary") or "").strip(),
            "body": str(form.get("body") or "").strip(),
            "release_date": str(form.get("release_date") or "").strip(),
            "tags": str(form.get("tags") or "").strip(),
        }
        if len(fields["title"]) < 2:
            return fields, "Give the release a title of at least 2 characters."
        if len(fields["title"]) > MAX_TITLE:
            return fields, f"Keep the title under {MAX_TITLE} characters."
        if len(fields["summary"]) < 10:
            return fields, "Add a summary of at least 10 characters."
        if len(fields["summary"]) > MAX_SUMMARY:
            return fields, f"Keep the summary under {MAX_SUMMARY} characters."
        if len(fields["body"]) < 10:
            return fields, "Add at least 10 characters of Markdown release notes."
        if len(fields["body"]) > MAX_BODY:
            return fields, f"Keep the Markdown body under {MAX_BODY} characters."
        if not _valid_date(fields["release_date"]):
            return fields, "Choose a valid release date."
        return fields, None

    async def unique_slug(title: str) -> str:
        base = _slug(title)
        candidate = base
        counter = 2
        while await application.db.fetch_val(
            "SELECT 1 FROM release_notes WHERE slug = ?", candidate
        ):
            candidate = f"{base[:72]}-{counter}"
            counter += 1
        return candidate

    @application.route("/admin/notes", methods=["POST"], name="admin.notes.create")
    async def create_note(request: Request) -> MutationResult:
        if not is_admin():
            return await result("Unlock the owner studio before drafting a release.")
        form = await request.form()
        fields, error = validate(form)
        if error:
            return await result(error)
        release_id = uuid4().hex
        now = _now()
        status = "published" if str(form.get("action") or "") == "publish" else "draft"
        await application.db.execute(
            "INSERT INTO release_notes "
            "(id, slug, title, summary, body_markdown, status, release_date, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            release_id,
            await unique_slug(fields["title"]),
            fields["title"],
            fields["summary"],
            fields["body"],
            status,
            fields["release_date"],
            now,
            now,
        )
        tags = _clean_tags(fields["tags"])
        if tags:
            await application.db.execute_many(
                "INSERT INTO release_tags (release_id, tag) VALUES (?, ?)",
                [(release_id, tag) for tag in tags],
            )
        return await result("Release published." if status == "published" else "Draft saved.")

    @application.route("/admin/notes/{release_id}/edit", methods=["POST"], name="admin.notes.edit")
    async def edit_note(request: Request, release_id: str) -> MutationResult:
        if not is_admin():
            return await result("Unlock the owner studio before editing releases.")
        form = await request.form()
        fields, error = validate(form)
        if error:
            return await result(error)
        changed = await application.db.execute(
            "UPDATE release_notes SET title = ?, summary = ?, body_markdown = ?, "
            "release_date = ?, updated_at = ? WHERE id = ?",
            fields["title"],
            fields["summary"],
            fields["body"],
            fields["release_date"],
            _now(),
            release_id,
        )
        if not changed:
            return await result("That release is no longer in the changelog.")
        await application.db.execute("DELETE FROM release_tags WHERE release_id = ?", release_id)
        tags = _clean_tags(fields["tags"])
        if tags:
            await application.db.execute_many(
                "INSERT INTO release_tags (release_id, tag) VALUES (?, ?)",
                [(release_id, tag) for tag in tags],
            )
        return await result("Release updated; its permalink stayed the same.")

    @application.route(
        "/admin/notes/{release_id}/publish", methods=["POST"], name="admin.notes.publish"
    )
    async def publish_note(release_id: str) -> MutationResult:
        if not is_admin():
            return await result("Unlock the owner studio before publishing releases.")
        changed = await application.db.execute(
            "UPDATE release_notes SET status = 'published', updated_at = ? WHERE id = ?",
            _now(),
            release_id,
        )
        return await result(
            "Release published." if changed else "That release is no longer in the changelog."
        )

    @application.route(
        "/admin/notes/{release_id}/delete", methods=["POST"], name="admin.notes.delete"
    )
    async def delete_note(release_id: str) -> MutationResult:
        if not is_admin():
            return await result("Unlock the owner studio before deleting releases.")
        deleted = await application.db.execute("DELETE FROM release_notes WHERE id = ?", release_id)
        return await result(
            "Release deleted." if deleted else "That release is no longer in the changelog."
        )

    @application.route("/styles.css", referenced=True)
    def styles(request: Request) -> Response:
        return Response(
            (ROOT / "styles.css").read_text(encoding="utf-8"),
            content_type="text/css; charset=utf-8",
        )

    return application


app = create_app()


if __name__ == "__main__":
    app.run()
