# Datasets

`apps.datasets` lets workspace members upload a CSV and get it stored, validated
and ready for later phases (column mapping, cleaning, forecasting).

## Model

`Dataset` (workspace-scoped, see `docs/permissions.md`):

| Field | Notes |
| --- | --- |
| `name` | Defaults to the uploaded filename; overridable at upload time. |
| `original_filename` | The client's filename, kept only for display. |
| `file` | Stored under `datasets/{workspace_id}/<random>.csv`; the client's filename is never used for the path. |
| `size`, `sha256` | Computed server-side from the uploaded bytes. |
| `status` | `uploaded` / `validated` / `failed` (later phases add the validated/failed transition). |
| `row_count` | Data rows, excluding the header. |
| `column_mapping`, `detected_frequency` | Set by the mapping endpoint (column roles, parse results, frequency). |

`sha256` is unique per workspace: uploading the same file twice to the same
workspace is rejected; the same content in a different workspace is fine.

Uploaded files are never served through a public URL (`MEDIA_ROOT` is not
wired to any Django static/media route) — reading one back requires an
authenticated, workspace-scoped API call, and no such read-the-file endpoint
exists yet.

## API (`/api/workspaces/{workspace_id}/datasets/`)

| Endpoint | Method | Role | Purpose |
| --- | --- | --- | --- |
| `datasets/` | GET | any member | List the workspace's datasets |
| `datasets/` | POST (multipart) | Owner/Analyst | Upload a CSV (`file`, optional `name`) |
| `datasets/{id}/` | GET | any member | Get one dataset |
| `datasets/{id}/mapping/` | PUT, PATCH | Owner/Analyst | Set the column mapping (see below) |

A non-member gets `404`; a Viewer gets `403` on upload. `Dataset` is registered
in `backend/tests/isolation.py`.

## Upload validation

Before anything is stored, the uploaded file must have a `.csv` extension, be
non-empty, be at or under `DATASET_MAX_UPLOAD_BYTES` (default 20 MB), decode as
UTF-8 (BOM-aware) text, use a comma, semicolon or tab delimiter
(`apps/datasets/validation.py` sniffs it), have at least one data row under its
header, and have no more than `DATASET_MAX_ROWS` rows (default 500,000). Any
failure is a uniform `400` with the reason in `error.details.file`.

## Column mapping

`PUT` replaces the mapping and requires `date` and `target`; `PATCH` merges the
given fields into the stored mapping. Fields:

| Field | Meaning |
| --- | --- |
| `date` | Timestamp column (required) |
| `target` | Numeric column to forecast (required) |
| `series_id` | Optional column identifying each series |
| `regressors` | Optional list of numeric columns |
| `date_order` | Optional `dmy` or `mdy`, to settle a day/month ambiguity |
| `timezone` | Optional IANA name for dates without a UTC offset |
| `decimal_separator` | Optional `.` or `,`, to settle an ambiguous number column |

Rules, all checked against the stored file (`apps/datasets/mapping.py`): every
column must exist and appear once in the header, one column cannot hold two
roles, the date column must parse, and the target and each regressor must be
numeric. Problems are returned together as `400` with `error.code =
invalid_mapping` and `error.details` keyed by role, each entry carrying its own
`code`, `message` and, where relevant, counts and example values (for
regressors, one entry per column name). Nothing is saved on a `400`.

**Dates** (`dates.py`) are matched against a fixed list of `strptime` formats; a
format is accepted only if it parses every value. If both day-first and
month-first formats fit (`03/04/2024`), the column is reported as
`ambiguous_date_order` instead of being guessed; a day above 12 elsewhere in
the column settles it, otherwise supply `date_order`. A column that mixes
formats is `mixed_date_formats`; other bad values give `unparseable_dates`
(empty cells count as bad). Both report the number of bad values and the first
five. Values with a UTC offset (`Z`, `+02:00`) are timezone-aware; naive values
keep the supplied `timezone`. A column mixing aware and naive values is rejected.

**Numbers** (`numbers.py`) accept thousand separators (`1,234.5`, `1.234,5`,
`1 234,5`, `1'234.5`) and decimal commas. The decimal separator is decided per
column; if the only evidence is ambiguous (`1,234`), `,` is read as a thousands
separator and `parsing.<role>.ambiguous_separator` is `true` until
`decimal_separator` is given. Empty cells and the tokens `NA`, `N/A`, `NaN`,
`null`, `none`, `-`, `--` count as missing, not as failures.

Two thresholds apply to the share of non-empty cells that must convert:

| Column | Setting | Default |
| --- | --- | --- |
| target | `DATASET_MIN_TARGET_NUMERIC_SHARE` | 0.99 |
| each regressor | `DATASET_MIN_NUMERIC_SHARE` | 0.95 |

The target bar is stricter because losing the values being forecast is worse than
losing a regressor value. Cells that fail conversion are **kept as missing**, not
dropped: `column_mapping.parsing.<role>` stores `converted`, `empty`, `failed`,
`missing` (empty + failed), the first five `failed_examples` and the first twenty
`failed_lines` (file line numbers, the header is line 1). The quality report (a later
step) lists them as a warning with the count so cleaning can decide what to do.

*Known limitation:* currency symbols (`$12.50`, `12 EUR`) and percent signs
(`45%`) are not parsed; such cells count as failures. Strip them before upload.

**Frequency** (`frequency.py`, pandas) is detected every time a mapping is saved, from
the parsed date column, and stored in `column_mapping.parsing.frequency` and
`Dataset.detected_frequency`. Each `series_id` value is judged on its own distinct,
sorted timestamps:

| Result | Meaning |
| --- | --- |
| `1min`, `15min`, `hourly`, `6h`, `daily`, `weekly`, `14D`, ... | A fixed step; most gaps equal it and the rest are multiples |
| `monthly`, `quarterly`, `yearly` | Calendar steps on a shared day of month (or month ends) |
| `irregular` | The spacing fits neither rule, or fewer than half the periods are present |
| `mixed` | The series disagree (`by_series` lists the first ten) |
| `unknown` | Fewer than three distinct timestamps in every series |

The stored object also holds `regular`, `consistent`, `series_count`, `observations`,
`duplicates` (repeated timestamps within a series, never used as a period),
`missing_periods` (multiples of the step that are absent) and the first five `gaps`
(`after`, `missing`, plus `series` when there are several). Aware timestamps are
compared in UTC, naive ones as wall-clock time. An irregular or mixed result does not
reject the mapping; the quality report and cleaning decide what to do.

Saving a mapping resets the dataset to `uploaded`, recomputes `detected_frequency`
and writes a `dataset.mapping` audit event with the roles before and after.
The mapping is read synchronously from the stored file, so a very large file
makes the request slower; a ragged CSV (rows with differing field counts) is
already refused at upload.

## Storage

`MEDIA_ROOT` defaults to `backend/media` locally and `/app/media` in Docker,
where a named volume (`media_data`) shares it between the `api` and `worker`
containers so a Celery task (added in a later step) can read what the API
wrote. Override with the `MEDIA_ROOT` env var in production.
