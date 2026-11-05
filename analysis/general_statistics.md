# General survey participation statistics

Source: `2026-Grace-Hunt Library Survey_November 5, 2026_10.09.csv`.

## Who is counted

A completed survey has `Finished=True` (or `1`). Exclude the staff IDs in `post_processing.STAFF` using both identity fields, exclude previews, and require affirmative study consent. Use the raw export before removing later same-day submissions, so those repeats remain observable. Normalize IDs by trimming whitespace, lowercasing, and removing the email domain; prefer Email and fall back to participantemail. Counts describe IDs, with no identifying values exported.

Input records: **397**. Mutually exclusive exclusions, checked in staff/preview/consent/completion order: staff 50, previews 0, no consent 13, not finished 0.

## Unique participants and completed surveys

| Measure | Count |
| --- | --- |
| Completed non-staff, consenting submissions (before same-day deduplication) | 334 |
| Completed submissions with an identifiable participant ID | 327 |
| Unique normalized non-staff participant IDs | 238 |
| Completed submissions without an ID (cannot check repeat participation) | 7 |
| IDs with exactly one completed submission | 195 |
| IDs with two or more completed submissions | 43 (18.1%) |
| Additional identified submissions beyond each ID's first | 89 |

## Most frequent survey day and time

Timing uses **survey start in Eastern local time**, matching the existing analysis. An hour interval includes its starting hour and excludes the next hour. Voucher periods are the recorded categories, not inferred clock intervals. Percentages use all qualifying completed submissions, including repeats and submissions without IDs. All ties are shown. These counts reflect collected responses rather than response rates adjusted for tablet availability or sampling exposure.

| Measure | Peak category (all ties) | Submissions (% of completed) |
| --- | --- | --- |
| Most frequent weekday | Tuesday | 78 (23.4%) |
| Most frequent voucher period | Lunch | 144 (43.1%) |
| Most frequent start-hour interval | 12:00-13:00 | 45 (13.5%) |
| Most frequent weekday + voucher period | Tuesday / Lunch | 38 (11.4%) |
| Most frequent weekday + start hour | Tuesday / 14:00-15:00 | 11 (3.3%) |

### Weekday distribution

| Weekday | Completed submissions |
| --- | --- |
| Monday | 50 (15.0%) |
| Tuesday | 78 (23.4%) |
| Wednesday | 62 (18.6%) |
| Thursday | 65 (19.5%) |
| Friday | 47 (14.1%) |
| Saturday | 16 (4.8%) |
| Sunday | 16 (4.8%) |

### Voucher-period distribution

| Voucher period | Completed submissions |
| --- | --- |
| Morning | 41 (12.3%) |
| Lunch | 144 (43.1%) |
| Dinner | 117 (35.0%) |
| Late Night | 24 (7.2%) |
| Off Hours | 1 (0.3%) |
| Unknown | 7 (2.1%) |

## Repeat participation

**43 of 238 identifiable participants** completed more than one survey. The following counts are numbers of unique IDs meeting each condition at least once across the entire export; the rows overlap and must not be added together. Missing-ID submissions are excluded from repeat counts.

| Repeat pattern | Unique IDs |
| --- | --- |
| Two or more submissions on the same local date | 1 |
| Two or more submissions in the same Monday-Sunday calendar week (includes same-day repeats) | 20 |
| Submissions on two or more different dates in the same Monday-Sunday week | 19 |
| Two or more submissions in a rolling seven-calendar-day window (includes same-day repeats) | 30 |
| Submissions on different dates in a rolling seven-calendar-day window | 29 |

A calendar week runs Monday through Sunday, using the ISO week-year to handle year boundaries. A rolling seven-calendar-day window spans local dates separated by 0-6 days, so it can cross a Sunday/Monday boundary. All repeat classifications use survey start dates. Same-week counts include same-day repeats; the different-day rows distinguish return visits.

### Non-overlapping breakdown of repeat participants

| Pattern | Unique IDs |
| --- | --- |
| Different-day repeats within a calendar week, without any same-day repeat | 19 |
| Same-day repeats, without different-day repeats within a calendar week | 1 |
| Both same-day repeats and different-day repeats within a calendar week | 0 |
| Repeat participants with neither of those patterns (different calendar weeks only) | 23 |

These four categories sum to 43. There are 1 participant/date groups with same-day repeats, containing 1 additional same-day submissions beyond the first in each group.

### Completed submissions per identifiable participant

| Submissions per ID | Unique IDs |
| --- | --- |
| 1 | 195 |
| 2 | 24 |
| 3 | 9 |
| 4 | 2 |
| 5 | 2 |
| 6 | 4 |
| 7 | 1 |
| 8 | 1 |

## Relation to the question-level analysis

The question-level analysis keeps the earliest identified submission per day and does not separately filter on Finished. This participation report requires completion and includes later same-day submissions. These definitions can produce different submission totals; unique-ID counts cannot account for unidentified submissions.
