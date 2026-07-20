# Survey JSON Field Reference

This file documents the JSON schema used by files in this folder.

## Top-level survey object

| Field | Type | Required | Meaning |
|---|---|---|---|
| name | string | Yes | Survey name (non-empty). |
| consent_text | string | Yes | Consent text shown before questions. |
| active | boolean | Yes | Whether the survey is active. |
| questions | array<object> | Yes | Ordered question definitions. |

## Fields shared by all question types

| Field | Type | Required | Meaning |
|---|---|---|---|
| type | string | Yes | Question type. One of: single, multi, multi_matrix, likert, short_text, image_grid. |
| order | integer | Yes | Display order. Must be unique across all questions. |
| text | string | Yes | Question prompt (non-empty). |
| included_in_short | boolean | No | Include in short survey mode. Default: false. |
| required | boolean | No | Whether the question requires an answer. Default: true. |

## single

| Field | Type | Required | Meaning |
|---|---|---|---|
| choices | array<object> | Yes | Select-one options. Must be non-empty. |

## multi

| Field | Type | Required | Meaning |
|---|---|---|---|
| choices | array<object> | Yes | Select-many options. Must be non-empty. |

## multi_matrix

| Field | Type | Required | Meaning |
|---|---|---|---|
| choices | array<object> | Yes | Matrix rows. Must be non-empty. |
| columns | array<object> | Yes | Matrix columns. Must be non-empty. |
| row_select_mode | string | No | Row uniqueness rule for choice columns. Values: single or multi. Default: multi. |
| char_limit | integer | No | Max character length for short_text matrix cells. Must be > 0 if present. |

### multi_matrix column object

| Field | Type | Required | Meaning |
|---|---|---|---|
| key | string | Yes | Column key (unique within question). |
| label | string | Yes | Column label shown in UI. |
| kind | string | No | Column behavior. Values: choice or short_text. Default: choice. |
| required | boolean | No | Whether this column is required independently. Default: false. |
| select_mode | string | Conditional | For kind=choice only. Values: single or multi. Default: single. |
| text_mode | string | Conditional | For kind=short_text only. Values: string or integer. Default: string. |

## likert

| Field | Type | Required | Meaning |
|---|---|---|---|
| likert_min | integer | Yes | Minimum scale value. |
| likert_max | integer | Yes | Maximum scale value. Must be >= likert_min. |
| likert_min_label | string | No | Label for minimum endpoint. Default: empty string. |
| likert_max_label | string | No | Label for maximum endpoint. Default: empty string. |

## short_text

| Field | Type | Required | Meaning |
|---|---|---|---|
| field_count | integer | No | Number of vertically stacked text fields. Must be > 0. Default: 1. |
| char_limit | integer | No | Shared max length per field. Must be > 0 if present. |
| field_required | array<boolean> | No | Per-field required flags. Length must equal field_count. Default: repeats required for each field. |

## image_grid

| Field | Type | Required | Meaning |
|---|---|---|---|
| grid_image | string | Yes | Image path for the grid prompt. |
| grid_rows | integer | Yes | Number of grid rows. Must be > 0. |
| grid_cols | integer | Yes | Number of grid columns. Must be > 0. |

## Reusable nested objects

### choice object

Used by single, multi, and multi_matrix choices.

| Field | Type | Required | Meaning |
|---|---|---|---|
| text | string | Yes | Option text (non-empty). |
| order | integer | No | Option order. If omitted, defaults to array index order. |
