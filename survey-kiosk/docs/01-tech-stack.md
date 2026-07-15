# 01 · Tech Stack

This document lists every framework and library, why it's here, and how
configuration flows into the running app.

## Runtime & language

- **Python ≥ 3.13** (`pyproject.toml:4`). No special language features beyond
  standard library; nothing should block running on 3.11/3.12 if needed.
- **uv** for environment + dependency management (not pip). The lockfile
  `uv.lock` pins exact versions; `uv sync` reproduces the environment.
  Everything runs via `uv run …` so you never have to activate a virtualenv.

## Dependencies (`pyproject.toml`)

| Package | Role | Where it shows up |
|---------|------|-------------------|
| **Django 5.1** | Web framework: ORM, admin, templating, auth, migrations. Chosen primarily for the **free admin dashboard** and ORM. | everywhere |
| **psycopg[binary] 3** | PostgreSQL driver for production. | `config/settings.py` database block |
| **django-anymail[postmark]** | Transactional email through Postmark. | `config/settings.py` email block, `survey/emails.py` |
| **qrcode[pil]** | Server-side QR PNG generation (Pillow comes along for image work). | `survey/views.py` `_qr_data_uri`, `seed_demo` grid image |
| **django-htmx** | Small helper middleware for HTMX requests. | middleware; the kiosk QR poll |
| **django-ratelimit** | IP-based rate limiting on abuse-prone endpoints. | `@ratelimit` decorators in `survey/views.py` |
| **whitenoise** | Serves static files from the app process (no separate static host). | middleware + `STORAGES` |
| **gunicorn** | Production WSGI server. | `Procfile` |

There is **no** front-end build toolchain (no Node, no bundler). HTMX is loaded
from a CDN in the base template, and the only custom JS is a small vanilla file
(`survey/static/survey/grid.js`).

## Why Django over a lighter framework

The app needs an admin UI for staff to manage questions, review responses,
upload prize codes, and export CSV. Django's admin delivers all of that for
free, and the ORM models map cleanly onto the survey/claim/prize domain. A
thinner framework (FastAPI/Flask) would have meant building the admin by hand.

## Data stores

- **PostgreSQL in production**, selected via the `DATABASE_URL` environment
  variable and parsed in `config/settings.py:101` (`_parse_database_url`).
- **SQLite fallback** when `DATABASE_URL` is unset (`config/settings.py:116`) —
  this is what local dev and the test suite use. The file is `db.sqlite3` in the
  project root and is gitignored.
  > Note: one production behavior relies on Postgres — `select_for_update(skip_locked=True)`
  > during prize assignment (doc 03). SQLite ignores row locking, which is fine
  > for single-process dev but is why concurrency correctness should be checked
  > against Postgres.

## Email

- Configured in `config/settings.py:164`. If `POSTMARK_SERVER_TOKEN` is set, the
  Anymail Postmark backend is used; otherwise the **console backend** prints
  emails to the server log (handy in dev — you can copy the magic link from the
  terminal).
- The only email sent is the verification/magic-link message (`survey/emails.py`).

## Static & media files

- `STATIC_URL`/`STATIC_ROOT` and `MEDIA_URL`/`MEDIA_ROOT` are set in
  `config/settings.py:142`.
- **Static** (CSS/JS): served by WhiteNoise. The storage backend is gated on
  `DEBUG` (`config/settings.py:149`): plain `StaticFilesStorage` in dev/tests,
  `CompressedManifestStaticFilesStorage` in production (requires
  `collectstatic`). This split exists because the manifest backend errors if a
  referenced file hasn't been collected — which broke the test run early on.
- **Media** (admin-uploaded grid images): stored on the local filesystem under
  `media/`. In `DEBUG` they're served by Django (`config/urls.py`); in production
  you'd point a volume or object store at `MEDIA_ROOT`.

## Configuration: how settings reach the app

All deployment-specific values are **read from the environment**, optionally
seeded from a `.env` file at the project root. The flow:

1. `config/settings.py:15` `_load_dotenv()` reads `.env` (simple `KEY=VALUE`
   lines) and populates `os.environ` *without overriding* anything already set
   in the real environment. So real env vars always win over `.env`.
2. `env()` / `env_bool()` helpers (`config/settings.py:32`) read individual keys
   with defaults.
3. `.env.example` documents the full set; copy it to `.env` for local dev.

### Environment variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `SECRET_KEY` | Django signing/crypto key. **Set a strong one in prod.** | insecure dev value |
| `DEBUG` | Debug mode; also flips security hardening + static backend. | `true` |
| `ALLOWED_HOSTS` | Comma-separated allowed Host headers. | `localhost,127.0.0.1` |
| `BASE_URL` | Public base URL used to build absolute QR + magic links. | `http://localhost:8000` |
| `DATABASE_URL` | Postgres DSN; omit for SQLite. | (unset → SQLite) |
| `TARGET_DOMAIN` | Email domain appended to usernames. | `andrew.cmu.edu` |
| `QR_ROTATE_SECONDS` | How often the kiosk QR refreshes. | `5` |
| `TOKEN_TTL_SECONDS` | How long a scanned token stays valid. | `15` |
| `SURVEY_TTL_MINUTES` | Session lifetime after a scan. | `20` |
| `VERIFY_TTL_HOURS` | Magic-link lifetime. | `24` |
| `POSTMARK_SERVER_TOKEN` | Enables real email via Postmark. | (unset → console) |
| `DEFAULT_FROM_EMAIL` | From address on outgoing mail. | `Survey Kiosk <noreply@andrew.cmu.edu>` |

The survey-specific constants (`TARGET_DOMAIN`, the timing values) are promoted
to module-level settings at `config/settings.py:187` so views/models can read
them via `settings.X`.

## Security hardening

When `DEBUG` is false (`config/settings.py:176`) the app turns on: SSL redirect,
secure session/CSRF cookies, the `X-Forwarded-Proto` header trust (for running
behind a TLS-terminating proxy), and one year of HSTS including subdomains.
`CSRF_TRUSTED_ORIGINS` is set from `BASE_URL` when it's https
(`config/settings.py:48`).
