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
| `column_mapping`, `detected_frequency` | Set in later steps (column mapping, frequency detection). |

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

A non-member gets `404`; a Viewer gets `403` on upload. `Dataset` is registered
in `backend/tests/isolation.py`.

## Upload validation

Before anything is stored, the uploaded file must have a `.csv` extension, be
non-empty, be at or under `DATASET_MAX_UPLOAD_BYTES` (default 20 MB), decode as
UTF-8 (BOM-aware) text, use a comma, semicolon or tab delimiter
(`apps/datasets/validation.py` sniffs it), have at least one data row under its
header, and have no more than `DATASET_MAX_ROWS` rows (default 500,000). Any
failure is a uniform `400` with the reason in `error.details.file`.

## Storage

`MEDIA_ROOT` defaults to `backend/media` locally and `/app/media` in Docker,
where a named volume (`media_data`) shares it between the `api` and `worker`
containers so a Celery task (added in a later step) can read what the API
wrote. Override with the `MEDIA_ROOT` env var in production.
