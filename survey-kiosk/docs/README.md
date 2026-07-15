# Survey Kiosk — Architecture Docs

These documents describe how the codebase is structured so you can modify it
confidently. Read them in order the first time; afterwards use them as reference.

| Doc | What it covers |
|-----|----------------|
| [01-tech-stack.md](01-tech-stack.md) | Frameworks, libraries, why each was chosen, how config flows from the environment. |
| [02-data-model.md](02-data-model.md) | Every model, its fields, relationships, constraints, and lifecycle. The "M" in MVC. |
| [03-controllers-and-flows.md](03-controllers-and-flows.md) | URL map, each view, and the end-to-end request flows. The "C" in MVC. |
| [04-templates-and-frontend.md](04-templates-and-frontend.md) | Templates, HTMX usage, the image-grid widget, static assets. The "V" in MVC. |
| [05-admin-and-operations.md](05-admin-and-operations.md) | Django admin customizations, management commands, deploy & ops. |

## What this app does (one paragraph)

An always-on kiosk screen shows a QR code that **rotates every few seconds**.
Each scan mints a **unique, time-boxed survey session** (20 min). The participant
picks a short (5 questions) or long (15 questions) survey, gives IRB consent,
answers one question per screen, then claims a prize by entering their CMU
username. The app emails a **magic link** that simultaneously proves they own
the mailbox and reveals a **one-time redemption code** drawn from an
admin-uploaded pool. Staff view results and export CSV from the Django admin.

## How "MVC" maps onto this Django project

Django uses the **MTV** naming (Model–Template–View), which is the same idea as
MVC with different labels:

| MVC term | Django term | Where it lives here |
|----------|-------------|---------------------|
| **Model** | Model | `survey/models.py` (+ migrations) |
| **Controller** | **View** | `survey/views.py`, routed by `survey/urls.py` |
| **View** (presentation) | **Template** | `survey/templates/**` + `survey/static/**` |

So when this app says "view" it means the request-handling function (the
controller). The HTML lives in templates. Keep that mapping in mind while
reading `03-controllers-and-flows.md` (the controllers) and
`04-templates-and-frontend.md` (the presentation).

## Project layout at a glance

```
survey-kiosk/
├── manage.py                 # Django entry point (run via `uv run python manage.py …`)
├── pyproject.toml / uv.lock  # dependencies, managed by uv
├── Procfile                  # process types for deployment (web + release)
├── .env.example              # documents every environment variable
├── config/                   # the Django "project" (site-wide wiring)
│   ├── settings.py           # all configuration, read from the environment
│   ├── urls.py               # top-level URL routing (admin, survey, media)
│   ├── wsgi.py / asgi.py     # server entry points
├── survey/                   # the one Django "app" (all domain logic)
│   ├── models.py             # data model  → doc 02
│   ├── views.py              # controllers  → doc 03
│   ├── urls.py               # routes       → doc 03
│   ├── forms.py              # username/claim validation
│   ├── tokens.py             # signed rotating-QR tokens (no DB row)
│   ├── emails.py             # magic-link email
│   ├── admin.py              # admin dashboard, CSV export, code upload → doc 05
│   ├── templates/            # HTML (survey/ + admin/ overrides) → doc 04
│   ├── static/survey/        # app.css, grid.js → doc 04
│   ├── management/commands/  # seed_demo, expire_sessions, purge_data → doc 05
│   └── migrations/           # generated schema history
└── docs/                     # you are here
```

## Conventions used throughout

- **Config comes from the environment.** Nothing deployment-specific is hard-coded;
  see `config/settings.py` and `.env.example`. Without a `DATABASE_URL` the app uses
  a local SQLite file; without `POSTMARK_SERVER_TOKEN` emails print to the console.
- **One Django app (`survey`).** The project is small enough that splitting it would
  add ceremony without benefit. Add new domain features here.
- **Server-rendered + HTMX, no SPA.** Pages are plain Django templates; HTMX adds
  the QR auto-refresh and could add more partial updates later (doc 04).
- **References below use `file:line`** so you can jump straight to the code.
