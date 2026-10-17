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
| `status` | `uploaded` -> `validating` -> `validated` or `failed` (see Quality report). Saving a mapping always returns it to `uploaded`. |
| `row_count` | Data rows, excluding the header. |
| `upload_report` | Facts found at upload: `delimiter` and `ragged` (`count`, `short`, `long`, first 10 `lines`). |
| `column_mapping`, `detected_frequency` | Set by the mapping endpoint (column roles, parse results, frequency). |
| `quality_report`, `validated_at`, `validation_error` | Set by the validation task: the report (null until validated, kept when validation failed on error findings), when it finished, and a readable failure reason. |

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
| `datasets/{id}/validate/` | POST | Owner/Analyst | Queue the quality report; `202` with status `validating` |

A non-member gets `404`; a Viewer gets `403` on upload. `Dataset` is registered
in `backend/tests/isolation.py`.

## Upload validation

Before anything is stored, the uploaded file must have a `.csv` extension, be
non-empty, be at or under `DATASET_MAX_UPLOAD_BYTES` (default 20 MB), decode as
UTF-8 (BOM-aware) text, use a comma, semicolon or tab delimiter
(`apps/datasets/validation.py` picks the one that gives most rows the same field
count), have at least one data row under its header, and have no more than
`DATASET_MAX_ROWS` rows (default 500,000). Any failure is a uniform `400` with the
reason in `error.details.file`.

**Ragged rows.** A row whose field count differs from the header is *ragged*. Short
rows are padded with empty cells and long rows are truncated when the file is read, so
a truncated last line no longer sinks an upload. Up to `DATASET_MAX_RAGGED_SHARE` of the
rows (default 0.01 = 1%, and always at least one row) may be ragged; beyond that the
upload is a `400` naming the count and the first lines, because a file that far out of
shape is more likely the wrong delimiter or a broken export. Entirely blank lines are not
counted as ragged and are not data rows: `row_count` excludes them and
`upload_report.blank_lines` counts them (the quality report shows an info item). The
ragged count, short/long split and the first ten line numbers are stored in
`upload_report.ragged`.

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
makes the request slower.

Files are read by `apps/datasets/columns.py` in chunks of `DATASET_READ_CHUNK_ROWS`
rows (default 50,000) with the stdlib `csv` module and the dialect chosen at upload,
so the mapping endpoint and the quality report see exactly the same cells. Blank lines
are skipped, short rows padded, long rows truncated, and every row keeps the file line
it ended on (header = line 1), which is what `failed_lines` reports.

## Storage

`MEDIA_ROOT` defaults to `backend/media` locally and `/app/media` in Docker,
where a named volume (`media_data`) shares it between the `api` and `worker`
containers so a Celery task (added in a later step) can read what the API
wrote. Override with the `MEDIA_ROOT` env var in production.

## Quality report

`POST datasets/{id}/validate/` builds a stored, versioned report in a Celery task
(`apps/datasets/tasks.py`, logic in `services.run_validation` and `quality.py`). The
request returns `202` with the dataset in status `validating`; poll `GET datasets/{id}/`
until `status` is `validated` or `failed`. The detail body then carries `quality_report`,
`validated_at` and `validation_error`.

| Situation | Result |
| --- | --- |
| No saved mapping | `409`, code `no_mapping` |
| Already validating | `409`, code `already_validating` |
| Viewer / non-member / anonymous | `403` / `404` / `401` |
| Mapping saved (PUT/PATCH) | status back to `uploaded`, report, `validated_at` and `validation_error` cleared; a run still in flight is orphaned and its result discarded |

**Status rule.** `validated` whenever the task finishes without an error-severity
finding, even with warnings. `failed` when the task crashes, the file is missing or
unreadable, the time limit is hit, or the report holds an `error` finding (every series
below `DATASET_MIN_OBSERVATIONS_ERROR`, or a target with no numeric value). The reason is
stored in `validation_error` in plain words; crashes are logged with their traceback but
the stored text never includes it. A report built before an error finding is kept.

**Concurrency and retries.** The status change to `validating` happens under a row lock
(`select_for_update`), so two simultaneous requests cannot both start a run. Each run has
a token (`validation_run`); the task only writes if the dataset is still validating with
that token, so a stale or duplicated delivery is a no-op (`skipped`) and re-validating
replaces the report. The task acknowledges late and is rejected on worker loss, so a dead
worker's message is redelivered. A dataset stuck in `validating` longer than
`DATASET_VALIDATION_STALE_SECONDS` may be validated again. The task is queued with
`transaction.on_commit`, so a worker never sees a half-written state.

| Setting | Default | Meaning |
| --- | --- | --- |
| `DATASET_MIN_OBSERVATIONS_ERROR` | 10 | Series with fewer usable target values are "too short" |
| `DATASET_MIN_OBSERVATIONS_WARN` | 50 | Series below this are "short" (warning) |
| `DATASET_READ_CHUNK_ROWS` | 50000 | Rows per chunk when reading the file |
| `DATASET_VALIDATION_SOFT_TIME_LIMIT` / `..._TIME_LIMIT` | 300 / 330 s | Clean failure, then kill |
| `DATASET_VALIDATION_STALE_SECONDS` | 900 | After this a lost run may be replaced |

**Parsing.** The report reads the file with the same chunked reader as the mapping
endpoint and reuses its rules: the stored date format, the decimal separator stored per
column, `parse_number`, and the per-series frequency analysis. A test proves the counts
(empty, failed, failed lines, duplicates, gaps, frequency) equal what the mapping stored.
Nothing is cleaned: outliers, gaps and missing values are only counted.

### Report schema (`schema_version` 1)

Top level: `schema_version`, `severity` (`ok` when there are no findings, otherwise the
highest finding severity), `summary` (`info` / `warning` / `error` counts), `overview`,
`columns`, `findings`, `series`. The content is deterministic (same file and mapping give
the same report, regardless of chunk size); the PostgreSQL JSON column does not preserve
key order, so do not rely on it.

| `overview` field | Meaning |
| --- | --- |
| `rows`, `columns` | Data rows read (blank lines excluded) and header width |
| `series` | Number of series (1 without `series_id`) |
| `date_range` | `start`, `end` (ISO; UTC for aware dates) |
| `frequency`, `frequencies` | Dataset-level label and the count of series per label |
| `target`, `series_id`, `regressors` | The mapped columns |

`columns[]`: `name`, `role` (`date`, `series_id`, `target`, `regressor`), `missing`
(empty + failed conversion), `empty`, `failed`, `missing_share`.

Every `findings[]` entry has `code`, `severity`, `message`, `counts` (numbers, always
over all series) and `sample` (at most 10 entries, or 5 gaps). Errors first, then
warnings, then info.

| Code | Severity | When | `counts` |
| --- | --- | --- | --- |
| `target_not_numeric` | error | no target cell converts | `rows`, `empty`, `failed` |
| `series_too_short` | error if every series is, else warning | fewer than `..._ERROR` usable target values | `series`, `of`, `minimum` |
| `series_short` | warning | between the two limits | `series`, `minimum` |
| `under_two_seasons` | info | fewer than two cycles for the frequency (24 h, 7 daily, 52 weekly, 12 monthly, 4 quarterly; none for yearly and `nD`) and at least `..._ERROR` values | `series` |
| `missing_target` | warning | empty or non-numeric target cells | `missing`, `empty`, `failed` |
| `failed_numeric_conversion` | warning | target/regressor cells that failed conversion (kept as missing); sample has the first 20 file lines per column | `cells`, `columns` |
| `missing_regressors` | info | empty or failed regressor cells | `cells`, `columns` |
| `missing_series_id` | warning | empty series ids (grouped as one series) | `rows` |
| `ragged_rows` | warning | from `upload_report` | `rows`, `short`, `long` |
| `blank_lines` | info | from `upload_report` | `lines` |
| `duplicate_timestamps` | warning | a timestamp repeated within a series | `duplicates`, `series` |
| `date_gaps` | warning | missing periods of the detected frequency | `missing_periods`, `series`, `longest_gap` |
| `irregular_frequency` | warning | series with no regular step | `series` |
| `mixed_frequency` | warning | series disagree | `frequencies` |
| `outliers_iqr` | info | outside 1.5 x IQR of the quartiles | `values`, `series` |
| `outliers_robust_z` | info | robust z-score `0.6745 (x - median) / MAD` above 3.5 | `values`, `series` |
| `constant_series` | warning | one value in every row | `series` |
| `near_constant_series` | warning | one value in at least 95% of rows (and at least `..._ERROR` values) | `series` |
| `unusual_negatives` | warning | negatives although at least 95% of the target is non-negative | `values`, `observed` |
| `series_summaries_truncated` | info | more than 50 series | `series`, `listed` |

Outlier rules run per series on non-missing values, need at least 8 values, and skip a
series whose IQR (or MAD) is zero because they have no spread to measure against.
Outliers are never removed. Series ids are matched as written in the file (no trimming).

`series`: `total`, `listed`, `truncated`, `order` (`worst first`), `aggregate`
(`with_errors`, `with_warnings`, `clean`, over all series) and `items` (at most 50,
worst first: error, then warning, then info; ties by number of flags and name). Each item:
`series` (null without `series_id`), `severity`, `rows`, `observations` (non-missing
target), `missing_target`, `first`, `last`, `frequency`, `duplicate_timestamps`,
`missing_periods`, `longest_gap`, `outliers_iqr`, `outliers_robust_z`, `flags`.

Every validation writes `dataset.validate` audit events: `started` (actor = requester) and
`completed` or `failed` (no actor; `status`, `severity`, `reason`).
