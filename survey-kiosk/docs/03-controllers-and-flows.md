# 03 · Controllers & Request Flows

The "C" in MVC. In Django the controller is the **view function**. All of them
live in `survey/views.py`; routing lives in `survey/urls.py`. Supporting logic
sits in `survey/tokens.py`, `survey/forms.py`, and `survey/emails.py`.

## URL map (`survey/urls.py`, namespace `survey:`)

| Pattern | View | Name | Purpose |
|---------|------|------|---------|
| `/` | `home` | `home` | redirect to the lone active kiosk, else admin |
| `/kiosk/<int>/` | `kiosk_page` | `kiosk` | the always-on kiosk screen |
| `/kiosk/<int>/qr` | `kiosk_qr` | `kiosk_qr` | HTMX fragment: a fresh signed QR |
| `/s/<token>` | `scan` | `scan` | scan target; validates token, mints a session |
| `/survey/<uuid>/start` | `start` | `start` | consent + short/long pick |
| `/survey/<uuid>/q/<int>` | `question` | `question` | one question per step |
| `/survey/<uuid>/claim` | `claim` | `claim` | enter username → send magic link |
| `/claim/verify/<token>` | `verify` | `verify` | magic link → assign code |

Top-level routing (`config/urls.py`) mounts `admin/` and includes
`survey.urls` at the root, plus serves `media/` when `DEBUG`.

Sessions are addressed by **UUID**, not a sequential id, so a URL can't be
guessed to reach someone else's run.

---

## The four flows

### Flow 1 — Rotating QR (kiosk idle loop)

```
kiosk_page renders kiosk.html
   └─ <div id="qr" hx-get=".../qr" hx-trigger="load, every Ns">
         every N seconds → kiosk_qr → returns _qr.html fragment
```

- `kiosk_page` (`views.py:55`) renders the shell and passes
  `effective_rotate_seconds`.
- The page's `#qr` div polls `kiosk_qr` via HTMX every N seconds (doc 04).
- `kiosk_qr` (`views.py:64`) mints a fresh token, builds the absolute scan URL
  `BASE_URL + /s/<token>`, renders it to a base64 PNG data-URI
  (`_qr_data_uri`, `views.py:44`), and returns just the image fragment.
- Rate-limited to 120/min per IP (a kiosk polls ~12/min, so this only stops
  abuse).

**Why no DB row for the token:** the token *is* the state. See "Token design".

### Flow 2 — Scan → session

```
phone scans QR → GET /s/<token>
   scan(): verify_kiosk_token(token, max_age=TOKEN_TTL_SECONDS)
     ├─ invalid/expired → expired_token.html (HTTP 410)
     └─ valid → create SurveySession → redirect to /survey/<uuid>/start
```

- `scan` (`views.py:80`) is the heart of the "unique session per scan" guarantee:
  every successful scan calls `SurveySession.objects.create(...)`, so two phones
  scanning the *same* on-screen code still get two distinct sessions.
- An expired or tampered token yields **410 Gone** with a "scan again" page.
- Rate-limited 30/min per IP.

### Flow 3 — Take the survey

```
/survey/<uuid>/start  (GET)  → consent.html (consent text + short/long radios)
/survey/<uuid>/start  (POST) → validate length + consent → redirect to q/1
/survey/<uuid>/q/1 … q/N      → one question per step, POST advances
   last step → mark session completed → redirect to /claim
```

- **Liveness gate.** `_live_session_or_response` (`views.py:93`) is called at the
  top of `start` and `question`. It:
  - redirects to `claim` if the session is already `completed`,
  - returns `expired_session.html` (**410**) if not live, *and lazily flips*
    a lapsed `active` session to `expired` as a side effect,
  - otherwise returns the live session to the view.
- `start` (`views.py:108`) validates the length is a real choice and that consent
  was ticked; on success it stores `length` + `consented` and sends the user to
  step 1. Validation errors re-render the consent page with **400**.
- `question` (`views.py:188`) loads the ordered question list via
  `survey.questions_for(length)`, clamps out-of-range steps back to step 1, and:
  - on **GET** renders the current question (pre-filling any existing answer so
    Back/refresh is non-destructive),
  - on **POST** calls `_save_answer`; if valid and it's the last step, marks the
    session `completed` + `completed_at` and redirects to `claim`; otherwise
    advances to `step + 1`.
- **`_save_answer`** (`views.py:138`) is the per-type validation/persistence
  switch. It `get_or_create`s the single `Answer` row for this (session,
  question), then by type:
  - `single` — one valid choice (or error if required),
  - `multi` — set of valid choices,
  - `likert` — integer within `likert_range`,
  - `short_text` — trimmed text,
  - `image_grid` — integer `(row, col)` within `grid_rows × grid_cols`.
  It returns an error string (re-rendered on the page) or `None`.

### Flow 4 — Claim, verify, deliver

```
/survey/<uuid>/claim (POST username)
   ├─ session not completed → bounce to survey or 410
   ├─ session already has a claim → show its pending/result page
   ├─ ClaimForm validates + normalizes username → email
   ├─ mailbox already won a prize → form error "already claimed"
   ├─ a live pending claim for this mailbox exists → re-show pending (no re-send)
   └─ else create PrizeClaim(pending) + send magic-link email → claim_pending.html

GET /claim/verify/<token>
   ├─ no such token → verify_invalid.html (404)
   ├─ pending but link expired → verify_invalid.html (410)
   ├─ _assign_prize() (atomic): assign next free code → verified, else pool_empty
   ├─ IntegrityError (mailbox raced to verified elsewhere) → verify_invalid (409)
   └─ prize.html (shows the code, or the pool-empty message)
```

- `claim` (`views.py:232`, POST rate-limited 10/min/IP) enforces three things in
  order: the survey must be **completed**; a session gets **one** claim (re-visits
  route to the existing claim's page); and a **mailbox** can only win once. The
  "already won" and "live pending" checks (`views.py:254`) give friendly messages
  *before* the DB constraint would trip.
- **Username → email** is handled by `ClaimForm` (`forms.py:9`): it lowercases,
  tolerates a pasted full `user@TARGET_DOMAIN` (rejecting any other domain),
  validates the local part against `^[A-Za-z0-9._-]+$`, and exposes the composed
  address via the `email` property. The participant only ever types their
  username; the domain is appended server-side (`settings.TARGET_DOMAIN`).
- `send_verify_email` (`emails.py:6`) builds `BASE_URL + /claim/verify/<token>`
  and sends it (console backend in dev, Postmark in prod).
- **`_assign_prize`** (`views.py:277`) is the money path and is written to be
  **safe under concurrency and idempotent**:
  - wraps everything in `transaction.atomic()`,
  - `select_for_update()` on the claim row (so two clicks of the same link
    serialize),
  - returns early if the claim is no longer `pending` — so re-clicking the link
    shows the *same* code rather than burning another,
  - grabs the next free code with
    `select_for_update(skip_locked=True).filter(assigned=False).order_by("id").first()`
    so concurrent verifications never hand out the same code,
  - if a code is found: marks it assigned + linked, sets the claim `verified`;
    if none: marks the claim `pool_empty`.
- `verify` (`views.py:307`) handles the not-found (404) and expired-link (410)
  cases, calls `_assign_prize`, and catches `IntegrityError` → **409** for the
  rare race where another claim for the same mailbox verified first.

---

## Token design (`survey/tokens.py`)

The rotating QR token is a **signed, self-describing token — no database row**.

- `mint_kiosk_token(kiosk_id)` (`tokens.py:16`) signs `{"k": kiosk_id, "n": nonce}`
  with Django's `TimestampSigner` (HMAC + embedded timestamp), where the nonce
  makes every minted token unique even within the same second.
- `verify_kiosk_token(token, max_age)` (`tokens.py:22`) returns the kiosk id only
  if the signature is valid **and** `now - timestamp ≤ max_age`; otherwise `None`
  (it swallows `SignatureExpired` / `BadSignature`).

Freshness is therefore enforced cryptographically at scan time — the server keeps
no per-token state, which is what lets the QR rotate every few seconds cheaply.
The verify-link token is different: it's a stored, single-use
`PrizeClaim.verify_token` with a DB-backed expiry (doc 02).

---

## Rate limiting

`django-ratelimit` decorates the abuse-prone endpoints (`views.py`): `kiosk_qr`
120/min, `scan` 30/min, `claim` 10/min (POST only). All key on client IP and
`block=True` (a hit raises `Ratelimited`, a `PermissionDenied` subclass → **403**).

> Operational note: behind a proxy/load balancer the client IP must be passed
> through (e.g. `X-Forwarded-For` handling) or every request looks like it comes
> from the proxy. The README's "before launch" section calls this out.

## HTTP status conventions used here

| Status | Meaning in this app |
|--------|---------------------|
| 302 | redirect between flow steps (`/` → kiosk, scan → start, last question → claim) |
| 400 | consent form validation failed |
| 403 | rate limit exceeded |
| 404 | unknown verify token |
| 409 | mailbox raced to a verified prize on another claim |
| 410 | token expired, or session expired/over — "scan again" |

## Where to make common changes

| You want to… | Touch |
|--------------|-------|
| Add a question type | `Question.Type` + `Answer` fields (doc 02), `_save_answer` (`views.py:138`), `question.html` (doc 04) |
| Change session length / token timing | env vars (doc 01) or per-kiosk overrides (doc 02) |
| Change the claim domain or username rules | `ClaimForm` (`forms.py`) + `TARGET_DOMAIN` |
| Change prize-assignment policy | `_assign_prize` (`views.py:277`) |
| Add a landing page at `/` | `home` (`views.py:30`) |
| Adjust rate limits | the `@ratelimit` decorators in `views.py` |
