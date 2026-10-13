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
