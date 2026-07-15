# Changelog

All notable changes to Chirp Changelog are documented here.

## 0.1.3 - 2026-07-14

- Refine the release timeline into a compact editorial archive with clearer
  hierarchy, responsive cards, stronger focus states, and narrow-screen support.
- Add the Chirp Changelog timeline favicon and verify it on full pages and as a
  standalone SVG asset.
- Refresh the Railway marketplace image to match the shipped interface.

## 0.1.2 - 2026-07-14

- Add the verified 1440×1000 live-deployment screenshot used by the Railway
  marketplace listing.

## 0.1.1 - 2026-07-14

- Derive absolute Atom links from Railway's built-in public domain automatically.
- Namespace the owner token as `CHANGELOG_ADMIN_TOKEN` so Chirp's strict
  configuration diagnostics stay clean in production.

## 0.1.0 - 2026-07-14

- Ship the searchable, tag-filtered public release timeline and stable permalinks.
- Add owner-token authentication with draft, publish, edit, and delete workflows.
- Render sanitized Markdown through Chirp's optional Markdown integration.
- Publish a standards-based Atom feed containing public releases only.
- Add PostgreSQL migrations, seed content, readiness checks, and Railway configuration.
- Cover HTML, HTMX, privacy, lifecycle, persistence, and failure contracts in tests.
