# Database

- **Hosted (development/uat/production):** PostgreSQL via `DATABASE_URL`. Required.
- **Local convenience:** if `DJANGO_ENVIRONMENT=local` and `DATABASE_URL` is unset, SQLite at `SQLITE_PATH` (default `data/zuvi.sqlite3`, create the folder automatically; add `data/` to backups, not Git).
- Tests and CI run on PostgreSQL 16. The SQLite path is exercised by the API/import/pipeline tests only.

## SQLite differences (local only)

| Feature | PostgreSQL | SQLite |
| --- | --- | --- |
| Public search | exact + trigram typo tolerance | `contains` matching only |
| `/health/ready/` probe | read-only connection with timeouts | plain `SELECT 1` |
| Concurrency | row locks | database-level write lock |

## Migrations

`catalog/migrations/0013_product_image_pipeline_and_import_batch.py` is additive (new nullable/blank columns, one new table). Existing rows are untouched. Run `python manage.py makemigrations --check` in CI (already done).

## Switching

Point `DATABASE_URL` at PostgreSQL (`postgres://user:pass@host:5432/db`), run `migrate`. There is **no automatic SQLite→PostgreSQL data copy**; use a fresh database or `dumpdata`/`loaddata` after review.
