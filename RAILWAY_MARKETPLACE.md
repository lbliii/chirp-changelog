# Deploy and Host a Changelog with Chirp

Launch a polished public changelog and release-notes archive powered by Chirp and PostgreSQL. Publish safe Markdown updates, keep drafts private, organize releases with tags, and give visitors searchable HTML, stable permalinks, and a standards-based Atom feed.

## About Hosting

The template provisions one Chirp web service and one Railway-managed PostgreSQL service. Railway generates the application signing key and owner token, supplies the database URL and public domain, runs database migrations before each release is promoted, and checks `/ready` before routing traffic to the deployment.

The application uses server-rendered HTML with HTMX enhancements, so every owner workflow also works without JavaScript. PostgreSQL owns all durable release data. Redis is not required because Chirp uses signed cookie sessions and the starter does not depend on a shared cache, job queue, or cross-worker realtime fan-out.

## Why Deploy

- Give a product a useful release-notes home in one click.
- Publish sanitized Markdown without adding a CMS or account system.
- Offer both a polished human archive and a machine-readable Atom feed.
- Get generated secrets, migrations, and readiness checks without manual wiring.
- Own the application code and PostgreSQL data after deployment.

## Common Use Cases

- Product and SaaS release notes
- Open-source project changelogs
- Internal platform announcements
- API and developer-tool updates
- A production-shaped Chirp learning project

## Dependencies for Chirp Changelog

### Deployment Dependencies

- A Chirp web service built from `lbliii/chirp-changelog`
- Railway PostgreSQL with persistent storage
- Python 3.14 and the locked application dependencies

No Redis service or external SaaS account is required. After deployment, open the generated public domain to view the changelog. Retrieve `CHIRP_ADMIN_TOKEN` from the web service variables when you need owner access.

Framework documentation: https://lbliii.github.io/chirp/

Starter source and support: https://github.com/lbliii/chirp-changelog
