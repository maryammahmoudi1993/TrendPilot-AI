from apps.core.tasks import ping


def test_ping_task_runs_eagerly():
    result = ping.delay()
    assert result.get() == "pong"


def test_celery_app_is_configured_from_django_settings():
    from config.celery import app

    assert app.conf.task_always_eager is True
