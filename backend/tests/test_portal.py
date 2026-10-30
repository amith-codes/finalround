"""Role portal tests: customer request flow, electrician responses with reasons, admin activity and counts."""
from datetime import datetime, time, timedelta
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from app.models import (
    Assignment, AvailabilityOverride, Electrician, ElectricianLocality, Job, Shift,
)
from app.models.enums import JobStatus


def _headers(client, username, password):
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def portal(seeded, client):
    customer = _headers(client, "demo_customer", "customer123")
    electrician = _headers(client, "demo_electrician", "electrician123")
    eid = client.get("/api/auth/me", headers=electrician).json()["electrician_id"]
    profile = client.get(f"/api/electricians/{eid}").json()
    zone = next(z for z in client.get("/api/zones").json() if z["code"] == profile["zones"][0])
    # Booking checks use the real clock, so the window is relative to now rather than tests.conftest.NOW.
    start = (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    body = {
        "title": "Fan repair", "customer_name": "Demo Customer", "customer_phone": "9800000000",
        "address": "12 MG Road", "service_locality": profile["localities"][0], "district": "Bengaluru Urban",
        "state": "Karnataka", "service_items": [{"id": "uc_fan_repair", "quantity": 1}],
        "requested_electrician_id": eid, "lat": zone["center_lat"], "lon": zone["center_lon"],
        "zone_code": zone["code"], "duration_minutes": 60, "required_skills": [profile["skills"][0]],
        "window_start": start.isoformat(), "window_end": (start + timedelta(days=7)).isoformat(),
        "sla_deadline": (start + timedelta(days=7, hours=2)).isoformat(),
    }
    r = client.post("/api/jobs", json=body, headers=customer)
    assert r.status_code == 201, r.text
    return {"customer": customer, "electrician": electrician, "eid": eid, "job": r.json()}


def _act(client, p, action, reason=None):
    return client.post(f"/api/portal/electrician/bookings/{p['job']['id']}/action",
                       json={"action": action, "reason": reason}, headers=p["electrician"])


def test_customer_request_starts_awaiting_response(portal, client):
    job = portal["job"]
    assert job["booking_stage"] == "awaiting_response"
    assert job["booking_amount"] == 198  # 149 + 49 visit fee below ₹399
    response = client.get("/api/portal/electrician/bookings", headers=portal["electrician"]).json()
    assigned = [job for panel in response["electricians"] for job in panel["assigned"]]
    assert any(j["id"] == job["id"] and j["customer_phone"] == "9800000000" for j in assigned)


@pytest.mark.parametrize("action", ["decline", "cancel", "customer_unavailable", "disturbed"])
def test_release_actions_require_reason(portal, client, action):
    for reason in (None, "", "   "):
        r = _act(client, portal, action, reason)
        assert r.status_code == 422 and r.json()["error"]["code"] == "REASON_REQUIRED"
    if action == "disturbed":
        assert _act(client, portal, action, "x" * 251).status_code == 422
    assert client.get(f"/api/jobs/{portal['job']['id']}").json()["status"] == "assigned"


def test_decline_is_recorded_for_admin_and_customer(portal, client, seeded):
    job, candidate, _ = _prepare_disturbance(portal, client, seeded, accepted=False)
    job_id = job.id
    r = _act(client, portal, "decline", "Van broke down")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "assigned" and r.json()["booking_stage"] == "awaiting_response"
    assert r.json()["assignment"]["electrician_id"] == candidate.id

    mine = next(j for j in client.get("/api/portal/customer/bookings", headers=portal["customer"]).json()
                if j["id"] == job_id)
    assert mine["booking_stage"] == "awaiting_response"
    assert mine["last_disruption"]["action"] == "decline"
    history = client.get(f"/api/portal/bookings/{job_id}/history", headers=portal["customer"]).json()
    assert any(e["action"] == "decline" and e["reason"] == "Van broke down" for e in history["events"])
    assert any(e["action"] == "reassigned" and e["new_electrician"] == candidate.name for e in history["events"])

    activity = client.get("/api/portal/admin/booking-activity").json()
    event = next(e for e in activity["events"] if e["job_id"] == job_id and e["action"] == "decline")
    assert event["electrician_id"] == portal["eid"] and event["reason"] == "Van broke down"
    assert event["needs_reassignment"] is False
    assert event["current_electrician"] == candidate.name


def test_customer_cancel_records_reason_and_electrician(portal, client):
    job_id = portal["job"]["id"]
    r = client.post(f"/api/portal/customer/bookings/{job_id}/cancel", params={"reason": "Fixed it myself"},
                    headers=portal["customer"])
    assert r.status_code == 200 and r.json()["booking_stage"] == "cancelled"
    event = next(e for e in client.get("/api/portal/admin/booking-activity").json()["events"] if e["job_id"] == job_id)
    assert event["action"] == "cancelled_by_customer" and event["reason"] == "Fixed it myself"
    assert event["electrician_id"] == portal["eid"] and event["needs_reassignment"] is False


def test_accept_and_start_stages(portal, client):
    # Completing needs a later minute than the start, so the completed stage is not exercised here.
    assert _act(client, portal, "accept").json()["booking_stage"] == "accepted"
    assert _act(client, portal, "start").json()["booking_stage"] == "in_progress"
    assert _act(client, portal, "decline", "Too late").status_code == 409


def _prepare_disturbance(portal, client, db, *, accepted=True):
    if accepted:
        assert _act(client, portal, "accept").json()["booking_stage"] == "accepted"
    db.expire_all()
    job = db.get(Job, portal["job"]["id"])
    old_assignment = job.active_assignment
    old_electrician_id = portal["eid"]
    candidate = db.scalar(select(Electrician).where(Electrician.id != old_electrician_id).order_by(Electrician.id))
    assert candidate is not None

    # Isolate the test booking from the seeded demo schedule and all but one possible replacement.
    for other in db.scalars(select(Job).where(Job.id != job.id)):
        other.status = JobStatus.CANCELLED.value
        for assignment in other.assignments:
            assignment.is_active = False
    electricians = list(db.scalars(select(Electrician)))
    for electrician in electricians:
        electrician.active = electrician.id in {old_electrician_id, candidate.id}

    start = (datetime.now() + timedelta(days=5)).replace(hour=10, minute=0, second=0, microsecond=0)
    job.window_start = start
    job.window_end = start + timedelta(hours=2)
    job.sla_deadline = start + timedelta(hours=4)
    job.duration_minutes = 60
    old_assignment.start = start
    old_assignment.end = start + timedelta(minutes=60)

    candidate.active = True
    candidate.home_lat, candidate.home_lon = job.lat, job.lon
    candidate.skills = list(job.required_skills)
    candidate.zones = [job.zone]
    candidate.service_localities = [ElectricianLocality(locality=job.booking_details.locality)]
    candidate.shifts = [Shift(day_of_week=day, start_time=time(0, 0), end_time=time(23, 59)) for day in range(7)]
    candidate.unavailable_periods = []
    override = db.get(AvailabilityOverride, candidate.id)
    if override:
        override.is_available = True
    db.commit()
    db.expire_all()
    return db.get(Job, job.id), db.get(Electrician, candidate.id), start


def _disturb(client, p, reason="Vehicle breakdown", headers=None):
    return client.post(f"/api/portal/electrician/bookings/{p['job']['id']}/action",
                       json={"action": "disturbed", "reason": reason},
                       headers=headers or p["electrician"])


def _cancel_service(client, p, reason="Unable to attend", headers=None):
    return client.post(f"/api/portal/electrician/bookings/{p['job']['id']}/action",
                       json={"action": "cancel", "reason": reason},
                       headers=headers or p["electrician"])


def test_disturbed_reassigns_locally_and_keeps_replacement_pending(portal, client, seeded):
    job, candidate, _ = _prepare_disturbance(portal, client, seeded)
    old_name = job.active_assignment.electrician.name

    response = _disturb(client, portal, "Severe traffic on the route")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "assigned"
    assert result["booking_stage"] == "awaiting_response"
    assert result["assignment"]["electrician_id"] == candidate.id

    schedule = client.get(f"/api/scheduling/jobs/{job.id}").json()
    latest_change = schedule["changes"][-1]
    assert "zone" not in latest_change["reason"].casefold()
    assert "released" in latest_change["reason"].casefold()

    history = client.get(f"/api/portal/bookings/{job.id}/history", headers=portal["customer"]).json()
    disturbed = next(event for event in history["events"] if event["action"] == "disturbed")
    reassigned = next((event for event in history["events"] if event["action"] == "reassigned"), None)
    assert reassigned is not None, history["events"]
    assert disturbed["actor_role"] == "electrician"
    assert disturbed["old_electrician"] == old_name
    assert disturbed["reason"] == "Severe traffic on the route"
    assert reassigned["old_electrician"] == old_name
    assert reassigned["new_electrician"] == candidate.name
    assert any(not row["active"] and row["electrician"] == old_name for row in history["assignments"])
    assert any(row["active"] and row["electrician"] == candidate.name for row in history["assignments"])

    customer_job = next(item for item in client.get("/api/portal/customer/bookings", headers=portal["customer"]).json()
                        if item["id"] == job.id)
    assert customer_job["last_disruption"]["reason"] == "Severe traffic on the route"
    assert customer_job["last_disruption"]["replacement_electrician"] == candidate.name
    assert customer_job["booking_stage"] == "awaiting_response"

    activity = client.get("/api/portal/admin/booking-activity").json()
    item = next(event for event in activity["events"] if event["job_id"] == job.id and event["action"] == "disturbed")
    assert item["electrician"] == old_name
    assert item["current_electrician"] == candidate.name
    assert item["reassignment_status"] == "awaiting_electrician_response"
    assert item["needs_reassignment"] is False

    # A repeated request from the released electrician cannot create a second active assignment.
    repeated = _disturb(client, portal, "Submitting again")
    assert repeated.status_code == 403
    active_ids = list(seeded.scalars(select(Assignment.id).where(
        Assignment.job_id == job.id, Assignment.is_active.is_(True))))
    assert len(active_ids) == 1


def test_pending_customer_decline_reassigns_locally_immediately(portal, client, seeded):
    job, candidate, _ = _prepare_disturbance(portal, client, seeded, accepted=False)
    old_name = job.active_assignment.electrician.name

    response = _act(client, portal, "decline", "Unable to attend")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "assigned"
    assert result["booking_stage"] == "awaiting_response"
    assert result["assignment"]["electrician_id"] == candidate.id
    assert result["last_disruption"]["action"] == "decline"
    assert result["last_disruption"]["reason"] == "Unable to attend"
    assert result["last_disruption"]["replacement_electrician"] == candidate.name

    history = client.get(f"/api/portal/bookings/{job.id}/history", headers=portal["customer"]).json()
    declined = next(event for event in history["events"] if event["action"] == "decline")
    reassigned = next(event for event in history["events"] if event["action"] == "reassigned")
    assert declined["old_electrician"] == old_name
    assert declined["reason"] == "Unable to attend"
    assert reassigned["new_electrician"] == candidate.name
    assert len([row for row in history["assignments"] if row["active"]]) == 1


def test_pending_customer_decline_without_local_candidate_keeps_booking_open(portal, client, seeded):
    job, candidate, _ = _prepare_disturbance(portal, client, seeded, accepted=False)
    candidate.service_localities = [ElectricianLocality(locality="Different locality")]
    seeded.commit()

    response = _act(client, portal, "decline", "Unable to attend")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "unassigned"
    assert result["booking_stage"] == "reassignment_needed"
    assert result["assignment"] is None
    assert result["last_disruption"]["action"] == "decline"
    activity = client.get("/api/portal/admin/booking-activity").json()
    event = next(event for event in activity["events"] if event["job_id"] == job.id and event["action"] == "decline")
    assert event["needs_reassignment"] is True
    assert event["reassignment_status"] == "awaiting_manual_reassignment"
    seeded.expire_all()
    assert seeded.get(Job, job.id).status == JobStatus.UNASSIGNED.value


def test_disturbed_reassigns_same_locality_without_legacy_skill_or_zone(portal, client, seeded):
    job, candidate, _ = _prepare_disturbance(portal, client, seeded)
    # Customer bookings must use the customer's locality, even when old zone
    # metadata and catalog skill tags no longer match the replacement.
    candidate.zones = []
    candidate.skills = []
    registered_locality = candidate.service_localities[0].locality
    job.booking_details.locality = (
        f"{registered_locality}, {job.booking_details.district}, {job.booking_details.state}"
    )
    candidate.service_localities[0].locality = registered_locality
    seeded.commit()

    response = _disturb(client, portal, "Vehicle problem")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "assigned"
    assert result["booking_stage"] == "awaiting_response"
    assert result["assignment"]["electrician_id"] == candidate.id


def test_electrician_cancel_reassigns_customer_service_locally(portal, client, seeded):
    job, candidate, _ = _prepare_disturbance(portal, client, seeded)
    old_name = job.active_assignment.electrician.name

    response = _cancel_service(client, portal, "Vehicle problem")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "assigned"
    assert result["booking_stage"] == "awaiting_response"
    assert result["assignment"]["electrician_id"] == candidate.id
    assert result["cancel_reason"] is None
    assert result["last_disruption"]["action"] == "cancel"
    assert result["last_disruption"]["reason"] == "Vehicle problem"
    assert result["last_disruption"]["replacement_electrician"] == candidate.name

    history = client.get(f"/api/portal/bookings/{job.id}/history", headers=portal["customer"]).json()
    cancelled = next(event for event in history["events"] if event["action"] == "cancel")
    reassigned = next(event for event in history["events"] if event["action"] == "reassigned")
    assert cancelled["old_electrician"] == old_name
    assert cancelled["reason"] == "Vehicle problem"
    assert reassigned["new_electrician"] == candidate.name
    assert len([row for row in history["assignments"] if row["active"]]) == 1

    activity = client.get("/api/portal/admin/booking-activity").json()
    event = next(event for event in activity["events"] if event["job_id"] == job.id and event["action"] == "cancel")
    assert event["current_electrician"] == candidate.name
    assert event["reassignment_status"] == "awaiting_electrician_response"

    repeated = _cancel_service(client, portal, "Submitting again")
    assert repeated.status_code == 403
    seeded.expire_all()
    assert len(list(seeded.scalars(select(Assignment.id).where(
        Assignment.job_id == job.id, Assignment.is_active.is_(True))))) == 1


def test_electrician_cancel_without_local_replacement_keeps_booking_open(portal, client, seeded):
    job, candidate, _ = _prepare_disturbance(portal, client, seeded)
    candidate.service_localities = [ElectricianLocality(locality="Different locality")]
    seeded.commit()

    response = _cancel_service(client, portal, "Vehicle problem")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "unassigned"
    assert result["booking_stage"] == "reassignment_needed"
    assert result["assignment"] is None
    assert result["cancel_reason"] is None
    assert result["last_disruption"]["action"] == "cancel"
    assert result["last_disruption"]["reassignment_status"] == "awaiting_reassignment"
    activity = client.get("/api/portal/admin/booking-activity").json()
    event = next(event for event in activity["events"] if event["job_id"] == job.id and event["action"] == "cancel")
    assert event["needs_reassignment"] is True
    assert event["reassignment_status"] == "awaiting_manual_reassignment"
    seeded.expire_all()
    assert seeded.get(Job, job.id).status == JobStatus.UNASSIGNED.value


def test_concurrent_disturbed_submissions_create_one_reassignment(portal, client, seeded):
    job, candidate, _ = _prepare_disturbance(portal, client, seeded)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(
            lambda reason: _disturb(client, portal, reason),
            ("Vehicle problem", "Severe traffic"),
        ))

    assert sorted(response.status_code for response in responses) == [200, 403]
    seeded.expire_all()
    active_assignments = list(seeded.scalars(select(Assignment).where(
        Assignment.job_id == job.id, Assignment.is_active.is_(True))))
    assert len(active_assignments) == 1
    assert active_assignments[0].electrician_id == candidate.id
    history = client.get(f"/api/portal/bookings/{job.id}/history", headers=portal["customer"]).json()
    assert len([event for event in history["events"] if event["action"] == "disturbed"]) == 1
    assert len([event for event in history["events"] if event["action"] == "reassigned"]) == 1


def test_disturbed_without_local_candidate_stays_active_for_dispatch(portal, client, seeded):
    job, candidate, _ = _prepare_disturbance(portal, client, seeded)
    candidate.service_localities = [ElectricianLocality(locality="Different locality")]
    seeded.commit()

    response = _disturb(client, portal, "Vehicle problem")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "unassigned"
    assert result["booking_stage"] == "reassignment_needed"
    assert result["assignment"] is None
    assert result["last_disruption"]["reason"] == "Vehicle problem"
    assert result["last_disruption"]["reassignment_status"] == "awaiting_reassignment"

    activity = client.get("/api/portal/admin/booking-activity").json()
    event = next(event for event in activity["events"] if event["job_id"] == job.id and event["action"] == "disturbed")
    assert event["needs_reassignment"] is True
    assert event["reassignment_status"] == "awaiting_manual_reassignment"
    assert seeded.scalar(select(Assignment.id).where(
        Assignment.job_id == job.id, Assignment.is_active.is_(True))) is None
    seeded.expire_all()
    assert seeded.get(Job, job.id).status == JobStatus.UNASSIGNED.value


@pytest.mark.parametrize("constraint", [
    "locality", "skills", "zone", "shift", "availability", "window", "travel", "overlap",
])
def test_disturbed_reassigns_same_locality_even_when_scheduler_rejects_constraints(
        portal, client, seeded, constraint):
    job, candidate, start = _prepare_disturbance(portal, client, seeded)
    if constraint == "locality":
        candidate.service_localities = [ElectricianLocality(locality="Elsewhere")]
    elif constraint == "skills":
        candidate.skills = []
    elif constraint == "zone":
        candidate.zones = []
    elif constraint == "shift":
        candidate.shifts = [Shift(day_of_week=(start.weekday() + 1) % 7,
                                  start_time=time(0, 0), end_time=time(23, 59))]
    elif constraint == "availability":
        override = seeded.get(AvailabilityOverride, candidate.id)
        if override is None:
            seeded.add(AvailabilityOverride(electrician_id=candidate.id, is_available=False))
        else:
            override.is_available = False
    elif constraint == "window":
        job.duration_minutes = 180
    elif constraint == "travel":
        candidate.home_lat, candidate.home_lon = 0.0, 0.0
    elif constraint == "overlap":
        blocker = seeded.scalar(select(Job).where(Job.id != job.id).limit(1))
        blocker.status = JobStatus.IN_PROGRESS.value
        blocker.actual_start = start - timedelta(hours=1)
        blocker.duration_minutes = 180
        blocker.lat, blocker.lon = job.lat, job.lon
        seeded.add(Assignment(job_id=blocker.id, electrician_id=candidate.id,
                              start=start - timedelta(hours=1), end=start + timedelta(hours=3),
                              travel_minutes=0, is_active=True))
    seeded.commit()

    response = _disturb(client, portal, f"Test {constraint} constraint")
    assert response.status_code == 200, response.text
    result = response.json()
    if constraint == "locality":
        assert result["booking_stage"] == "reassignment_needed"
        assert result["status"] == "unassigned"
        assert result["assignment"] is None
        assert seeded.scalar(select(Assignment.id).where(
            Assignment.job_id == job.id, Assignment.is_active.is_(True))) is None
    else:
        assert result["booking_stage"] == "awaiting_response"
        assert result["status"] == "assigned"
        assert result["assignment"]["electrician_id"] == candidate.id
        active = list(seeded.scalars(select(Assignment).where(
            Assignment.job_id == job.id, Assignment.is_active.is_(True))))
        assert len(active) == 1
        assert active[0].electrician_id == candidate.id


def test_disturbed_requires_an_accepted_booking_and_electrician_authorization(portal, client, seeded):
    pending = _disturb(client, portal, "Vehicle breakdown")
    assert pending.status_code == 409
    assert pending.json()["error"]["code"] == "BOOKING_NOT_ACCEPTED"
    assert client.post(f"/api/portal/electrician/bookings/{portal['job']['id']}/action",
                       json={"action": "disturbed", "reason": "Vehicle breakdown"},
                       headers=portal["customer"]).status_code == 403

    assert _act(client, portal, "accept").status_code == 200
    seeded.expire_all()
    job = seeded.get(Job, portal["job"]["id"])
    other = seeded.scalar(select(Electrician).where(Electrician.id != portal["eid"]).order_by(Electrician.id))
    job.active_assignment.electrician_id = other.id
    seeded.commit()
    wrong_electrician = _disturb(client, portal, "Vehicle breakdown")
    assert wrong_electrician.status_code == 403
    assert wrong_electrician.json()["error"]["code"] == "NOT_ASSIGNED"


def test_disturbed_is_not_available_after_work_starts_or_completes(portal, client, seeded):
    assert _act(client, portal, "accept").json()["booking_stage"] == "accepted"
    assert _act(client, portal, "start").json()["booking_stage"] == "in_progress"
    in_progress = _disturb(client, portal, "Vehicle breakdown")
    assert in_progress.status_code == 409
    assert in_progress.json()["error"]["code"] == "BOOKING_NOT_ACCEPTED"

    assert _act(client, portal, "complete").json()["booking_stage"] == "completed"
    completed = _disturb(client, portal, "Vehicle breakdown")
    assert completed.status_code == 409
    assert completed.json()["error"]["code"] == "BOOKING_NOT_ACCEPTED"

    job = seeded.get(Job, portal["job"]["id"])
    job.status = JobStatus.CANCELLED.value
    seeded.commit()
    cancelled = _disturb(client, portal, "Vehicle breakdown")
    assert cancelled.status_code == 409
    assert cancelled.json()["error"]["code"] == "BOOKING_NOT_ACCEPTED"


def test_dispatch_cannot_manually_reassign_customer_booking_outside_locality(portal, client, seeded):
    job, candidate, _ = _prepare_disturbance(portal, client, seeded)
    candidate.service_localities = [ElectricianLocality(locality="Different locality")]
    seeded.commit()

    response = client.post(f"/api/portal/admin/bookings/{job.id}/assign",
                           json={"electrician_id": candidate.id, "reason": "Manual review"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LOCALITY_MISMATCH"


def test_admin_endpoints_are_admin_only(portal, client):
    for who in ("customer", "electrician"):
        assert client.get("/api/portal/admin/booking-activity", headers=portal[who]).status_code == 403
        assert client.get("/api/portal/admin/overview", headers=portal[who]).status_code == 403


def test_overview_counts_inactive_electricians(seeded, client):
    before = client.get("/api/portal/admin/overview").json()
    assert before["electricians"] == before["active_electricians"] + before["inactive_electricians"]
    target = next(e for e in client.get("/api/electricians").json() if not e["in_progress_job_ids"])
    client.delete(f"/api/electricians/{target['id']}")
    after = client.get("/api/portal/admin/overview").json()
    assert after["electricians"] == before["electricians"]
    assert after["inactive_electricians"] == before["inactive_electricians"] + 1
