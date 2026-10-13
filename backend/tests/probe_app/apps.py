from django.apps import AppConfig


class ProbeConfig(AppConfig):
    """Test-only app: proves the workspace scoping blocks. Never installed in production."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "tests.probe_app"
    label = "probe"
