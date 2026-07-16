# 04 · Templates & Frontend

The "V" (presentation) in MVC. This app is **server-rendered HTML with a sprinkle
of HTMX** — there is no SPA, no build step, no front-end framework. Templates
live in `survey/templates/`, static assets in `survey/static/survey/`.

## Template inventory

### Participant-facing (`survey/templates/survey/`)

| Template | Rendered by | Role |
|----------|-------------|------|
| `base.html` | (extended by all) | HTML skeleton, loads HTMX + `app.css`, renders flash messages, defines `content`/`scripts` blocks |
| `kiosk.html` | `kiosk_page` | the always-on screen; HTMX-polls for the QR |
| `_qr.html` | `kiosk_qr` | tiny fragment: just the `<img>` QR (swapped into the kiosk page) |
| `consent.html` | `start` | IRB consent text + short/long radio choice |
| `question.html` | `question` | renders any of the 5 question types + Back/Next |
| `claim.html` | `claim` (GET) | username entry form |
| `claim_pending.html` | `claim` (POST ok) | "check your email" page |
| `prize.html` | `verify` (ok) | reveals the prize code, or the pool-empty message |
| `expired_token.html` | `scan` (stale token) | "scan again" — HTTP 410 |
| `expired_session.html` | survey views (lapsed) | "session expired, scan again" — 410 |
| `verify_invalid.html` | `verify` (bad/expired/dup) | invalid magic link — 404/410/409 |

`_qr.html` is prefixed with `_` by convention to flag it as a **partial** (a
fragment meant to be embedded, not a full page).

### Admin overrides (`survey/templates/admin/survey/`)

These extend Django's admin templates to add custom UI (covered in doc 05):
- `surveysession/change_list.html` — summary stat cards above the session list.
- `prizecode/change_list.html` — adds an "Upload codes" button.
- `prizecode/upload.html` — the paste-codes form page.

## The `base.html` shell

`base.html` provides: the viewport meta (locked scale for kiosk/phone), the HTMX
script from a CDN (`unpkg.com/htmx.org@1.9.12`, `base.html:8`), the stylesheet,
a flash-messages list, and two blocks — `content` (page body) and `scripts`
(per-page JS, used only by the image-grid page). Every participant page does
`{% extends "survey/base.html" %}`.

## HTMX usage (small and targeted)

HTMX is used in exactly one place today: the **kiosk QR auto-refresh**
(`kiosk.html:7`).

```html
<div id="qr"
     hx-get="{% url 'survey:kiosk_qr' kiosk.id %}"
     hx-trigger="load, every {{ rotate_seconds }}s"
     hx-swap="innerHTML">
```

- `hx-trigger="load, every Ns"` fetches once on load, then every N seconds.
- `hx-get` calls the `kiosk_qr` view, which returns `_qr.html` (just the `<img>`).
- `hx-swap="innerHTML"` replaces the contents of `#qr` with that fragment.

So the page never reloads; only the QR image is re-fetched on the interval the
kiosk's `effective_rotate_seconds` dictates. The rest of the survey uses plain
form POSTs and redirects (doc 03) — HTMX is available if you want to convert a
step to a partial swap later, but it isn't required.

> `django-htmx` middleware is installed (doc 01); it exposes `request.htmx` if you
> ever need a view to behave differently for HTMX vs full-page requests. Not used
> yet.

## How `question.html` renders the 5 types

A single template (`question.html`) handles every question type with an
`{% if question.type == … %}` ladder. Each branch emits the right input and
**pre-fills the existing answer**, so Back/refresh is non-destructive:

| Type | Markup | Pre-fill source |
|------|--------|-----------------|
| `single` | radio inputs named `choice` | `selected_choice_ids` (from the view) |
| `multi` | checkboxes named `choices` | `selected_choice_ids` |
| `multi_matrix` | table with row options and per-column radio/checkbox cells named `matrix_<column_key>` | `answer_value.selected_keys` |
| `likert` | radios over `question.likert_range`, with endpoint labels | `answer.likert_value` |
| `short_text` | `<textarea name="text">` | `answer.text_value` |
| `image_grid` | image + clickable overlay + hidden `grid_row`/`grid_col` | `answer.grid_row/col` data attributes |

The view passes `selected_choice_ids`, `answer`, `step`, `total`, and any `error`
string; the template just renders them. The submit button reads "Finish" on the
last step and "Next" otherwise (`question.html:70`).

## The image-grid widget (the one bit of custom JS)

This is the only non-trivial front-end piece. It turns an admin-uploaded image
into a tappable grid and records the chosen cell.

**Markup** (`question.html:52`): a `.grid-wrap` carrying `data-rows`/`data-cols`
(and any previously selected row/col), the `<img>`, an empty `.grid-overlay` whose
CSS grid is sized to `grid_rows × grid_cols`, and two hidden inputs `grid_row` /
`grid_col`.

**Behavior** (`static/survey/grid.js`): on load it reads the dimensions, builds
`rows × cols` `.grid-cell` divs into the overlay (each tagged with its
`data-row`/`data-col`), re-selects any previously chosen cell, and on click marks
the cell `selected` and writes its row/col into the hidden inputs. The script is
loaded only on image-grid pages via the `scripts` block (`question.html:77`).

On submit, those hidden fields are what `_save_answer` validates against
`grid_rows × grid_cols` (doc 03). It's plain vanilla JS in an IIFE — no
dependencies.

## Static assets (`survey/static/survey/`)

- `app.css` — minimal, clean styling (cards, choices, the Likert row, the grid
  overlay, buttons, flash messages). No framework.
- `grid.js` — the image-grid widget above.

Served by WhiteNoise. In production run `collectstatic` (doc 01 / doc 05) so the
hashed manifest is built; in dev they're served directly.

## Styling philosophy

Deliberately minimal/clean (a locked decision): legible on both a large kiosk
display and a phone. If you restyle, `app.css` is the single place; the templates
use stable class names (`card`, `choice`, `likert`, `grid-wrap`/`grid-overlay`/
`grid-cell`, `btn`, `messages`/`msg`).
