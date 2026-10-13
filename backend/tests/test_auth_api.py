from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from tests.helpers import STRONG_PASSWORD, addr

User = get_user_model()
pytestmark = pytest.mark.django_db

REGISTER = "/api/auth/register/"
LOGIN = "/api/auth/login/"
REFRESH = "/api/auth/refresh/"
LOGOUT = "/api/auth/logout/"
ME = "/api/auth/me/"
CHANGE_PASSWORD = "/api/auth/change-password/"
NEW_PASSWORD = "Another-Str0ng-Passphrase!"


@pytest.fixture
def user():
    return User.objects.create_user(addr("ada"), STRONG_PASSWORD, full_name="Ada")


def login(api, email=None, password=STRONG_PASSWORD):
    return api.post(LOGIN, {"email": email or addr("ada"), "password": password}, format="json")


def bearer(api, token):
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")


def assert_error(response, status, code=None):
    assert response.status_code == status, response.content
    error = response.json()["error"]
    assert set(error) >= {"code", "message"}
    if code:
        assert error["code"] == code
    return error


# --- register ---------------------------------------------------------------


def test_register_happy_path(api):
    response = api.post(
        REGISTER,
        {"email": addr("New.User"), "password": STRONG_PASSWORD, "full_name": "New"},
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == addr("new.user")
    assert "password" not in body["user"]
    assert body["access"] and body["refresh"]
    assert User.objects.get(email=addr("new.user")).check_password(STRONG_PASSWORD)


def test_register_duplicate_email_rejected_case_insensitively(api, user):
    response = api.post(
        REGISTER, {"email": addr("ADA"), "password": STRONG_PASSWORD}, format="json"
    )
    error = assert_error(response, 400, "validation_error")
    assert "email" in error["details"]
    assert User.objects.count() == 1


@pytest.mark.parametrize("password", ["short1A", "password", "12345678901", "trendpilot-new-user"])
def test_register_weak_password_rejected(api, password):
    response = api.post(
        REGISTER, {"email": addr("trendpilot-new-user"), "password": password}, format="json"
    )
    error = assert_error(response, 400, "validation_error")
    assert "password" in error["details"]
    assert not User.objects.exists()


def test_register_requires_valid_email(api):
    response = api.post(REGISTER, {"email": "nope", "password": STRONG_PASSWORD}, format="json")
    assert "email" in assert_error(response, 400)["details"]


def test_register_is_throttled(api):
    for i in range(3):
        body = {"email": addr(f"u{i}"), "password": STRONG_PASSWORD}
        assert api.post(REGISTER, body, format="json").status_code == 201
    body = {"email": addr("u9"), "password": STRONG_PASSWORD}
    error = assert_error(api.post(REGISTER, body, format="json"), 429, "throttled")
    assert error["details"]["retry_after"] > 0


# --- login ------------------------------------------------------------------


def test_login_happy_path_and_token_claims(api, user):
    response = login(api, email=addr("ADA"))
    assert response.status_code == 200
    body = response.json()
    assert AccessToken(body["access"])["user_id"] == str(user.pk)
    assert RefreshToken(body["refresh"])["user_id"] == str(user.pk)
    user.refresh_from_db()
    assert user.last_login is not None


def test_login_errors_do_not_reveal_whether_email_exists(api, user):
    wrong_password = login(api, password="not-the-password")
    unknown_email = login(api, email=addr("nobody"))
    inactive = User.objects.create_user(addr("off"), STRONG_PASSWORD, is_active=False)
    inactive_resp = login(api, email=inactive.email)
    for response in (wrong_password, unknown_email, inactive_resp):
        assert_error(response, 401)
    assert wrong_password.json() == unknown_email.json() == inactive_resp.json()


def test_login_missing_fields(api):
    assert_error(api.post(LOGIN, {}, format="json"), 400, "validation_error")


def test_login_is_throttled(api, user):
    for _ in range(5):
        assert login(api, password="bad").status_code == 401
    error = assert_error(login(api, password="bad"), 429, "throttled")
    assert "retry_after" in error["details"]
    # even the right password is refused while throttled
    assert login(api).status_code == 429


# --- refresh / expiry / blacklist --------------------------------------------


def test_refresh_rotates_and_blacklists_old_token(api, user):
    tokens = login(api).json()
    first = api.post(REFRESH, {"refresh": tokens["refresh"]}, format="json")
    assert first.status_code == 200
    assert first.json()["refresh"] != tokens["refresh"]
    reuse = api.post(REFRESH, {"refresh": tokens["refresh"]}, format="json")
    assert_error(reuse, 401)


def test_refresh_with_garbage_token(api):
    assert_error(api.post(REFRESH, {"refresh": "abc"}, format="json"), 401)


def test_expired_access_token_rejected(api, user):
    token = AccessToken.for_user(user)
    token.set_exp(lifetime=-timedelta(minutes=1))
    bearer(api, str(token))
    assert_error(api.get(ME), 401)


def test_expired_refresh_token_rejected(api, user):
    token = RefreshToken.for_user(user)
    token.set_exp(lifetime=-timedelta(minutes=1))
    assert_error(api.post(REFRESH, {"refresh": str(token)}, format="json"), 401)


def test_access_token_is_short_lived(user):
    token = AccessToken.for_user(user)
    assert token["exp"] - token["iat"] <= 15 * 60


# --- logout -------------------------------------------------------------------


def test_logout_blacklists_refresh_token(api, user):
    tokens = login(api).json()
    bearer(api, tokens["access"])
    assert api.post(LOGOUT, {"refresh": tokens["refresh"]}, format="json").status_code == 204
    api.credentials()
    assert_error(api.post(REFRESH, {"refresh": tokens["refresh"]}, format="json"), 401)


def test_logout_twice_fails_second_time(api, user):
    tokens = login(api).json()
    bearer(api, tokens["access"])
    api.post(LOGOUT, {"refresh": tokens["refresh"]}, format="json")
    response = api.post(LOGOUT, {"refresh": tokens["refresh"]}, format="json")
    assert_error(response, 400, "validation_error")


def test_logout_requires_authentication(api, user):
    tokens = login(api).json()
    assert_error(api.post(LOGOUT, {"refresh": tokens["refresh"]}, format="json"), 401)


def test_logout_rejects_a_refresh_token_owned_by_someone_else(api, user):
    other = User.objects.create_user(addr("grace"), STRONG_PASSWORD)
    other_refresh = str(RefreshToken.for_user(other))
    bearer(api, str(AccessToken.for_user(user)))
    response = api.post(LOGOUT, {"refresh": other_refresh}, format="json")
    assert_error(response, 400, "validation_error")
    api.credentials()
    assert api.post(REFRESH, {"refresh": other_refresh}, format="json").status_code == 200


# --- me ------------------------------------------------------------------------


def test_me_requires_authentication(api):
    assert_error(api.get(ME), 401, "not_authenticated")


def test_me_get_and_patch(api, user):
    bearer(api, str(AccessToken.for_user(user)))
    assert api.get(ME).json()["email"] == addr("ada")
    response = api.patch(ME, {"full_name": "Ada L.", "email": addr("evil")}, format="json")
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.full_name == "Ada L."
    assert user.email == addr("ada")  # email is read-only


def test_me_does_not_allow_put_or_delete(api, user):
    bearer(api, str(AccessToken.for_user(user)))
    assert_error(api.put(ME, {"full_name": "x"}, format="json"), 405)
    assert_error(api.delete(ME), 405)


def test_inactive_user_token_rejected(api, user):
    token = str(AccessToken.for_user(user))
    user.is_active = False
    user.save()
    bearer(api, token)
    assert_error(api.get(ME), 401)


# --- change password --------------------------------------------------------------


def test_change_password_happy_path(api, user):
    tokens = login(api).json()
    bearer(api, tokens["access"])
    response = api.post(
        CHANGE_PASSWORD,
        {"old_password": STRONG_PASSWORD, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["access"]
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    # the old refresh token no longer works, the newly issued one does
    api.credentials()
    assert_error(api.post(REFRESH, {"refresh": tokens["refresh"]}, format="json"), 401)
    new_refresh = {"refresh": response.json()["refresh"]}
    assert api.post(REFRESH, new_refresh, format="json").status_code == 200


def test_change_password_wrong_old_password(api, user):
    bearer(api, str(AccessToken.for_user(user)))
    response = api.post(
        CHANGE_PASSWORD, {"old_password": "wrong", "new_password": NEW_PASSWORD}, format="json"
    )
    assert "old_password" in assert_error(response, 400)["details"]


def test_change_password_weak_new_password(api, user):
    bearer(api, str(AccessToken.for_user(user)))
    response = api.post(
        CHANGE_PASSWORD,
        {"old_password": STRONG_PASSWORD, "new_password": "12345678"},
        format="json",
    )
    assert "new_password" in assert_error(response, 400)["details"]
    user.refresh_from_db()
    assert user.check_password(STRONG_PASSWORD)


def test_change_password_requires_authentication(api):
    assert_error(api.post(CHANGE_PASSWORD, {}, format="json"), 401)


# --- error format -------------------------------------------------------------------


def test_unknown_route_is_404(api):
    assert api.get("/api/auth/nope/").status_code == 404
