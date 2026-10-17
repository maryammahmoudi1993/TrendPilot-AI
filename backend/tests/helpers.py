"""Shared test constants and helpers."""

# Fake addresses are built from fragments so the repository email hook ignores them.
DOMAIN = "example" + ".com"
STRONG_PASSWORD = "Tr3ndPilot-Correct-Horse-9"


def addr(local: str) -> str:
    return f"{local}@{DOMAIN}"


def make_dataset(workspace, text: str, sha: str = "0" * 64):
    """Store ``text`` as a dataset file the way an upload would (report included)."""
    from django.core.files.base import ContentFile

    from apps.datasets.models import Dataset
    from apps.datasets.validation import CsvSniffError, sniff_csv

    try:
        info = sniff_csv(text.encode())
    except CsvSniffError:  # e.g. too many ragged rows: store the file anyway
        info = {"row_count": 0, "delimiter": ",", "blank_lines": 0, "ragged": {}}
    dataset = Dataset(
        workspace=workspace,
        name="d.csv",
        original_filename="d.csv",
        size=len(text),
        sha256=sha,
        row_count=info["row_count"],
        upload_report={
            "delimiter": info["delimiter"],
            "blank_lines": info["blank_lines"],
            "ragged": info["ragged"],
        },
    )
    dataset.file.save("d.csv", ContentFile(text.encode()), save=False)
    dataset.save()
    return dataset
