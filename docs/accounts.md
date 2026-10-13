# Accounts and the user model

`AUTH_USER_MODEL` is `accounts.User` (app `apps.accounts`):

- UUID primary key, `email` is the login field, there is no username.
- Email is stripped and lowercased on every save, and is unique both as a plain
  column and through a case-insensitive `lower(email)` database constraint.
- Passwords are hashed with Django's configured hashers; `create_user` without a
  password stores an unusable one.

## Recreate the development database (one time)

Phase 1 replaced Django's default user with this model and the migrations were
regenerated from scratch, so a database created in Phase 0 cannot be upgraded.
Throw it away and migrate again:

```bash
docker compose down -v          # removes the pgdata and redisdata volumes
docker compose up -d --build    # the api container runs `migrate` on start
```

Without Docker, drop and recreate the PostgreSQL database, then run
`python manage.py migrate`. Nothing in Phase 0 stored user data.

## Auth API (`/api/auth/`)

| Endpoint | Method | Auth | Purpose |
| --- | --- | --- | --- |
| `register/` | POST | none, throttled | Create an account; returns user + access/refresh tokens |
| `login/` | POST | none, throttled | Email + password -> access/refresh tokens |
| `refresh/` | POST | none | Rotate the refresh token (old one is blacklisted) |
| `logout/` | POST | Bearer | Blacklist the caller's refresh token |
| `me/` | GET, PATCH | Bearer | Read or update the profile (`full_name`; email is read-only) |
| `change-password/` | POST | Bearer | Needs the current password; blacklists all refresh tokens, returns a fresh pair |

- Access tokens live 10 minutes, refresh tokens 7 days (`JWT_ACCESS_MINUTES`,
  `JWT_REFRESH_DAYS`). Refresh tokens rotate on every use.
- Login failures (unknown email, wrong password, inactive user) return the same
  `401` body, so the API does not reveal whether an email is registered.
- Throttling is per client IP (`THROTTLE_LOGIN_RATE`, `THROTTLE_REGISTER_RATE`)
  and its counters live in the Redis cache.
- Password rules come from Django's validators (length, common, numeric-only,
  similarity to the email/name).

## Error format

Every error response is `{"error": {"code", "message", "details?"}}`. Validation
errors put the per-field messages in `details`; throttled requests (`429`) carry
`details.retry_after` in seconds.

## Audit log and API docs

- Security-relevant actions write an append-only `AuditEvent` in the same transaction
  as the action: login, logout, password change, workspace create/rename/delete and
  every membership change (add, role change, remove, leave). Refused changes write
  nothing. Owners read their workspace's log at `GET /api/workspaces/{id}/audit/`
  (filter with `?action=member.add`); account events have no workspace and are not
  shown there. Deleting a workspace detaches its events (the deletion event keeps the
  workspace id and name in its metadata).
- Interactive API docs: `/api/docs/` (Swagger UI); schema: `/api/schema/`.
