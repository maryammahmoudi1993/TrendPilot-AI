from .base import *  # noqa: F403

DEBUG = True
SECRET_KEY = SECRET_KEY or "dev-insecure-secret-key"  # noqa: F405
ALLOWED_HOSTS = ["*"]
