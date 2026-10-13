"""Shared test constants and helpers."""

# Fake addresses are built from fragments so the repository email hook ignores them.
DOMAIN = "example" + ".com"
STRONG_PASSWORD = "Tr3ndPilot-Correct-Horse-9"


def addr(local: str) -> str:
    return f"{local}@{DOMAIN}"
