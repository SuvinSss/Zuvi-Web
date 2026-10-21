# Performance testing

Tool: **Locust** (`backend/loadtests/locustfile.py`). Scenarios: public catalogue (pages, search, home) and authenticated management API (list/page, search, filter, detail, meta, login).

## How to run

```bash
cd backend
createdb zuvi_load                       # throwaway database — never a real one
DATABASE_URL=postgres://…/zuvi_load python manage.py migrate
DATABASE_URL=… LOAD_PRODUCTS=3000 python manage.py shell < scripts/load_seed.py
API_THROTTLE_LOGIN=100000/min API_THROTTLE_USER=1000000/min PORT=8001 WEB_CONCURRENCY=3 \
  DATABASE_URL=… gunicorn config.wsgi -c gunicorn.conf.py
locust -f loadtests/locustfile.py --headless -u 20 -r 5 -t 60s --host http://127.0.0.1:8001 --csv loadtests/results/run
```
Throttles are raised **only on the test server** so rate limiting does not hide server capacity.

## Measured result (single run, 2026-10-21)

Environment: 2 vCPU container running Gunicorn (3 sync workers), PostgreSQL 16 and Locust *on the same machine*; DEBUG on; 3,000 products; 20 users (15 shoppers, 5 managers), 60 s, think time 0.5–2 s.

| Metric | Result |
| --- | --- |
| Requests / failures | 872 / 0 |
| Throughput | 14.5 req/s (bounded by think time, not saturation) |
| Latency, all requests | p50 130 ms · p95 370 ms · p99 620 ms · max 713 ms |
| Public `/products/?page=N` | p50 130 ms · p95 330 ms |
| Public `/products/?q=` | p50 240 ms · p95 490 ms |
| API list `?page=N` | p50 68 ms · p95 240 ms |
| API search `?q=` | p50 62 ms · p95 180 ms |
| DB queries per API list page | 6, constant for page_size 20 and 100 (no N+1) |

**Interpretation limits:** this is a small, shared-hardware smoke/load run, not a capacity test. It did **not** find a saturation point, was not run against production-like infrastructure or S3 media, and did not exercise uploads or imports under load. Do not extrapolate it into user-count claims.

## Scalability notes

- The API list uses `select_related`/`prefetch_related` and fixed-size pages (max 100); list queries do not grow with page size.
- Image processing/import commits run inside the request (CPU-bound). Fine for the 5 MB / 1000-row limits; move to a queue before raising them.
- Not done: Redis/DB-backed shared cache for throttling (throttles use the default local-memory cache, so limits are per process), CDN for media, background workers.
