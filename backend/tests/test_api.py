"""API-level tests: validation, error format, state machine, idempotency, auth."""
from datetime import datetime, timedelta

from tests.conftest import NOW

D1 = (NOW + timedelta(days=1)).replace(hour=0)


def job_payload(**over):
    body = {
        "title": "Replace faulty RCD", "lat": 12.97, "lon": 77.59, "zone_code": "CEN", "priority": "high",
        "duration_minutes": 60, "required_skills": ["fault_finding"],
        "window_start": D1.replace(hour=9).isoformat(), "window_end": D1.replace(hour=13).isoformat(),
        "sla_deadline": D1.replace(hour=14).isoformat(),
    }
    body.update(over)
    return body


def test_requires_auth(client):
    client.headers.pop("Authorization")
    r = client.get("/api/jobs")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHORIZED"


def test_bad_login(client):
    r = client.post("/api/auth/login", data={"username": "dispatcher", "password": "nope"})
    assert r.status_code == 401


def test_create_and_get_job(seeded, client):
    r = client.post("/api/jobs", json=job_payload())
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["job_number"].startswith("JOB-") and job["status"] == "pending"
    assert client.get(f"/api/jobs/{job['id']}").json()["title"] == "Replace faulty RCD"


def test_validation_errors_have_consistent_shape(seeded, client):
    r = client.post("/api/jobs", json=job_payload(window_end=D1.replace(hour=8).isoformat()))
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR" and err["details"]

    r = client.post("/api/jobs", json=job_payload(required_skills=["telepathy"]))
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_SKILL"

    r = client.post("/api/jobs", json=job_payload(duration_minutes=500))
    assert r.status_code == 422  # longer than the window

    r = client.get("/api/jobs/999999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_idempotent_job_creation(seeded, client):
    h = {"Idempotency-Key": "create-job-abc"}
    a = client.post("/api/jobs", json=job_payload(), headers=h)
    b = client.post("/api/jobs", json=job_payload(), headers=h)
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] == b.json()["id"]
    assert b.headers.get("Idempotent-Replayed") == "true"
    c = client.post("/api/jobs", json=job_payload(title="Something else"), headers=h)
    assert c.status_code == 422 and c.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    titles = [j["title"] for j in client.get("/api/jobs").json()]
    assert titles.count("Replace faulty RCD") == 1


def test_invalid_state_transitions_rejected(seeded, client):
    job = client.post("/api/jobs", json=job_payload()).json()
    # pending -> completed is not allowed
    r = client.put(f"/api/jobs/{job['id']}", json={"status": "completed"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    # 'assigned' is set only by the scheduler
    r = client.put(f"/api/jobs/{job['id']}", json={"status": "assigned"})
    assert r.status_code == 409
    # pending -> in_progress needs an assignment
    r = client.post(f"/api/jobs/{job['id']}/start")
    assert r.status_code == 409
    # cancel, then no further edits
    assert client.delete(f"/api/jobs/{job['id']}").json()["status"] == "cancelled"
    r = client.put(f"/api/jobs/{job['id']}", json={"title": "Changed"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "JOB_LOCKED"


def test_full_lifecycle(seeded, client):
    job = client.post("/api/jobs", json=job_payload()).json()
    run = client.post("/api/scheduling/run", json={"as_of": NOW.isoformat()}).json()
    assert job["id"] in run["jobs_assigned"]
    detail = client.get(f"/api/scheduling/jobs/{job['id']}").json()
    assert detail["current_assignment"] and detail["explanation"]
    start = detail["current_assignment"]["start"]
    r = client.post(f"/api/jobs/{job['id']}/start", json={"started_at": start})
    assert r.json()["status"] == "in_progress"
    r = client.post("/api/disruptions/job-completion",
                    json={"job_id": job["id"], "completed_at": (datetime.fromisoformat(start) + timedelta(minutes=45)).isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["disruption"]["timing"] == "15 min early"
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "completed"


def test_electrician_crud(seeded, client):
    body = {"name": "Test Sparky", "home_lat": 12.97, "home_lon": 77.59, "skills": ["lighting"], "zones": ["CEN"],
            "shifts": [{"day_of_week": d, "start_time": "08:00", "end_time": "16:00"} for d in range(5)]}
    r = client.post("/api/electricians", json=body)
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["employee_code"].startswith("EL-") and len(e["shifts"]) == 5
    r = client.put(f"/api/electricians/{e['id']}", json={"skills": ["lighting", "ev_charger"]})
    assert r.json()["skills"] == ["ev_charger", "lighting"]
    bad = client.post("/api/electricians", json={**body, "shifts": [{"day_of_week": 0, "start_time": "16:00", "end_time": "08:00"}]})
    assert bad.status_code == 422
    r = client.delete(f"/api/electricians/{e['id']}")
    assert r.json()["electrician"]["active"] is False


def test_dashboard_endpoints(seeded, client):
    client.post("/api/scheduling/run", json={"as_of": NOW.isoformat()})
    q = {"as_of": NOW.isoformat()}
    ov = client.get("/api/dashboard/overview", params=q).json()
    assert ov["total_jobs"] == 100 and ov["latest_run"]
    wl = client.get("/api/dashboard/workload", params={**q, "start": D1.date().isoformat()}).json()
    assert len(wl["electricians"]) == 20
    sla = client.get("/api/dashboard/sla", params=q).json()
    assert sla["counts"]["unassigned"] > 0
    sched = client.get("/api/dashboard/schedule", params={**q, "day": D1.date().isoformat()}).json()
    assert any(lane["jobs"] for lane in sched["lanes"])
    cmp_ = client.get("/api/dashboard/comparison").json()
    assert cmp_["run"]["after_snapshot"]
