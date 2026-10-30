"""Generate and load the DispatchGrid demo dataset.

    python -m app.seed               # reset the database and load seed data
    python -m app.seed --schedule    # ...and run an initial scheduling pass

Dates are relative to the moment the script runs: jobs are spread over the next three days
(D1..D3), a few jobs are already in progress / completed today. The data is generated with a
fixed random seed, so the same day always produces the same dataset.

Built-in problem cases (all electrician work):
  * EL-001 Arjun Rao is the only high-voltage electrician  -> "skilled electrician unavailable"
  * two high-priority solar jobs in WST compete for the same slot
  * a cluster of high-priority panel upgrades in STH exceeds local capacity (currently infeasible)
  * jobs that can never be assigned: missing skill combination, uncovered zone, out-of-hours
    window, only qualified electrician unavailable, unachievable SLA, unreachable in time
"""
import argparse
import random
from datetime import date, datetime, time, timedelta

from app.database import SessionLocal, reset_db
from app.models import (
    Assignment,
    Electrician,
    Job,
    ServiceZone,
    Shift,
    Skill,
    UnavailablePeriod,
)
from app.models.enums import JobStatus
from app.services.auth import ensure_default_user

SKILLS = [
    ("residential_wiring", "Residential wiring"),
    ("commercial_wiring", "Commercial wiring"),
    ("industrial_wiring", "Industrial / three-phase wiring"),
    ("panel_upgrade", "Distribution board & panel upgrades"),
    ("fault_finding", "Fault finding & diagnostics"),
    ("lighting", "Lighting installation"),
    ("ev_charger", "EV charger installation"),
    ("solar_pv", "Solar PV & inverters"),
    ("generator", "Generator & changeover switches"),
    ("fire_alarm", "Fire alarm & emergency lighting"),
    ("data_cabling", "Data & low-voltage cabling"),
    ("high_voltage", "High-voltage / transformer work"),
    ("smart_home", "Smart home & automation"),
    ("inspection_testing", "Inspection, testing & certification"),
]

ZONES = [
    ("CEN", "Central", 12.9716, 77.5946),
    ("NTH", "North", 13.0350, 77.5970),
    ("STH", "South", 12.9050, 77.5850),
    ("EST", "East", 12.9750, 77.6650),
    ("WST", "West", 12.9750, 77.5250),
    ("OUT", "Airport Outskirts", 13.1700, 77.6800),
]
ZONE_CENTER = {z[0]: (z[2], z[3]) for z in ZONES}

# (name, skills, zones, home zone, shift (start, end), overtime minutes, day off (D-index or weekday rule))
ELECTRICIANS = [
    ("Arjun Rao", ["residential_wiring", "commercial_wiring", "industrial_wiring", "panel_upgrade", "fault_finding",
                   "high_voltage", "generator", "inspection_testing", "lighting", "fire_alarm"],
     ["CEN", "NTH", "EST"], "CEN", (8, 17), 60),
    ("Priya Nair", ["residential_wiring", "lighting", "smart_home", "data_cabling"], ["CEN", "EST"], "EST", (9, 17), 30),
    ("Rahul Menon", ["commercial_wiring", "panel_upgrade", "fault_finding", "inspection_testing"], ["STH", "CEN"], "STH", (8, 16), 0),
    ("Sneha Kulkarni", ["solar_pv", "residential_wiring", "ev_charger"], ["WST", "CEN"], "WST", (8, 16), 30),
    ("Vikram Shetty", ["residential_wiring", "fault_finding", "lighting"], ["NTH", "CEN"], "NTH", (8, 16), 0),
    ("Anita Desai", ["fire_alarm", "commercial_wiring", "data_cabling", "inspection_testing"], ["CEN", "NTH"], "CEN", (9, 17), 0),
    ("Karthik Iyer", ["panel_upgrade", "residential_wiring", "fault_finding"], ["STH"], "STH", (8, 16), 30),
    ("Deepa Reddy", ["ev_charger", "smart_home", "residential_wiring", "lighting"], ["EST", "NTH"], "EST", (10, 18), 0),
    ("Mohammed Faiz", ["generator", "industrial_wiring", "commercial_wiring", "fault_finding"], ["EST", "STH"], "EST", (8, 16), 60),
    ("Lakshmi Pillai", ["residential_wiring", "lighting", "fault_finding", "smart_home"], ["WST", "STH"], "WST", (9, 17), 0),
    ("Suresh Gowda", ["residential_wiring", "fault_finding", "lighting"], ["OUT", "NTH"], "NTH", (8, 16), 30),
    ("Rekha Joshi", ["ev_charger", "residential_wiring"], ["OUT", "NTH"], "CEN", (8, 16), 0),
    ("Imran Khan", ["commercial_wiring", "data_cabling", "fire_alarm", "lighting"], ["EST", "CEN"], "CEN", (11, 19), 0),
    ("Divya Hegde", ["solar_pv", "panel_upgrade", "inspection_testing"], ["NTH", "EST"], "NTH", (8, 16), 30),
    ("Naveen Kumar", ["residential_wiring", "panel_upgrade", "lighting", "ev_charger"], ["STH", "WST"], "STH", (9, 17), 0),
    ("Farah Sheikh", ["smart_home", "data_cabling", "lighting"], ["CEN", "WST"], "CEN", (10, 18), 0),
    ("Ganesh Bhat", ["industrial_wiring", "generator", "panel_upgrade", "fault_finding"], ["NTH", "OUT"], "NTH", (8, 16), 60),
    ("Meera Krishnan", ["residential_wiring", "commercial_wiring", "fault_finding", "lighting", "inspection_testing"], ["CEN", "STH", "WST"], "CEN", (8, 16), 0),
    ("Ravi Patil", ["fire_alarm", "commercial_wiring", "lighting"], ["WST", "STH"], "WST", (11, 19), 30),
    ("Asha Fernandes", ["residential_wiring", "ev_charger", "solar_pv", "lighting"], ["EST", "CEN"], "EST", (9, 17), 0),
]

# Job templates: (title, skills, duration range, priority weights low/medium/high/urgent)
TEMPLATES = [
    ("Replace faulty wall sockets", ["residential_wiring"], (30, 60), (5, 4, 1, 0)),
    ("Rewire kitchen circuit", ["residential_wiring"], (90, 180), (3, 5, 2, 0)),
    ("Trace tripping RCD", ["fault_finding"], (45, 120), (1, 4, 4, 1)),
    ("Total power loss - diagnose", ["fault_finding", "residential_wiring"], (60, 120), (0, 2, 4, 3)),
    ("Install LED downlights", ["lighting"], (60, 150), (5, 4, 1, 0)),
    ("Office lighting retrofit", ["lighting", "commercial_wiring"], (120, 240), (3, 5, 2, 0)),
    ("Upgrade distribution board", ["panel_upgrade"], (120, 240), (1, 4, 4, 0)),
    ("Install home EV charger", ["ev_charger"], (90, 180), (2, 6, 2, 0)),
    ("Solar inverter fault", ["solar_pv"], (60, 120), (1, 4, 4, 1)),
    ("Install rooftop solar isolator", ["solar_pv"], (90, 150), (3, 5, 2, 0)),
    ("Generator changeover switch service", ["generator"], (60, 120), (2, 4, 3, 1)),
    ("Fire alarm panel fault", ["fire_alarm"], (60, 120), (0, 3, 4, 3)),
    ("Emergency lighting test", ["fire_alarm", "inspection_testing"], (60, 120), (3, 5, 2, 0)),
    ("Structured data cabling", ["data_cabling"], (120, 240), (4, 5, 1, 0)),
    ("Smart switch & hub install", ["smart_home"], (60, 120), (5, 4, 1, 0)),
    ("Electrical safety certificate (EICR)", ["inspection_testing"], (90, 180), (3, 5, 2, 0)),
    ("Three-phase machine hookup", ["industrial_wiring"], (120, 240), (1, 4, 4, 1)),
    ("Shop fit-out wiring", ["commercial_wiring"], (150, 240), (2, 5, 3, 0)),
]

CUSTOMERS = ["Sharma Residence", "Green Leaf Cafe", "Patel Apartments", "Sunrise School", "Metro Clinic",
             "Lakeview Villas", "City Bakery", "Nova Tech Park", "Orchid Hotel", "Hill Side PG",
             "Sai Textiles", "Blue Moon Salon", "Prestige Towers", "Gupta Hardware", "Silver Oak Homes"]

PRIORITIES = ["low", "medium", "high", "urgent"]


def _at(day: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(day, time(h, m))


def _near(rng: random.Random, zone: str, spread: float = 0.018) -> tuple[float, float]:
    lat, lon = ZONE_CENTER[zone]
    return round(lat + rng.uniform(-spread, spread), 5), round(lon + rng.uniform(-spread, spread), 5)


def build(db, now: datetime | None = None, rng_seed: int = 42) -> dict:
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    rng = random.Random(rng_seed)
    today = now.date()
    d1, d2, d3 = (today + timedelta(days=i) for i in (1, 2, 3))

    skills = {code: Skill(code=code, name=name) for code, name in SKILLS}
    zones = {code: ServiceZone(code=code, name=name, center_lat=lat, center_lon=lon) for code, name, lat, lon in ZONES}
    db.add_all(list(skills.values()) + list(zones.values()))
    db.flush()

    techs: list[Electrician] = []
    for i, (name, sk, zs, home, (sh, eh), ot) in enumerate(ELECTRICIANS, start=1):
        lat, lon = _near(rng, home, 0.01)
        first = name.split()[0].lower()
        e = Electrician(employee_code=f"EL-{i:03d}", name=name, phone=f"+91 98450 {10000 + i * 137:05d}",
                        email=f"{first}.{i}@dispatchgrid.example", home_lat=lat, home_lon=lon,
                        max_overtime_minutes=ot, active=True)
        e.skills = [skills[s] for s in sk]
        e.zones = [zones[z] for z in zs]
        # One rotating day off; electricians 1, 11, 12 work every day so the crafted cases hold.
        day_off = None if i in (1, 11, 12) else (i % 7)
        e.shifts = [Shift(day_of_week=d, start_time=time(sh), end_time=time(eh)) for d in range(7) if d != day_off]
        techs.append(e)
    db.add_all(techs)
    db.flush()
    by_code = {e.employee_code: e for e in techs}

    db.add_all([
        UnavailablePeriod(electrician_id=by_code["EL-005"].id, start=_at(d1, 8), end=_at(d1, 13), reason="Medical appointment"),
        UnavailablePeriod(electrician_id=by_code["EL-012"].id, start=_at(d2, 0), end=_at(d3, 0), reason="Annual leave"),
        UnavailablePeriod(electrician_id=by_code["EL-014"].id, start=_at(d1, 12), end=_at(d1, 14), reason="Safety training"),
        UnavailablePeriod(electrician_id=by_code["EL-008"].id, start=_at(d3, 10), end=_at(d3, 18), reason="Vehicle service"),
        UnavailablePeriod(electrician_id=by_code["EL-019"].id, start=_at(d2, 11), end=_at(d2, 15), reason="Union meeting"),
    ])

    jobs: list[Job] = []

    def add_job(title, sk, zone, priority, duration, ws, we, sla, status=JobStatus.PENDING.value, loc=None, customer=None):
        lat, lon = loc or _near(rng, zone)
        j = Job(title=title, customer_name=customer or rng.choice(CUSTOMERS),
                address=f"{rng.randint(1, 250)} {rng.choice(['MG Road', 'Main Street', '4th Cross', 'Ring Road', 'Park Lane', '12th Main'])}, {zones[zone].name}",
                lat=lat, lon=lon, zone_id=zones[zone].id, priority=priority, duration_minutes=duration,
                window_start=ws, window_end=we, sla_deadline=sla, status=status)
        j.required_skills = [skills[s] for s in sk]
        jobs.append(j)
        return j

    # ---- crafted cases --------------------------------------------------------------
    add_job("Transformer tap change + solar inverter integration", ["high_voltage", "solar_pv"], "NTH", "high",
            180, _at(d1, 9), _at(d1, 16), _at(d1, 17))                                             # MISSING_SKILLS
    add_job("Fire alarm panel fault at warehouse", ["fire_alarm"], "OUT", "high",
            90, _at(d1, 9), _at(d1, 15), _at(d1, 16))                                              # NO_ZONE_ELIGIBLE
    add_job("After-hours shop lighting changeover", ["lighting"], "CEN", "medium",
            90, _at(d1, 21), _at(d1, 23, 30), _at(d2, 9))                                          # SHIFT_CONSTRAINTS
    add_job("EV charger commissioning at logistics hub", ["ev_charger"], "OUT", "medium",
            120, _at(d2, 9), _at(d2, 13), _at(d2, 18))                                             # ELECTRICIAN_UNAVAILABLE
    add_job("Cargo terminal power loss", ["fault_finding"], "OUT", "urgent",
            60, _at(d1, 8), _at(d1, 12), _at(d1, 8, 30))                                           # SLA_UNACHIEVABLE
    add_job("Airport hotel lift supply isolation", ["residential_wiring"], "OUT", "medium",
            50, _at(d3, 8), _at(d3, 9), _at(d3, 12), loc=(13.21, 77.71))                            # TRAVEL_TIME
    # Two high-priority solar jobs competing for the same slot in WST.
    for n in range(2):
        add_job(f"Solar inverter shutdown - site {'AB'[n]}", ["solar_pv"], "WST", "high",
                90, _at(d1, 10), _at(d1, 12), _at(d1, 12, 30))
    # Capacity crunch: panel upgrades in STH, all in the same morning window.
    for n in range(5):
        add_job(f"Urgent board replacement after flooding #{n + 1}", ["panel_upgrade"], "STH", "high" if n < 4 else "medium",
                120, _at(d1, 8), _at(d1, 12), _at(d1, 13) if n < 4 else _at(d1, 18))
    # Work only the high-voltage specialist (EL-001) can do.
    add_job("HV switchgear inspection", ["high_voltage", "inspection_testing"], "CEN", "high",
            120, _at(d1, 9), _at(d1, 14), _at(d1, 16))
    add_job("Substation feeder fault", ["high_voltage", "fault_finding"], "EST", "urgent",
            90, _at(d1, 13), _at(d1, 17), _at(d1, 17))
    add_job("Transformer oil test & reconnect", ["high_voltage"], "NTH", "medium",
            120, _at(d2, 9), _at(d2, 16), _at(d2, 18))

    # ---- in-progress and completed work (today) -----------------------------------
    started = now - timedelta(minutes=40)
    in_progress = [
        ("Main breaker replacement", ["panel_upgrade"], "CEN", "high", 120, "EL-018"),
        ("Restaurant kitchen circuit fault", ["fault_finding"], "EST", "urgent", 90, "EL-009"),
        ("Rewire bedroom circuits", ["residential_wiring"], "WST", "medium", 150, "EL-010"),
    ]
    for title, sk, zone, prio, dur, code in in_progress:
        j = add_job(title, sk, zone, prio, dur, started - timedelta(minutes=20), started + timedelta(minutes=dur + 120),
                    started + timedelta(minutes=dur + 180), status=JobStatus.IN_PROGRESS.value)
        j.actual_start = started
        j.assignments = [Assignment(electrician_id=by_code[code].id, start=started, end=started + timedelta(minutes=dur),
                                    travel_minutes=0, travel_from="dispatched manually", is_active=True,
                                    explanation="Dispatched before DispatchGrid was introduced.")]
    done_start = now - timedelta(hours=4)
    for title, sk, zone, code in [("Socket replacement", ["residential_wiring"], "CEN", "EL-002"),
                                  ("Emergency light test", ["fire_alarm"], "NTH", "EL-006")]:
        j = add_job(title, sk, zone, "low", 60, done_start - timedelta(hours=1), done_start + timedelta(hours=3),
                    done_start + timedelta(hours=4), status=JobStatus.COMPLETED.value)
        j.actual_start, j.actual_end = done_start, done_start + timedelta(minutes=55)
        j.assignments = [Assignment(electrician_id=by_code[code].id, start=j.actual_start, end=j.actual_end,
                                    travel_minutes=0, travel_from="dispatched manually", is_active=True)]
    for title in ("Doorbell transformer swap", "Garden lighting quote visit"):
        j = add_job(title, ["lighting"], "WST", "low", 45, _at(d1, 9), _at(d1, 17), _at(d2, 17),
                    status=JobStatus.CANCELLED.value)
        j.cancel_reason = "Customer cancelled"

    # ---- regular random demand to reach 100 jobs --------------------------------------
    zone_weights = [("CEN", 25), ("NTH", 20), ("STH", 18), ("EST", 17), ("WST", 15), ("OUT", 5)]
    zone_pool = [z for z, w in zone_weights for _ in range(w)]
    while len(jobs) < 100:
        title, sk, (dmin, dmax), pw = rng.choice(TEMPLATES)
        zone = rng.choice(zone_pool)
        if zone == "OUT":
            title, sk, (dmin, dmax), pw = rng.choice([t for t in TEMPLATES if set(t[1]) <= {"residential_wiring", "fault_finding", "lighting", "ev_charger"}])
        priority = rng.choices(PRIORITIES, weights=pw)[0]
        duration = rng.randrange(dmin, dmax + 1, 15)
        day = rng.choice([d1, d1, d2, d2, d3])
        start_h = rng.randint(8, 14)
        ws = _at(day, start_h, rng.choice([0, 30]))
        length = max(duration + 30, rng.choice([120, 180, 240, 300, 360]))
        we = min(ws + timedelta(minutes=length), _at(day, 19))
        if (we - ws).total_seconds() / 60 < duration:
            ws = we - timedelta(minutes=duration + 30)
        if priority in ("urgent", "high"):
            sla = we + timedelta(minutes=rng.choice([0, 30, 60]))
        else:
            sla = we + timedelta(minutes=rng.choice([-60, 0, 120, 240, 1440]))
            sla = max(sla, ws + timedelta(minutes=duration + 15))
        add_job(title, sk, zone, priority, duration, ws, we, sla)

    db.add_all(jobs)
    db.flush()
    for j in jobs:
        j.job_number = f"JOB-{j.id:05d}"
    db.commit()
    return {"skills": len(skills), "zones": len(zones), "electricians": len(techs), "jobs": len(jobs),
            "planning_days": [d.isoformat() for d in (d1, d2, d3)]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset the database and load DispatchGrid seed data.")
    parser.add_argument("--schedule", action="store_true", help="run an initial scheduling pass after seeding")
    args = parser.parse_args()

    reset_db()
    with SessionLocal() as db:
        ensure_default_user(db)
        summary = build(db)
        print(f"Seeded {summary}")
        if args.schedule:
            from app.services.scheduling_service import execute_run, scheduler_lock

            with scheduler_lock():
                run = execute_run(db, trigger="seed")
            print(f"Initial scheduling run {run.id}: {run.metrics}")


if __name__ == "__main__":
    main()
