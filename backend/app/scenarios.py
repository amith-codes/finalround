"""Disruption scenarios for demos, executed against a running API.

    python -m app.scenarios list
    python -m app.scenarios run <name> [--api http://127.0.0.1:8000]
    python -m app.scenarios run all

Run `python -m app.seed` first (and start uvicorn). Each scenario prints what changed.
"""
import argparse
import sys
import threading
import uuid
from datetime import datetime, timedelta

import httpx

from app import config


class Api:
    def __init__(self, base: str):
        self.c = httpx.Client(base_url=base, timeout=60)
        r = self.c.post("/api/auth/login", data={"username": config.DEFAULT_ADMIN_USERNAME,
                                                 "password": config.DEFAULT_ADMIN_PASSWORD})
        r.raise_for_status()
        self.token = r.json()["access_token"]
        self.c.headers["Authorization"] = f"Bearer {self.token}"

    def get(self, path, **params):
        r = self.c.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def post(self, path, body=None, key=None, ok=(200, 201)):
        headers = {"Idempotency-Key": key} if key else {}
        r = self.c.post(path, json=body or {}, headers=headers)
        if r.status_code not in ok:
            print(f"  ! {path} -> {r.status_code} {r.text}")
        return r


def _tomorrow(h, m=0):
    return (datetime.now() + timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)


def _print_run(run: dict) -> None:
    m = run["metrics"]
    print(f"  run {run['id'][:8]}  trigger={run['trigger']}  objective={run['objective_score']}")
    print(f"  assigned={m['assigned']} unassigned={m['unassigned']} unchanged={m['unchanged']} changes={m['changes']}")
    for c in run["changes"][:12]:
        print(f"   - {c['job_number']} {c['change_type']:<10} {c['old_electrician_name'] or '-'} -> "
              f"{c['new_electrician_name'] or '-'}: {(c['reason'] or '')[:110]}")
    if len(run["changes"]) > 12:
        print(f"   ... {len(run['changes']) - 12} more")


def _ensure_schedule(api: Api) -> dict:
    current = api.get("/api/scheduling/current")
    if not current["run"]:
        print("No schedule yet - running initial scheduling.")
        _print_run(api.post("/api/scheduling/run").json())
        current = api.get("/api/scheduling/current")
    return current


def skilled_unavailable(api: Api):
    """EL-001 (the only high-voltage electrician) calls in sick for tomorrow."""
    _ensure_schedule(api)
    arjun = next(e for e in api.get("/api/electricians") if e["employee_code"] == "EL-001")
    r = api.post("/api/disruptions/electrician-unavailable", {
        "electrician_id": arjun["id"], "start": _tomorrow(0).isoformat(), "end": _tomorrow(23, 59).isoformat(),
        "reason": "Sick leave"})
    print(f"  directly affected: {r.json()['disruption']['directly_affected_jobs']}")
    _print_run(r.json()["run"])


def urgent_job(api: Api):
    """An urgent sparking-switchboard call arrives in the South zone tomorrow morning."""
    _ensure_schedule(api)
    r = api.post("/api/disruptions/urgent-job", {
        "title": "Sparking main switchboard", "lat": 12.906, "lon": 77.588, "zone_code": "STH",
        "duration_minutes": 60, "required_skills": ["panel_upgrade"], "customer_name": "Lakeview Villas",
        "window_start": _tomorrow(8).isoformat(), "window_end": _tomorrow(11).isoformat(),
        "sla_deadline": _tomorrow(11).isoformat()})
    _print_run(r.json()["run"])


def _first_assigned(api: Api) -> dict:
    current = _ensure_schedule(api)
    return next(a for a in current["assignments"] if a["status"] == "assigned")


def duration_change(api: Api):
    """The first planned job of the day turns out to need an extra hour."""
    a = _first_assigned(api)
    job = api.get(f"/api/jobs/{a['job_id']}")
    r = api.post("/api/disruptions/job-duration-change", {
        "job_id": job["id"], "new_duration_minutes": job["duration_minutes"] + 60, "reason": "Extra circuits found"})
    _print_run(r.json()["run"])


def cancel_job(api: Api):
    """A customer cancels a planned job."""
    a = _first_assigned(api)
    r = api.post("/api/disruptions/job-cancel", {"job_id": a["job_id"], "reason": "Customer cancelled"})
    _print_run(r.json()["run"])


def _in_progress(api: Api) -> dict | None:
    jobs = api.get("/api/jobs", status="in_progress")
    if not jobs:
        print("  no in-progress job available (re-seed to get some)")
    return jobs[0] if jobs else None


def early_finish(api: Api):
    """An in-progress job finishes 30 minutes early."""
    job = _in_progress(api)
    if job:
        start = datetime.fromisoformat(job["actual_start"])
        done = start + timedelta(minutes=max(15, job["duration_minutes"] - 30))
        r = api.post("/api/disruptions/job-completion", {"job_id": job["id"], "completed_at": done.isoformat()})
        print(f"  {r.json()['disruption']['job_number']} completed {r.json()['disruption']['timing']}")
        _print_run(r.json()["run"])


def late_finish(api: Api):
    """An in-progress job is running 90 minutes over (reported as a duration change)."""
    job = _in_progress(api)
    if job:
        r = api.post("/api/disruptions/job-duration-change", {
            "job_id": job["id"], "new_duration_minutes": job["duration_minutes"] + 90, "reason": "Corroded busbar"})
        _print_run(r.json()["run"])


def duplicate_requests(api: Api):
    """The same scheduling request is sent twice with one Idempotency-Key."""
    key = str(uuid.uuid4())
    a = api.post("/api/scheduling/run", key=key)
    b = api.post("/api/scheduling/run", key=key)
    print(f"  first run id  {a.json()['id']}")
    print(f"  second run id {b.json()['id']}  replayed={b.headers.get('Idempotent-Replayed')}")


def concurrent_runs(api: Api):
    """Two scheduling requests fire at the same moment; they are serialised safely."""
    out = []

    def go(path):
        out.append((path, httpx.post(api.c.base_url.join(path), json={}, timeout=120,
                                     headers={"Authorization": f"Bearer {api.token}"})))

    ts = [threading.Thread(target=go, args=(p,)) for p in ("/api/scheduling/run", "/api/scheduling/reoptimize")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    for path, r in out:
        body = r.json()
        print(f"  {path} -> {r.status_code} run={body.get('id', body)}")


SCENARIOS = {
    "skilled-unavailable": skilled_unavailable,
    "urgent-job": urgent_job,
    "duration-change": duration_change,
    "cancel-job": cancel_job,
    "early-finish": early_finish,
    "late-finish": late_finish,
    "duplicate-requests": duplicate_requests,
    "concurrent-runs": concurrent_runs,
}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["list", "run"])
    p.add_argument("name", nargs="?")
    p.add_argument("--api", default="http://127.0.0.1:8000")
    args = p.parse_args()
    if args.command == "list":
        for name, fn in SCENARIOS.items():
            print(f"{name:<20} {fn.__doc__}")
        return
    names = list(SCENARIOS) if args.name == "all" else [args.name]
    if not args.name or any(n not in SCENARIOS for n in names):
        sys.exit(f"Unknown scenario. Choose from: {', '.join(SCENARIOS)} or 'all'")
    api = Api(args.api)
    for n in names:
        print(f"\n=== {n}: {SCENARIOS[n].__doc__}")
        SCENARIOS[n](api)


if __name__ == "__main__":
    main()
