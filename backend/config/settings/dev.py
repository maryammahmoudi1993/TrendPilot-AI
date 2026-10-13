from .base import *  # noqa: F403

DEV_SECRET_KEY = "dev-insecure-secret-key-do-not-use-outside-local-development"

DEBUG = True
SECRET_KEY = SECRET_KEY or DEV_SECRET_KEY  # noqa: F405
ALLOWED_HOSTS = ["*"]
