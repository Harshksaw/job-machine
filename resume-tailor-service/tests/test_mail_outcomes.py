import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mail_outcomes.py"
_spec = importlib.util.spec_from_file_location("mail_outcomes_under_test", _PATH)
mail_outcomes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mail_outcomes)


def _jobs():
    jobs = [
        {"id": "j1", "company": "Acme Inc", "role": "Backend Engineer", "status": "applied", "job_url": "u1"},
        {"id": "j2", "company": "Globex", "role": "Data Engineer", "status": "applied", "job_url": "u2"},
        {"id": "j3", "company": "Globex", "role": "ML Engineer", "status": "applied", "job_url": "u3"},
        {"id": "j4", "company": "Initech", "role": "Engineer", "status": "offer", "job_url": "u4"},
    ]
    return jobs, {j["id"]: j for j in jobs}


def _event(**extra):
    return {"id": "m1", "company": "Acme", "role": "", "date": "2026-02-01", "outcome": "rejected",
            "confident": True, "note": "no", **extra}


def test_plan_writes_and_sets_status():
    jobs, by_id = _jobs()
    decision = mail_outcomes.plan(_event(), jobs, by_id)
    assert decision["action"] == "write" and decision["job"]["id"] == "j1"
    assert decision["set_status"] == "rejected" and decision["kind"] == "reply"


def test_plan_holds_uncertain_unless_asked():
    jobs, by_id = _jobs()
    assert mail_outcomes.plan(_event(confident=False), jobs, by_id)["action"] == "held"
    assert mail_outcomes.plan(_event(confident=False), jobs, by_id, include_uncertain=True)["action"] == "write"


def test_plan_reports_unmatched_and_ambiguous():
    jobs, by_id = _jobs()
    assert mail_outcomes.plan(_event(company="Umbrella"), jobs, by_id)["reason"] == "no dossier"
    ambiguous = mail_outcomes.plan(_event(company="Globex"), jobs, by_id)
    assert ambiguous["action"] == "unmatched" and ambiguous["reason"].startswith("ambiguous")
    exact = mail_outcomes.plan(_event(company="Globex", role="ML Engineer"), jobs, by_id)
    assert exact["action"] == "write" and exact["job"]["id"] == "j3"


def test_plan_never_downgrades_an_offer_and_activity_is_keyed_on_message_id():
    jobs, by_id = _jobs()
    decision = mail_outcomes.plan(_event(company="Initech"), jobs, by_id)
    assert decision["action"] == "write" and decision["set_status"] is None
    act = mail_outcomes.activity(_event(), "Mail sync")
    assert act["external_id"] == "gmail:m1" and act["occurred_at"] == "2026-02-01T00:00:00+00:00"
    assert act["kind"] == "reply" and act["title"] == "Email: rejected"
