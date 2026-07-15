# 05 · Admin & Operations

How staff manage content and read results (Django admin), the management
commands, and how the app is run/deployed.

## Django admin (`survey/admin.py`)

The admin is the staff control panel — content authoring, response review, prize
codes, and CSV export. Reachable at `/admin/` after `createsuperuser`.

### Registered models & customizations

| Model | Highlights |
|-------|------------|
| **Survey** (`admin.py:33`) | lists name/active/question count; **Questions inline** for quick editing |
| **Question** (`admin.py:43`) | filter by survey/type/short; `order` and `included_in_short` editable inline; **Choices inline** |
| **Kiosk** (`admin.py:51`) | shows survey + the per-kiosk rotate/ttl overrides |
| **SurveySession** (`admin.py:106`) | the results view — see below |
| **PrizeCode** (`admin.py:143`) | searchable; adds a **bulk upload** page — see below |
| **PrizeClaim** (`admin.py:190`) | lists email/status/assigned code; `verify_token` is read-only |

### Results dashboard (SurveySession)

`SurveySessionAdmin` (`admin.py:106`) is where you read results:

- **Summary cards.** `changelist_view` (`admin.py:116`) aggregates counts and
  renders them above the list via the `surveysession/change_list.html` override:
  sessions by status (+ a computed **completion rate**), claims by status, and
  prize codes (total / assigned / free). One glance tells you how the study is
  going and whether the code pool is running low.
- **Per-session answers.** Opening a session shows a read-only `AnswerInline`
  (`admin.py:57`) rendering each answer via `display_value()` (doc 02).
- **CSV export.** The `export_sessions_csv` action (`admin.py:72`): select sessions
  → action → download. The CSV is **wide** — base columns (`session_id`, kiosk,
  survey, length, status, timestamps) followed by **one column per question**
  across the selected sessions' surveys, ordered by `(survey, order, id)`.
  Image-grid answers serialize as `row,col`. Implemented with `select_related`/
  `prefetch_related` to avoid N+1 queries.

### Prize-code upload

`PrizeCodeAdmin` (`admin.py:143`) adds a custom admin URL `upload/`
(`get_urls`, `admin.py:150`) and an "Upload codes" button on the changelist
(`prizecode/change_list.html`). `upload_codes` (`admin.py:161`) takes a textarea
of **one code per line**, dedupes against existing codes and within the paste,
creates the new ones, and reports `Added N; skipped M duplicate(s)`. This is how
the real prize pool gets loaded before launch.

## Management commands (`survey/management/commands/`)

Run as `uv run python manage.py <command>`.

### `seed_demo` — placeholder content for dev/testing
Creates a demo Survey (15 questions, first 5 flagged short, all 5 types incl. a
generated grid PNG), a Kiosk, and 5 test prize codes. **Idempotent**: it
`update_or_create`s the Survey and clears/recreates its questions rather than
deleting the Survey — important because `Kiosk.survey`/`SurveySession.survey` are
`on_delete=PROTECT`, so deleting a referenced Survey would raise `ProtectedError`.
Safe to re-run.

### `expire_sessions` — the cron heartbeat
`expire_sessions.py` flips any `active` session whose `expires_at` has passed to
`expired`, in one bulk `UPDATE`. Sessions also expire **lazily** on the next
request (doc 03), so this command is a sweep for sessions that were simply
abandoned and never hit again. Intended to run every minute from cron:

```cron
* * * * * cd /app && uv run python manage.py expire_sessions
```

### `purge_data` — retention (shipped but unscheduled)
Retention is **indefinite by default** for this deployment, so this command is
not scheduled — it exists so a retention window can be enforced later without
code changes. `--days N` is **required**; `--yes` skips the confirmation prompt.

```bash
uv run python manage.py purge_data --days 90 --yes          # delete sessions older than 90 days (cascades to answers/claims)
uv run python manage.py purge_data --days 30 --emails-only --yes  # just scrub claim email addresses, keep responses
```

## Running locally

```bash
uv sync
cp .env.example .env                      # then edit
uv run python manage.py migrate           # build the DB schema
uv run python manage.py seed_demo         # demo survey + kiosk + test codes
uv run python manage.py createsuperuser   # admin login
uv run python manage.py runserver
```

Then visit `/` (redirects to the kiosk), `/kiosk/<id>/`, or `/admin/`. Without
`DATABASE_URL` it uses SQLite; without `POSTMARK_SERVER_TOKEN` the magic-link
email prints to the console — copy the link from the terminal to test verify.

## Tests (`survey/tests.py`)

```bash
uv run python manage.py test
```

Nine tests covering the token freshness/tamper logic and the full flow: unique
session minting, expired-token 410, end-to-end code assignment, idempotent
verify (no double-spend), mailbox dedup, pool-empty handling, and session-expiry
gating. They run with the locmem email backend and `RATELIMIT_ENABLE=False`.

## Deployment

The `Procfile` declares two process types:

```
web:     gunicorn config.wsgi --bind 0.0.0.0:${PORT:-8000} --workers 3
release: python manage.py migrate --noinput
```

`web` is the app server; `release` runs migrations on each deploy. The stack is
host-agnostic (anything that understands a Procfile, or run the two commands
yourself). Before serving in production:

```bash
DEBUG=false uv run python manage.py collectstatic --noinput   # build the WhiteNoise manifest
```

Set `DEBUG=false`, a strong `SECRET_KEY`, real `ALLOWED_HOSTS`/`BASE_URL` (https),
a managed `DATABASE_URL` (Postgres — see the concurrency note in doc 01/02), and
Postmark credentials. With `DEBUG=false` the app forces HTTPS redirect, secure
cookies, and HSTS (doc 01).

### Before-launch checklist (content owners)

1. Paste the IRB-approved consent wording into the Survey's *consent text*.
2. Upload the real prize codes via **Admin → Prize codes → Upload codes**.
3. Replace the placeholder questions and upload real grid images.
4. Add the Postmark server token + a verified sending domain.
5. If running behind a proxy/load balancer, ensure the real client IP is passed
   through, or IP rate limiting (doc 03) keys on the proxy.
