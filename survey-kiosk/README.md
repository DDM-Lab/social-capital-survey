# Survey Kiosk

A kiosk-based survey app. An always-on screen shows a QR code that rotates every
few seconds; each scan mints a unique, time-boxed survey session. Participants pick
a short (5 Q) or long (15 Q) survey, give IRB consent, answer, then claim a prize by
entering their CMU username — a magic-link email verifies the mailbox and reveals a
one-time redemption code from an admin-loaded pool. Results are in the Django admin
with CSV export.

Stack: Django 5.1 · HTMX · PostgreSQL · Postmark (django-anymail) · uv.

## Architecture docs

Detailed design docs live in [`docs/`](docs/README.md): the
[tech stack](docs/01-tech-stack.md), [data model](docs/02-data-model.md),
[controllers & request flows](docs/03-controllers-and-flows.md),
[templates & frontend](docs/04-templates-and-frontend.md), and
[admin & operations](docs/05-admin-and-operations.md). Start there to understand
or modify the codebase.

## Local development

```bash
uv sync                                  # install deps into .venv
cp .env.example .env                     # then edit values
uv run python manage.py migrate
uv run python manage.py seed_demo        # placeholder survey, kiosk, prize codes
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

- Visit `/` — it redirects to the active kiosk (if exactly one) or to `/admin/`.
- Kiosk screen: `/kiosk/<kiosk_id>/`  (id printed by `seed_demo`)
- Admin / dashboard / CSV / code upload: `/admin/`
- Without `DATABASE_URL` the app uses a local SQLite file. Set `DATABASE_URL`
  (`postgres://user:pass@host:5432/db`) to use Postgres.
- Without `POSTMARK_SERVER_TOKEN` emails print to the console.

## Tests

```bash
uv run python manage.py test
```

## Configuration

All settings come from the environment (see `.env.example`): `SECRET_KEY`, `DEBUG`,
`ALLOWED_HOSTS`, `BASE_URL`, `DATABASE_URL`, `TARGET_DOMAIN`, `QR_ROTATE_SECONDS`,
`TOKEN_TTL_SECONDS`, `SURVEY_TTL_MINUTES`, `VERIFY_TTL_HOURS`, `POSTMARK_SERVER_TOKEN`,
`DEFAULT_FROM_EMAIL`.

## Operations

```bash
# Run every minute from cron: flip lapsed active sessions to expired.
uv run python manage.py expire_sessions

# Retention is INDEFINITE by default (unscheduled). To enforce a window later:
uv run python manage.py purge_data --days 90 --yes
uv run python manage.py purge_data --days 30 --emails-only --yes
```

## Deploy (host-agnostic)

`Procfile` runs `gunicorn config.wsgi` and `migrate` on release. Before serving:

```bash
DEBUG=false uv run python manage.py collectstatic --noinput   # WhiteNoise serves /static
```

Set `DEBUG=false`, a strong `SECRET_KEY`, real `ALLOWED_HOSTS`/`BASE_URL` (https),
a managed `DATABASE_URL`, and Postmark credentials. With `DEBUG=false` the app
forces HTTPS redirect, secure cookies, and HSTS.

### Before launch (content owners)

1. Paste the IRB-approved consent wording into the Survey's *consent text* in admin.
2. Upload real prize codes via **Admin → Prize codes → Upload codes**.
3. Replace placeholder questions and upload grid images in admin.
4. Add Postmark server token + verified sending domain.

> Note: rate limiting keys on client IP. Behind a proxy/load balancer, configure the
> deployment to pass the real client IP (e.g. set up `X-Forwarded-For` handling).
