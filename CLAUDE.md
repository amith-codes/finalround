# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

DispatchGrid is an electrician-only workforce scheduling and recovery engine: a FastAPI + SQLite backend (`backend/`)
and a React + Vite frontend (`frontend/`). All domain data (skills, jobs, scenarios) must stay in electrician
operations. README.md holds the full algorithm and objective description, complexity, and API list.

## Commands

Backend (run from `backend/`, using the venv at `backend/venv`):

```bash
venv\Scripts\activate                        # Windows; bash: source venv/Scripts/activate
pip install -r requirements.txt
python -m app.seed --schedule                # DROPS and recreates dispatchgrid.db, loads 20 electricians/100 jobs, runs a first schedule
uvicorn app.main:app --reload                # http://127.0.0.1:8000, Swagger at /docs
pytest -v                                    # full suite
pytest tests/test_engine.py -v               # engine only (no DB, fast)
pytest tests/test_scenarios.py::test_scenario1_skilled_electrician_unavailable -v
python -m app.scenarios run all              # demo disruptions against a *running* API
```

Frontend (from `frontend/`): `npm install`, `npm run dev` (port 5173, proxies `/api` to :8000), `npm run build`.

Login is `dispatcher` / `dispatch123` (created on startup). Set `DISPATCHGRID_AUTH_DISABLED=1` to bypass JWT.
Other settings are environment variables in `app/config.py` (for example `DISPATCHGRID_DB_URL`).

## Architecture

The request flow is: routers → services → engine.

- `app/scheduling/` is a **pure engine with no SQLAlchemy**. It takes a `Problem` (types.py) and returns a `SolveResult`.
  - `routes.py::Evaluator` walks an ordered job list on one `(electrician_id, shift_index)` route, enforcing every hard
    constraint, and memoises results.
  - `engine.py::Scheduler` runs: keep pass (replays previous assignments) → cheapest-insertion construction →
    improvement rounds (retry, ejection, relocation; a move is applied only on a strict objective decrease).
  - `diagnosis.py` classifies unassigned jobs as `unassignable` or `currently_infeasible`, with reason codes and suggestions.
  - Keep it deterministic: iteration order and tie-breaks use IDs, and tests compare two runs for equality.
- `services/problem_builder.py` is the only bridge from DB to engine.
  - Weekly `Shift` rows expand into concrete intervals.
  - In-progress jobs, and jobs completed today, become `Anchor`s (electrician busy until X, then departs from that site).
  - Active assignments of schedulable jobs become `prior` (used for the keep pass and change penalties).
- `services/scheduling_service.py::execute_run` is the single place runs happen. The caller must hold `scheduler_lock()`.
  - It commits a `running` audit row, then solves and saves in one transaction.
  - On error it rolls back, marks the run `failed`, and raises `ApiError(500, "SCHEDULING_FAILED")`.
  - It writes `ScheduleChange` rows by diffing `problem.prior` against the new visits.
- Disruption routers (`routers/disruptions.py::_recover`):
  1. snapshot the schedule;
  2. apply the event and **commit it**;
  3. call `execute_run` (incremental mode), all under the lock.

  Extra `removed` change rows are passed through `extra_changes`.
- `services/idempotency.py::idempotent()` wraps POST handlers that accept an `Idempotency-Key`. The handler must commit
  its own work and return JSON-able data.

## Conventions and gotchas

- All datetimes are **naive local time**. Schemas strip tzinfo (`NaiveTimes`); the frontend sends `YYYY-MM-DDTHH:MM:SS` without a zone.
  Endpoints take an optional `as_of` planning clock. Tests pin it to `tests/conftest.py::NOW` (Fri 2026-10-30 07:00).
- Seed data is relative to the current date (jobs on D1–D3 = tomorrow onwards). `build(db, now=...)` accepts a fixed clock.
  Tests and `seed.py` docstrings depend on the hand-crafted cases at the top of `build()`
  (EL-001 is the only `high_voltage` electrician, the OUT-zone edge cases, and so on); keep them intact when changing seed data.
- Errors: raise `services.errors.ApiError(status, CODE, message, details)`. Never return ad-hoc error dicts;
  the handlers in `main.py` produce `{"error": {...}}`.
- Job status changes go through `job_service.transition()`; only the scheduler sets `assigned`/`unassigned`.
  Jobs and electricians are never hard-deleted (DELETE cancels or deactivates).
- Exactly one `Assignment.is_active` row per scheduled job. Older rows are history; flip `is_active` instead of deleting.
- Responses are plain dicts from `services/serializers.py`, not Pydantic response models.
- Objective weights live in `scheduling/types.py::Weights`, and the hard-SLA priorities in `routes.py::HARD_SLA_PRIORITIES`.
  Update the README's objective section when changing either.
- Constraint checks for tests: `tests/helpers.py::assert_valid` (engine output) and `test_scenarios.py::assert_schedule_valid` (persisted schedule).
- No migrations: the schema is `Base.metadata.create_all` from `app/models/__init__.py`. After a model change, re-run `python -m app.seed`.
