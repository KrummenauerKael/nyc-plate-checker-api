# NYC Plate Checker — API

A FastAPI + PostgreSQL backend for looking up NYC parking and camera violations by
license plate, built as a companion to my client-side [NYC Plate
Checker](https://github.com/KrummenauerKael/NYCplatechecker) project. Where the
original queries NYC Open Data directly from the browser, this adds a proper backend
with a persistent cache layer, containerized with Docker.

This is an active learning project — I'm using it to build backend Python experience
(FastAPI, SQLAlchemy, Alembic) and to learn Docker. It is **not feature-complete**; see
[Status](#status) below for what's done and what isn't.

## Why a cache-aside layer, not a mirrored dataset

NYC's [Open Parking and Camera Violations dataset](https://data.cityofnewyork.us/City-Government/Open-Parking-and-Camera-Violations/nc67-uf89)
has 100M+ rows — mirroring it isn't practical or necessary for a plate-lookup tool.
Instead, this uses a **cache-aside** pattern:

1. A request for `{state}/{plate}` first checks Postgres for a cached result.
2. If a cached row exists and is less than 24 hours old (matching Open Data's own
   refresh cadence), it's served directly — no external call.
3. If missing or stale, the API fetches fresh data from NYC Open Data, normalizes and
   upserts it into Postgres, and serves the result.

This keeps the database small (only plates people actually query get stored), keeps
response times fast on repeat lookups, and avoids hammering a rate-limited public API.

## Stack

- **FastAPI** — web framework / routing
- **PostgreSQL** — data storage
- **SQLAlchemy** — ORM
- **Alembic** — schema migrations
- **Docker Compose** — local dev environment (`db` + `api` services)

## Schema

- `plates` — one row per plate+state (+type) combo queried; `fetched_at` drives the
  cache TTL.
- `violations` — one row per violation, keyed by `summons_number` (the upsert target).
  `amount_due` is refreshed on every fetch so paid/outstanding status stays current.
- `lookups` — intended as a timestamped query log per plate. **Defined but not yet
  wired up** — see Status.

## Running locally

Requires Docker Desktop.

```bash
git clone https://github.com/KrummenauerKael/nyc-plate-checker-api.git
cd nyc-plate-checker-api
docker compose up --build
```

This starts Postgres and the API together. First run only, apply the database schema:

```bash
docker compose exec api alembic upgrade head
```

Then:

```
GET http://localhost:8000/plates/{state}/{plate}
```

Example:
```
GET http://localhost:8000/plates/NY/ABC1234
```
```json
{
  "state": "NY",
  "plate": "ABC1234",
  "source": "open_data",
  "violation_count": 3
}
```

`source` is `"open_data"` on a cache miss/refresh, `"cache"` when served from Postgres
without an external call.

## Status

**Working and tested end to end** (verified against real Open Data results, confirmed
directly in Postgres via `psql`):
- Docker Compose networking (`api` ↔ `db` by service name)
- Alembic migrations creating the schema
- Cache-aside read/fetch/upsert logic in `GET /plates/{state}/{plate}`

**Not yet done:**
- `lookups` table is defined but nothing writes to it yet
- Field normalization is minimal — only `summons_number` and `amount_due` are mapped
  from Open Data today; `total_amount`, `violation_date`, and other fields (violation
  type, county, issuing agency, etc.) aren't populated yet
- No automated tests, no CI
- No pruning job for stale/unqueried plates
- Credentials are hardcoded for local dev, not yet read from environment/`.env`
- Not yet deployed (planned: Supabase for production Postgres)

## Roadmap

- [ ] Wire up `lookups` query logging
- [ ] Full field normalization from Open Data
- [ ] Test suite + GitHub Actions CI (Postgres service container)
- [ ] Env-based config, `.env` for local secrets
- [ ] Rate limiting (`slowapi` + a Socrata app token) — prerequisite before public deploy
- [ ] Pruning job for old/unqueried plates
- [ ] Deploy DB to Supabase; deploy API to AWS ECS Fargate (ECR, task definition, ALB)
- [ ] Repoint the [frontend](https://github.com/KrummenauerKael/NYCplatechecker) at this API
