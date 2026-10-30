"""Role portal tests: customer request flow, electrician responses with reasons, admin activity and counts."""
from datetime import datetime, timedelta

import pytest


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
    assigned = client.get("/api/portal/electrician/bookings", headers=portal["electrician"]).json()["assigned"]
    assert any(j["id"] == job["id"] and j["customer_phone"] == "9800000000" for j in assigned)


@pytest.mark.parametrize("action", ["decline", "cancel", "customer_unavailable"])
def test_release_actions_require_reason(portal, client, action):
    for reason in (None, "", "   "):
        r = _act(client, portal, action, reason)
        assert r.status_code == 422 and r.json()["error"]["code"] == "REASON_REQUIRED"
    assert client.get(f"/api/jobs/{portal['job']['id']}").json()["status"] == "assigned"


def test_decline_is_recorded_for_admin_and_customer(portal, client):
    job_id = portal["job"]["id"]
    r = _act(client, portal, "decline", "Van broke down")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unassigned" and r.json()["booking_stage"] == "reassignment_needed"

    mine = next(j for j in client.get("/api/portal/customer/bookings", headers=portal["customer"]).json()
                if j["id"] == job_id)
    assert mine["booking_stage"] == "reassignment_needed"
    history = client.get(f"/api/portal/bookings/{job_id}/history", headers=portal["customer"]).json()
    assert any(e["action"] == "decline" and e["reason"] == "Van broke down" for e in history["events"])

    activity = client.get("/api/portal/admin/booking-activity").json()
    event = next(e for e in activity["events"] if e["job_id"] == job_id)
    assert event["electrician_id"] == portal["eid"] and event["reason"] == "Van broke down"
    assert event["needs_reassignment"] is True and activity["needs_reassignment"] >= 1
    assert client.get("/api/portal/admin/overview").json()["pending_dispatch"] >= 1


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
