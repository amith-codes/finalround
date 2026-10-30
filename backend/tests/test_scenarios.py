"""End-to-end evaluation scenarios on the seed dataset (section 10 of the brief) and disruptions."""
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Assignment, Electrician, Job, SchedulingRun
from tests.conftest import NOW

AS_OF = {"as_of": NOW.isoformat()}
D1 = (NOW + timedelta(days=1)).replace(hour=0)


def assert_schedule_valid():
    """Check the persisted schedule against every hard constraint."""
    with SessionLocal() as db:
        rows = db.scalars(select(Assignment).join(Job).where(
            Assignment.is_active.is_(True), Job.status.in_(["assigned", "in_progress"]))).all()
        by_tech: dict[int, list[Assignment]] = {}
        for a in rows:
            by_tech.setdefault(a.electrician_id, []).append(a)
            job, e = a.job, a.electrician
            if job.status == "assigned":
                assert {s.code for s in job.required_skills} <= {s.code for s in e.skills}, job.job_number
                assert job.zone.code in {z.code for z in e.zones}, job.job_number
                assert job.window_start <= a.start and a.end <= job.window_end, job.job_number
                assert e.active, f"{job.job_number} assigned to inactive {e.name}"
                for p in e.unavailable_periods:
                    assert not (p.start < a.end and p.end > a.start), f"{job.job_number} overlaps unavailability"
        for eid, items in by_tech.items():
            items.sort(key=lambda a: a.start)
            for x, y in zip(items, items[1:]):
                assert x.end <= y.start, f"overlap for electrician {eid}: {x.job.job_number} / {y.job.job_number}"
        ids = [a.job_id for a in rows]
        assert len(ids) == len(set(ids)), "a job has more than one active assignment"


def run(client, path="/api/scheduling/run", **kw):
    r = client.post(path, json={**AS_OF, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def job_by_title(db, title) -> Job:
    return db.scalar(select(Job).where(Job.title == title))


def test_seed_schedule_is_valid_and_explained(seeded, client):
    out = run(client)
    assert out["status"] == "completed"
    assert out["metrics"]["assigned"] >= 60
    assert_schedule_valid()
    codes = {u["job_number"]: u["reasons"][0]["code"] for u in out["unassigned"]}
    for title, code in [
        ("Transformer tap change + solar inverter integration", "MISSING_SKILLS"),
        ("Fire alarm panel fault at warehouse", "NO_ZONE_ELIGIBLE"),
        ("After-hours shop lighting changeover", "SHIFT_CONSTRAINTS"),
        ("EV charger commissioning at logistics hub", "ELECTRICIAN_UNAVAILABLE"),
        ("Cargo terminal power loss", "SLA_UNACHIEVABLE"),
        ("Airport hotel lift supply isolation", "TRAVEL_TIME"),
    ]:
        assert codes[job_by_title(seeded, title).job_number] == code, title
    # Every assigned job carries an explanation.
    for a in client.get("/api/scheduling/current").json()["assignments"]:
        assert a["explanation"]


def test_scenario1_skilled_electrician_unavailable(seeded, client):
    run(client)
    arjun = seeded.scalar(select(Electrician).where(Electrician.employee_code == "EL-001"))
    before = {a["job_id"]: a for a in client.get("/api/scheduling/current").json()["assignments"]}
    arjun_jobs = {jid for jid, a in before.items() if a["electrician_id"] == arjun.id and a["status"] == "assigned"}
    others = {jid: (a["electrician_id"], a["start"]) for jid, a in before.items() if a["electrician_id"] != arjun.id}
    r = client.post("/api/disruptions/electrician-unavailable", json={
        "electrician_id": arjun.id, "start": D1.replace(hour=0).isoformat(),
        "end": (D1 + timedelta(days=1)).isoformat(), "reason": "Sick", **AS_OF})
    assert r.status_code == 200, r.text
    body = r.json()
    assert_schedule_valid()
    changes = {c["job_id"]: c for c in body["run"]["changes"]}
    d1_jobs = {j for j in arjun_jobs if before[j]["start"].startswith(D1.date().isoformat())}
    assert d1_jobs, "seed should give Arjun work on D1"
    for j in d1_jobs:
        assert j in changes and changes[j]["change_type"] in ("reassigned", "unassigned")
        assert changes[j]["reason"]
    # HV work that only Arjun can do becomes unassignable with an availability reason.
    hv = job_by_title(seeded, "HV switchgear inspection")
    seeded.expire_all()
    hv = seeded.get(Job, hv.id)
    assert hv.status == "unassigned"
    assert hv.unassigned_reasons[0]["code"] == "ELECTRICIAN_UNAVAILABLE"
    # Most unaffected assignments stay exactly where they were.
    after = {a["job_id"]: (a["electrician_id"], a["start"]) for a in client.get("/api/scheduling/current").json()["assignments"]}
    kept = sum(1 for j, v in others.items() if after.get(j) == v)
    assert kept / len(others) > 0.8


def test_scenario2_competing_high_priority_jobs(seeded, client):
    out = run(client)
    a = job_by_title(seeded, "Solar inverter shutdown - site A")
    b = job_by_title(seeded, "Solar inverter shutdown - site B")
    assigned = set(out["jobs_assigned"])
    assert (a.id in assigned) != (b.id in assigned), "exactly one can take the only slot"
    loser = b if a.id in assigned else a
    entry = next(u for u in out["unassigned"] if u["job_id"] == loser.id)
    assert entry["classification"] == "currently_infeasible"
    assert entry["reasons"][0]["code"] == "NO_FEASIBLE_SLOT"


def test_scenario3_skilled_but_cannot_reach_in_time(seeded, client):
    out = run(client)
    job = job_by_title(seeded, "Airport hotel lift supply isolation")
    entry = next(u for u in out["unassigned"] if u["job_id"] == job.id)
    assert entry["classification"] == "unassignable"
    assert entry["reasons"][0]["code"] == "TRAVEL_TIME"
    assert "would finish" in entry["reasons"][0]["message"]


def test_scenario4_disruption_while_job_in_progress(seeded, client):
    run(client)
    ip = seeded.scalar(select(Job).where(Job.status == "in_progress"))
    tech_id = ip.active_assignment.electrician_id
    r = client.post("/api/disruptions/electrician-unavailable", json={
        "electrician_id": tech_id, "start": NOW.isoformat(), "end": (NOW + timedelta(hours=6)).isoformat(), **AS_OF})
    assert r.status_code == 200
    assert ip.job_number in r.json()["disruption"]["protected_in_progress_jobs"]
    seeded.expire_all()
    ip = seeded.get(Job, ip.id)
    assert ip.status == "in_progress" and ip.active_assignment.electrician_id == tech_id
    # Late-running in-progress job: extend its duration, downstream work is re-planned but the job stays put.
    r = client.post("/api/disruptions/job-duration-change", json={"job_id": ip.id, "new_duration_minutes": ip.duration_minutes + 90, **AS_OF})
    assert r.status_code == 200
    seeded.expire_all()
    assert seeded.get(Job, ip.id).status == "in_progress"
    assert_schedule_valid()


def test_scenario5_duplicate_scheduling_requests(seeded, client):
    h = {"Idempotency-Key": "run-001"}
    a = client.post("/api/scheduling/run", json=AS_OF, headers=h)
    b = client.post("/api/scheduling/run", json=AS_OF, headers=h)
    assert a.json()["id"] == b.json()["id"]
    assert b.headers["Idempotent-Replayed"] == "true"
    assert seeded.query(SchedulingRun).count() == 1
    # Without a key, a repeated run is deterministic and changes nothing.
    c = run(client)
    assert c["metrics"]["changes"]["reassigned"] == 0 and c["metrics"]["changes"]["retimed"] == 0
    assert c["metrics"]["changes"]["assigned"] == 0


def test_scenario6_concurrent_scheduling_requests(seeded, client):
    token = client.headers["Authorization"]
    results = []

    def worker(path):
        with TestClient(app) as c:
            c.headers["Authorization"] = token
            results.append(c.post(path, json=AS_OF))

    threads = [threading.Thread(target=worker, args=(p,)) for p in
               ("/api/scheduling/run", "/api/scheduling/reoptimize", "/api/scheduling/run")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    runs = seeded.query(SchedulingRun).order_by(SchedulingRun.started_at).all()
    assert len(runs) == 3 and all(r.status == "completed" for r in runs)
    assert_schedule_valid()


def test_scenario7_no_eligible_electrician(seeded, client):
    out = run(client)
    for title in ("Transformer tap change + solar inverter integration", "Fire alarm panel fault at warehouse"):
        job = job_by_title(seeded, title)
        entry = next(u for u in out["unassigned"] if u["job_id"] == job.id)
        assert entry["classification"] == "unassignable"
        assert entry["reasons"][0]["suggestion"]


def test_urgent_job_disruption(seeded, client):
    run(client)
    body = {"title": "Sparking main switch", "lat": 12.905, "lon": 77.585, "zone_code": "STH",
            "duration_minutes": 60, "required_skills": ["panel_upgrade"],
            "window_start": D1.replace(hour=8).isoformat(), "window_end": D1.replace(hour=11).isoformat(),
            "sla_deadline": D1.replace(hour=11).isoformat(), **AS_OF}
    r = client.post("/api/disruptions/urgent-job", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    jid = out["disruption"]["job_id"]
    assert jid in out["run"]["jobs_assigned"], "urgent job must displace lower-value work"
    assert_schedule_valid()


def test_cancel_frees_capacity(seeded, client):
    out = run(client)
    first = client.get("/api/scheduling/current").json()["assignments"]
    victim = next(a for a in first if a["status"] == "assigned")
    r = client.post("/api/disruptions/job-cancel", json={"job_id": victim["job_id"], "reason": "Customer no-show", **AS_OF})
    assert r.status_code == 200
    changes = r.json()["run"]["changes"]
    assert any(c["job_id"] == victim["job_id"] and c["change_type"] == "removed" for c in changes)
    assert r.json()["run"]["metrics"]["unassigned"] <= out["metrics"]["unassigned"]
    # Cancelling twice is rejected.
    again = client.post("/api/disruptions/job-cancel", json={"job_id": victim["job_id"], **AS_OF})
    assert again.status_code == 409


def test_failed_run_leaves_schedule_untouched(seeded, client, monkeypatch):
    run(client)
    before = client.get("/api/scheduling/current").json()["assignments"]

    def boom(*_a, **_k):
        raise RuntimeError("solver crashed")

    monkeypatch.setattr("app.services.scheduling_service.solve", boom)
    r = client.post("/api/scheduling/run", json=AS_OF)
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["code"] == "SCHEDULING_FAILED" and err["details"]["run_id"]
    failed = seeded.get(SchedulingRun, err["details"]["run_id"])
    seeded.refresh(failed)
    assert failed.status == "failed" and "solver crashed" in failed.error
    assert client.get("/api/scheduling/current").json()["assignments"] == before


@pytest.mark.parametrize("path", ["/api/scheduling/run", "/api/scheduling/reoptimize"])
def test_reoptimize_never_worse(seeded, client, path):
    first = run(client)
    second = run(client, path)
    assert second["objective_score"] <= first["objective_score"] + 1e-6
