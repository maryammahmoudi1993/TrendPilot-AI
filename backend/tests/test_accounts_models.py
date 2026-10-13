import uuid

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, transaction

from tests.helpers import DOMAIN, addr

User = get_user_model()
pytestmark = pytest.mark.django_db


def test_auth_user_model_is_accounts_user():
    assert User._meta.label == "accounts.User"
    assert User.USERNAME_FIELD == "email"
    assert not hasattr(User, "username") or "username" not in {f.name for f in User._meta.fields}


def test_create_user():
    user = User.objects.create_user(addr("ada"), "s3cret-pass-phrase")
    assert isinstance(user.pk, uuid.UUID)
    assert user.email == addr("ada")
    assert user.is_active and not user.is_staff and not user.is_superuser
    assert user.check_password("s3cret-pass-phrase")


def test_create_superuser():
    admin = User.objects.create_superuser(addr("root"), "s3cret-pass-phrase")
    assert admin.is_staff and admin.is_superuser


@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
def test_superuser_flags_cannot_be_false(flag):
    with pytest.raises(ValueError):
        User.objects.create_superuser(addr("root"), "pw", **{flag: False})


def test_email_is_required():
    with pytest.raises(ValueError):
        User.objects.create_user("", "pw")


def test_password_is_hashed():
    user = User.objects.create_user(addr("ada"), "s3cret-pass-phrase")
    assert user.password != "s3cret-pass-phrase"
    assert user.password.startswith(("md5$", "pbkdf2_", "argon2", "bcrypt"))


def test_unusable_password_when_none_given():
    user = User.objects.create_user(addr("ada"))
    assert not user.has_usable_password()


def test_email_is_normalized_on_create():
    user = User.objects.create_user(f"  Ada.Lovelace@{DOMAIN.upper()} ", "pw")
    assert user.email == addr("ada.lovelace")


def test_email_is_normalized_on_save():
    user = User.objects.create_user(addr("ada"), "pw")
    user.email = addr("ADA")
    user.save()
    user.refresh_from_db()
    assert user.email == addr("ada")


def test_duplicate_email_rejected_case_insensitively():
    User.objects.create_user(addr("ada"), "pw")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(addr("ADA"), "pw")


def test_database_constraint_catches_unnormalized_duplicate():
    User.objects.create_user(addr("ada"), "pw")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.bulk_create([User(email=addr("Ada"))])


def test_authenticate_is_case_insensitive_on_email():
    User.objects.create_user(addr("ada"), "s3cret-pass-phrase")
    assert authenticate(email=addr("ADA"), password="s3cret-pass-phrase") is not None
    assert authenticate(email=addr("ada"), password="wrong") is None


def test_str_is_email():
    assert str(User(email=addr("ada"))) == addr("ada")
