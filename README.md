# Ryan

Ryan is a Python modular monolith scaffold for the autonomous agent business OS
described in `docs/`.

## Local Commands

Run tests:

```bash
uv run pytest
```

Run the API locally:

```bash
uv run uvicorn ryan.app:app --reload
```

Run migrations:

```bash
uv run alembic upgrade head
```

The default environment is `sandbox`, with local SQLite at
`sqlite:///./ryan.sqlite3`.
