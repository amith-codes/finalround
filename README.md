# DispatchGrid – Electrician Workforce Scheduling & Recovery Engine

DispatchGrid assigns electrician service jobs to electricians automatically, optimises the schedule, recovers from
disruptions (sick electricians, urgent calls, overruns, cancellations) and explains every decision.
The domain is electrician operations only: skills such as `panel_upgrade`, `ev_charger`, `high_voltage`, service zones
across a city, recurring shifts and unavailability.

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite, react-router, axios |
| Backend | Python 3.10+ · FastAPI · SQLAlchemy 2 · Pydantic 2 |
| Storage | SQLite (WAL mode) |
| Auth | JWT bearer tokens (python-jose, bcrypt) |
| Tests | Pytest (engine unit tests + API/scenario tests) |
| API docs | Swagger UI at `/docs` |

---

## 1. Setup and running

Prerequisites: Python 3.10+, Node.js 18+ and npm.

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate            # Windows   (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
python -m app.seed --schedule    # reset DB, load seed data, run a first scheduling pass
uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000 · Swagger UI: http://127.0.0.1:8000/docs
- Login: **dispatcher / dispatch123**. In Swagger press *Authorize* and enter these credentials.
  Set `DISPATCHGRID_AUTH_DISABLED=1` to skip auth during local exploration.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend on port 8000.

### Role-based booking portal

The current project has one username/password sign-in backed by JWT; it does not contain an external SSO provider or OIDC configuration. The same sign-in screen routes users by the role stored on their server-side account.

- Sign in as the configured `dispatcher` administrator, open **Electricians**, and register each electrician with a sign-in name, initial password, skills, shifts, zones and service localities. Customers must enter the same locality name during booking for automatic locality dispatch.
- Open **Customers** to provision customer accounts. Customer, electrician and admin accounts all use the same sign-in route. Role values are assigned by the server; account forms do not accept a role.
- Customers use **Book electrician**, **Track booking status** and **Payment methods**. The existing service catalog page remains the booking page.
- If no qualified, available electrician serves the requested locality, the booking remains unassigned for admin review. Admins can assign or reassign it from the booking detail view.
- Payment methods save only a label, brand and last four digits. Card charging is not connected in this application; payment status can be updated by an admin.

New role tables are created automatically on startup. Existing SQLite records are preserved; `python -m app.seed` resets the database and should only be used when an intentional fresh sample dataset is wanted.

### Seed data

`python -m app.seed` drops and recreates the database. Add `--schedule` to also run the first scheduling pass.
Dates are relative to "now": jobs fall on the next three days (D1–D3), and some jobs are already in progress or completed today.
The dataset contains:

- 20 electricians with 14 electrical skills, 6 service zones, weekly shifts (one rotating day off each), overtime allowances,
  and 5 unavailable periods.
- 100 jobs across all priorities and statuses, including conflicting time windows and a capacity crunch
  (5 panel upgrades in the South zone competing for the same morning).
- Jobs that can never be assigned, one per reason: a skill combination nobody has, an uncovered zone, an out-of-hours window,
  the only qualified electrician on leave, an unachievable SLA, and a site nobody can reach in time.
- **EL-001 Arjun Rao**: the only high-voltage electrician, used for the "skilled electrician unavailable" scenario.

### Disruption scenarios (live demo)

With the API running:

```bash
python -m app.scenarios list
python -m app.scenarios run skilled-unavailable      # or: urgent-job, duration-change, cancel-job,
python -m app.scenarios run all                      #     early-finish, late-finish, duplicate-requests, concurrent-runs
```

All of these can also be triggered from the **Disruptions** page.

### Tests

```bash
cd backend
pytest -v                                  # whole suite (~20 s)
pytest tests/test_engine.py -v             # engine only, no database
pytest tests/test_scenarios.py::test_scenario6_concurrent_scheduling_requests -v
```

---

## 2. Architecture

```text
 React (Vite)  ──/api──►  FastAPI routers ──► services ──► scheduling engine (pure Python)
  pages/                    routers/*.py        job_service         scheduling/engine.py
  components/               (validation via     electrician_service scheduling/routes.py
  services/api.js            schemas/)          scheduling_service  scheduling/diagnosis.py
                                                 problem_builder ◄── SQLAlchemy models ──► SQLite
```

- **`app/scheduling/`** contains the engine and has no database code. It takes a `Problem`
  (jobs, electricians with concrete shift intervals, unavailability, the previous assignments, the planning clock)
  and returns a `SolveResult` (visits, unassigned jobs with reasons, objective breakdown, explanations).
  This makes the algorithm unit-testable with hand-built data (`tests/test_engine.py`).
- **`services/problem_builder.py`** converts database rows into a `Problem`. Weekly shifts become concrete intervals across the
  planning horizon. In-progress jobs and jobs completed today become *anchors*: the electrician is busy until then and
  sets off from that job's site afterwards.
- **`services/scheduling_service.py`** owns a scheduling run: locking, the audit row, solving, saving the results,
  computing the diff against the previous schedule, and handling failures.
- **Routers** stay thin. Disruption endpoints record the event and then run an incremental recovery under the same lock.
- **Planning clock.** Every scheduling, disruption and dashboard endpoint accepts an optional `as_of` timestamp,
  so demos and tests are deterministic. All times are naive local time of the dispatch centre.

### Database schema

| Table | Purpose |
|---|---|
| `electricians` | name, home base (lat/lon), `max_overtime_minutes`, `active` |
| `skills`, `electrician_skills` | skill catalogue and the many-to-many link |
| `service_zones`, `electrician_zones` | zones (with centre point) and zone coverage |
| `shifts` | recurring weekly working hours (`day_of_week`, `start_time`, `end_time`) |
| `unavailable_periods` | absolute datetime ranges an electrician cannot work |
| `jobs`, `job_skills` | job details, window, SLA, status, latest `feasibility` + `unassigned_reasons` (JSON) |
| `assignments` | job → electrician with start/end/travel/explanation; exactly one `is_active` row per scheduled job, older rows kept as history |
| `scheduling_runs` | the audit record of each run (see below) |
| `schedule_changes` | per-job diff for each run: assigned / unassigned / reassigned / retimed / removed, with a reason |
| `idempotency_records` | stored responses keyed by `(Idempotency-Key, endpoint)` |
| `users` | dispatcher accounts for JWT login |

Tables are created by `Base.metadata.create_all` on startup and by `app.seed`. There is no migration tool, because the schema
lives entirely in `app/models/__init__.py`.

Each **scheduling run record** stores: run ID, timestamps, trigger, mode, planning clock, jobs considered, jobs assigned,
unassigned jobs with classification and reasons, before/after snapshots of the schedule, objective score and breakdown,
summary metrics, algorithm statistics, and the list of `schedule_changes`.

### Job state machine

```text
pending ──► cancelled
unassigned ──► pending | cancelled
assigned ──► pending | in_progress | cancelled
in_progress ──► completed
completed, cancelled: terminal
```

Only the scheduler can move a job into `assigned` or `unassigned`. Any other transition is rejected with
`409 INVALID_STATUS_TRANSITION`. Once a job is in progress, only descriptive fields and its duration can change.

---

## 3. Scheduling algorithm

### Hard constraints (never violated)

1. The electrician has every required skill and covers the job's zone, and is active.
2. The job (plus the travel before it) lies inside a shift, which may extend up to the electrician's overtime allowance.
3. The job starts and ends inside its time window, and never starts before the planning clock.
4. No overlap with other jobs, unavailable periods, or an in-progress job. Travel time between consecutive jobs is always included.
5. **Urgent and high-priority jobs must finish by their SLA deadline.** If that is impossible, the job is reported as
   unassignable with `SLA_UNACHIEVABLE` so a dispatcher can escalate, rather than being planned late without anyone noticing.
   Medium- and low-priority jobs may finish late, with a per-minute penalty.

Travel time uses the straight-line distance × 1.3 road factor at 30 km/h, plus 5 minutes for parking and access.

### Objective (lower is better)

```text
score =  Σ unassigned jobs      × {urgent 10000, high 3000, medium 800, low 200}
       + Σ minutes past SLA     × {urgent 50, high 20, medium 5, low 2}
       + travel minutes         × 1
       + overtime minutes       × 3
       + reassigned jobs        × 60      (moved to a different electrician)
       + retimed jobs           × 15      (same electrician, start moved > 15 min)
```

The weights set a strict order of importance: leaving a high-priority job unassigned costs more than any realistic travel
saving, and change penalties make the schedule stable. Weights are defined in `scheduling/types.py::Weights`.

### Procedure (deterministic; ties are broken by IDs)

1. **Eligibility.** For each job, collect the *routes* `(electrician, shift instance)` where the electrician has the skills
   and zone and the shift overlaps the job's window.
2. **Keep pass (protect existing assignments).** Previous assignments are replayed on their original electrician in their
   original order. Those that are still feasible are kept; the rest are marked *displaced*, with the exact reason
   (for example "unavailable 08:00–17:00, so the job would finish after the window closes").
3. **Construction.** The remaining jobs are inserted most important first: priority, then fewest eligible routes,
   then earliest SLA. Each goes into the **cheapest feasible position** across all eligible routes (cheapest insertion).
4. **Improvement**, repeated up to 5 rounds until nothing improves:
   - retry unassigned jobs;
   - **ejection**: an unassigned job may take a slot by moving one job off a route, which is then re-inserted
     elsewhere or dropped. The objective decides, so a lower-priority job can never displace a higher-priority one;
   - **relocation**: move a single job to a cheaper position or electrician.

   A move is applied only if it strictly lowers the objective, so the loop always terminates.
5. **Re-optimise mode** (`POST /api/scheduling/reoptimize`) also builds a from-scratch schedule (change penalties still apply)
   and keeps whichever scores lower. The result is therefore never worse than the incremental schedule.
6. **Diagnosis.** Each job left unassigned is classified as either:
   - `unassignable`: impossible even with every calendar empty. Reasons: `MISSING_SKILLS`, `NO_ZONE_ELIGIBLE`,
     `SHIFT_CONSTRAINTS`, `ELECTRICIAN_UNAVAILABLE`, `SLA_UNACHIEVABLE`, `TRAVEL_TIME`, `WINDOW_EXPIRED`, `WINDOW_TOO_SHORT`.
   - `currently_infeasible` (`NO_FEASIBLE_SLOT`): possible in principle, but the capacity is taken. The jobs occupying it are listed.

   Every reason comes with a suggested action.

### Complexity

Let *n* be the number of jobs, *m* the eligible routes per job (after skill/zone/shift filtering, usually far below the
number of electricians × days), *r* the jobs per route, and *u* the unavailable periods per electrician.

- Evaluating a route: O(r·u). Results are memoised per (route, sequence).
- Best insertion of one job: O(m · r · r·u).
- Construction: O(n · m · r²·u).
- One improvement round: relocation O(n · m · r²·u) + ejection O(U · m · r · (r²·u + K·m·r²·u)),
  where *U* is the number of unassigned jobs and K = 12 is the cap on ejection candidates.
- At most 5 rounds, so the whole solve is polynomial. On the seed data (93 schedulable jobs, 20 electricians)
  a run takes about **30 ms** and roughly 1,200 route evaluations.

### Trade-offs and assumptions

- This is a greedy construction plus local search. It is not guaranteed optimal; for example, there are no swap moves
  between routes and no multi-job ejection chains.
- Shifts are same-day only (no overnight shifts). A job cannot be split across shifts.
- If an in-progress job has already run past its expected end, it is assumed to finish "now".
- Distances are straight-line estimates, not road routing.

---

## 4. Disruption handling and recovery

| Endpoint | What happens |
|---|---|
| `POST /api/disruptions/electrician-unavailable` | adds an unavailable period; the electrician's overlapping jobs are displaced and reassigned |
| `POST /api/disruptions/urgent-job` | creates the job (urgent by default); ejection lets it displace lower-priority work |
| `POST /api/disruptions/job-duration-change` | for a planned job, re-checks its slot; for an in-progress job, extends the busy period (late running) |
| `POST /api/disruptions/job-cancel` | cancels the job; the freed time is reused; the change is recorded as `removed` |
| `POST /api/disruptions/job-completion` | completes an in-progress job early or late; the electrician then sets off from that site at the actual finish time |

Each endpoint follows the same steps:

1. Snapshot the current schedule.
2. Apply the event and commit it. It is a real-world fact and must persist even if replanning fails.
3. Run incremental recovery.

Completed work is never touched. In-progress jobs are pinned to their electrician. The keep pass preserves every
assignment that is still feasible. The response lists the run's metrics, before/after snapshots, and each change with its
reason ("Previous slot with Arjun Rao no longer feasible: unavailable …", "Moved from X to Y to make room for job …",
"Same electrician; start moved later by 25 min because preceding work on the route changed").

---

## 5. Reliability and data integrity

- **Validation.** Pydantic schemas reject unknown fields, bad ranges, windows shorter than the duration, overlapping shifts,
  and unknown skill or zone codes.
- **Consistent errors.** Every error response has the shape `{"error": {"code", "message", "details"}}`
  (`VALIDATION_ERROR`, `NOT_FOUND`, `INVALID_STATUS_TRANSITION`, `SCHEDULER_BUSY`, `SCHEDULING_FAILED`, …).
- **Idempotency.** `POST /api/jobs`, the scheduling endpoints and all disruption endpoints accept an `Idempotency-Key` header.
  - A repeat with the same body replays the stored response, with the header `Idempotent-Replayed: true`.
  - The same key with a different body returns `422 IDEMPOTENCY_KEY_REUSED`.
  - A request still being processed under that key returns `409`.

  The frontend sends a fresh key on every create, run and disruption, so double-clicks are harmless.
- **Concurrency.**
  - All runs (and disruption + run pairs) hold a process-wide lock, so they execute one at a time and each sees the previous result.
  - A request waits up to 30 s for the lock, then gets `409 SCHEDULER_BUSY`.
  - Across processes, a run refuses to start while another run row is in the `running` state (and less than 10 minutes old).
  - SQLite runs in WAL mode with a busy timeout.
- **Transactions.** A run commits a `running` audit row first. Solving and saving then happen in **one transaction**.
- **Failed runs.** If a run raises, the transaction is rolled back, so the previous schedule stays exactly as it was. The run is
  marked `failed` with the error, and the API returns `500 SCHEDULING_FAILED` with the `run_id`.
- **Interrupted runs.** Runs left `running` by a crashed process are marked `interrupted` at the next startup.
  Their changes were never committed, so the schedule is consistent. The dashboard shows the latest failed or interrupted run.

---

## 6. API overview

Full, interactive documentation is in Swagger at `/docs`.

- **Auth**: `POST /api/auth/login` (form data), `GET /api/auth/me`
- **Jobs**: `POST/GET /api/jobs`, `GET/PUT/DELETE /api/jobs/{id}` (DELETE cancels), `POST /api/jobs/{id}/start`
- **Electricians**: `POST/GET /api/electricians`, `GET/PUT/DELETE /api/electricians/{id}` (DELETE deactivates),
  `POST /api/electricians/{id}/unavailability`, `DELETE /api/electricians/{id}/unavailability/{pid}`
- **Reference data**: `GET/POST /api/skills`, `GET/POST /api/zones`
- **Scheduling**: `POST /api/scheduling/run`, `POST /api/scheduling/reoptimize`, `GET /api/scheduling/current`,
  `GET /api/scheduling/history`, `GET /api/scheduling/runs/{run_id}`, `GET /api/scheduling/jobs/{job_id}`
- **Disruptions**: see section 4.
- **Dashboard**: `GET /api/dashboard/overview`, `/workload`, `/sla`, `/schedule?day=`, `/comparison`

## 7. Dashboard

| Page | Shows |
|---|---|
| Dashboard | KPIs; status × priority matrix (unassigned high/urgent highlighted); SLA risk list; unassigned jobs with their first reason and suggested action; electrician workload bars; latest run before/after with changes and reasons |
| Schedule | Gantt view per electrician and day: shifts, overtime allowance, unavailable periods, travel segments, jobs coloured by priority, and a "now" line. Click a job for its explanation and history |
| Jobs / Electricians | full CRUD, filters, availability management |
| Disruptions | forms for every disruption type, with the recovery result shown immediately |
| Run history | every run's full audit record |

## 8. Evaluation scenarios → where they are covered

| # | Scenario | Test |
|---|---|---|
| 1 | Highly skilled electrician unavailable | `test_scenario1_skilled_electrician_unavailable` |
| 2 | Two high-priority jobs competing for one slot | `test_scenario2_competing_high_priority_jobs`, `test_competing_high_priority_jobs_one_slot` |
| 3 | Skilled electrician cannot reach the job in time | `test_scenario3_skilled_but_cannot_reach_in_time`, `test_travel_time_can_make_job_unreachable` |
| 4 | Disruption while a job is in progress | `test_scenario4_disruption_while_job_in_progress` |
| 5 | Duplicate scheduling requests | `test_scenario5_duplicate_scheduling_requests`, `test_idempotent_job_creation` |
| 6 | Concurrent scheduling requests | `test_scenario6_concurrent_scheduling_requests` |
| 7 | No eligible electrician | `test_scenario7_no_eligible_electrician`, `test_missing_skill_is_unassignable_with_reason` |

`tests/helpers.py::assert_valid` checks every hard constraint on engine output, and `assert_schedule_valid` checks the
saved schedule after each scenario.

## 9. Known limitations and next steps

- No swap or 2-opt moves and no multi-job ejection chains. Adding them, or a metaheuristic such as simulated annealing
  or large-neighbourhood search, would improve quality on larger instances.
- Straight-line travel estimates; a routing API or a cached travel-time matrix would make them realistic.
- The scheduler lock is per process; the run-row guard only partly covers multiple workers.
  For production, use PostgreSQL with advisory locks or a job queue.
- No overnight shifts, no multi-day jobs, no breaks within shifts.
- A single dispatcher role. No per-user permissions, and no push notifications to electricians.
- The engine's SLA policy (hard for urgent/high) is fixed in code (`HARD_SLA_PRIORITIES`); it could be made configurable per job.
