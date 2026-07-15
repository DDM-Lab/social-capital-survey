# 02 · Data Model

All models live in `survey/models.py`. This is the "M" in MVC. Schema changes
require a migration (`uv run python manage.py makemigrations && … migrate`).

## Entity-relationship overview

```
Kiosk ─────┐ (PROTECT)
           ▼
        Survey ──< Question ──< Choice
           │           ▲
           │ (PROTECT)  │ (CASCADE)
           ▼            │
     SurveySession ──< Answer >── Question
           │ 1:1
           ▼
      PrizeClaim ──(SET_NULL)── PrizeCode
           ▲                        │
           └──── assigned_to ───────┘ (1:1, SET_NULL)
```

- `──<` = one-to-many (FK on the child).
- The label in parentheses is the `on_delete` behavior of that FK.

The two distinct halves of the model:
1. **Content** (authored by staff): `Survey`, `Question`, `Choice`, `Kiosk`.
2. **Run-time data** (created by participants): `SurveySession`, `Answer`,
   `PrizeClaim`, plus the staff-loaded `PrizeCode` pool.

`on_delete=PROTECT` on the content→run-time links is deliberate: you can't delete
a Survey or Kiosk that has real sessions/responses pointing at it, which guards
against accidental data loss. (This is also why `seed_demo` updates the demo
Survey in place rather than deleting it — see doc 05.)

---

## Content models

### `Kiosk` (`models.py:10`)
A physical always-on screen.

| Field | Type | Notes |
|-------|------|-------|
| `name` | char | display name |
| `active` | bool | only active kiosks render / accept scans |
| `survey` | FK→Survey (PROTECT) | which survey this kiosk serves |
| `rotate_seconds` | int, nullable | per-kiosk override of QR refresh interval |
| `token_ttl_seconds` | int, nullable | per-kiosk override of token validity |

Two convenience properties fall back to project settings when the override is
null: `effective_rotate_seconds` / `effective_token_ttl_seconds`
(`models.py:28`). Views read these, never the raw fields, so the global default
applies unless a kiosk overrides it.

### `Survey` (`models.py:37`)
A bank of questions. The "short" variant is simply the subset of questions
flagged `included_in_short`.

| Field | Type | Notes |
|-------|------|-------|
| `name` | char | |
| `active` | bool | |
| `consent_text` | text | IRB consent wording shown before the survey (placeholder until pasted) |

`questions_for(length)` (`models.py:51`) returns the ordered question set:
all questions for `long`, only the short-flagged ones for `short`.

### `Question` (`models.py:58`)
Belongs to a Survey (CASCADE — deleting a survey deletes its questions).

| Field | Type | Notes |
|-------|------|-------|
| `text` | char(500) | |
| `type` | char choice | one of the 5 types below |
| `order` | int | sort order within the survey |
| `included_in_short` | bool | part of the 5-question short survey |
| `required` | bool | whether an answer is mandatory |
| `likert_min` / `likert_max` | int | used only for Likert |
| `likert_min_label` / `likert_max_label` | char | endpoint labels for Likert |
| `grid_image` | image, nullable | used only for image-grid; uploaded to `media/grids/` |
| `grid_rows` / `grid_cols` | int, nullable | grid dimensions for image-grid |

**Question types** (`Question.Type`, `models.py:59`):

| Value | Label | Answer stored in |
|-------|-------|------------------|
| `single` | Single choice | `Answer.choices` (exactly 1) |
| `multi` | Multiple choice | `Answer.choices` (N) |
| `likert` | Likert scale | `Answer.likert_value` |
| `short_text` | Short text | `Answer.text_value` |
| `image_grid` | Image grid (single cell) | `Answer.grid_row` + `Answer.grid_col` |

`likert_range` property (`models.py:92`) yields `range(min, max+1)` for rendering
and validation.

### `Choice` (`models.py:97`)
A selectable option for single/multi questions. FK→Question (CASCADE), with
`text` and `order`.

---

## Run-time models

### `SurveySession` (`models.py:111`)
One participant's run, created the instant a QR is scanned.

| Field | Type | Notes |
|-------|------|-------|
| `id` | **UUID** PK | non-guessable; appears in URLs |
| `kiosk` | FK→Kiosk (PROTECT) | |
| `survey` | FK→Survey (PROTECT) | snapshotted from the kiosk at mint time |
| `length` | char choice | `short` / `long`; blank until the participant picks |
| `status` | char choice | `active` / `completed` / `expired` (default `active`) |
| `consented` | bool | set true when IRB consent is given |
| `created_at` | datetime | auto |
| `expires_at` | datetime | auto-set on first save (see below) |
| `completed_at` | datetime, nullable | set when the last question is answered |

Lifecycle helpers:
- `save()` (`models.py:131`) sets `expires_at = now + SURVEY_TTL_MINUTES` if not
  already set, so the 20-minute clock starts at creation.
- `is_expired` — clock has passed.
- `is_live` (`models.py:141`) — `status == active AND not expired`. Views gate
  every survey action on this.

Status transitions: `active → completed` (finished the last question) or
`active → expired` (clock ran out — flipped lazily on the next request, or in
bulk by the `expire_sessions` command).

### `Answer` (`models.py:148`)
One participant's answer to one question. FK→Session (CASCADE) and FK→Question
(CASCADE). Which field holds the value depends on the question type (see the
type table above). A **unique constraint** on `(session, question)`
(`models.py:159`) guarantees at most one answer per question per session, so
re-submitting a step updates rather than duplicates.

`display_value()` (`models.py:166`) renders any answer to a string for admin/CSV:
text as-is, Likert as its number, image-grid as `"row,col"`, and choices joined
with `; `.

### `PrizeCode` (`models.py:182`)
The pool of redemption codes that staff upload.

| Field | Type | Notes |
|-------|------|-------|
| `code` | char, **unique** | the redemption code |
| `assigned` | bool | whether it's been handed out |
| `assigned_to` | 1:1→PrizeClaim (SET_NULL) | which claim got it |
| `created_at` | datetime | |

### `PrizeClaim` (`models.py:200`)
A participant's attempt to claim a prize, created when they submit a username.

| Field | Type | Notes |
|-------|------|-------|
| `session` | **1:1**→Session (CASCADE) | one claim per session |
| `email` | email | `username@TARGET_DOMAIN`, normalized lowercase |
| `status` | char choice | `pending` / `verified` / `pool_empty` (default `pending`) |
| `verify_token` | char, **unique** | single-use magic-link token; defaults to `secrets.token_urlsafe` |
| `verify_expires_at` | datetime | auto-set to `now + VERIFY_TTL_HOURS` on save |
| `prize_code` | FK→PrizeCode (SET_NULL), nullable | the awarded code, once verified |
| `created_at` / `verified_at` | datetime | |

Status meaning:
- `pending` — email sent, link not yet clicked.
- `verified` — link clicked, a code was assigned (`prize_code` is set).
- `pool_empty` — link clicked but no codes were free; counts as "claimed" so the
  participant can't keep trying with the same mailbox.

**The key constraint** (`models.py:217`): a conditional `UniqueConstraint` on
`email`, applied **only** to rows whose status is `verified` or `pool_empty`.
This enforces *one prize per mailbox* at the database level while still allowing
multiple `pending` attempts (e.g. the same person scanning twice before clicking
the link). Because it's a partial/conditional index it **requires PostgreSQL** in
production for full effect.

`verify_expired` property (`models.py:232`) checks the magic-link clock.

---

## Where each constraint is enforced

| Rule | Enforced by | Location |
|------|-------------|----------|
| One answer per (session, question) | DB unique constraint | `models.py:159` |
| One claim per session | 1:1 field | `models.py:206` |
| One delivered prize per mailbox | DB conditional unique constraint | `models.py:217` |
| Code uniqueness | DB unique on `PrizeCode.code` | `models.py:185` |
| Can't delete a Survey/Kiosk with sessions | `on_delete=PROTECT` | `models.py:17,122,123` |

Application-level checks in the views back these up with friendly messages
before the DB constraint would fire — see doc 03.
