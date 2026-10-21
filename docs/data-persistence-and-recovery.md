# Data persistence and recovery

- **Database:** the source of truth. Back up PostgreSQL with `pg_dump` (hosted: use the provider's snapshots). For local SQLite, copy `data/zuvi.sqlite3` while the server is stopped.
- **Media:** `MEDIA_ROOT` locally; S3-compatible storage hosted (`MEDIA_STORAGE_BACKEND=s3`). Back up media with the database — rows reference files by name.
- **Sessions:** stored in the database, so they survive process restarts (verified) and deploys. Restoring an old database restores its sessions; rotate `DJANGO_SECRET_KEY` only intentionally.
- **Never reset:** nothing in the app or these docs drops or recreates the database. Migrations are additive. Test runs use separate throwaway databases.
- **Imports:** a failed or rolled-back commit leaves no products; staged upload files are deleted after commit. The batch row keeps counts, summary and errors for audit.
- **Images:** removing a photo or product keeps the files, so a restored database never points at missing media. Reclaim space with `cleanup_product_media` (dry run first).

## Recovery checklist

1. Stop writers (scale web to 0 or maintenance mode).
2. Restore the database snapshot; restore the media bucket/folder from the same time.
3. `python manage.py migrate` (no-op if schema matches), then `python manage.py check`.
4. Start the app; `GET /health/ready/` should return `ok`.
