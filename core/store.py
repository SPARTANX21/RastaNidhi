"""Tiny JSON-file store for the multi-user demo: users, sessions, audit reviews, contractor evidence, citizen reports."""
from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime
from pathlib import Path

PATH = Path(os.environ.get("RUPEE_STORE", Path(__file__).resolve().parents[1] / "store.json"))
DEMO_OTP = "1234"
ROLES = ["Admin", "Ward Officer", "Contractor", "Auditor / Verifier", "Citizen", "Researcher"]

_lock = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load() -> dict:
    if PATH.exists():
        return json.loads(PATH.read_text(encoding="utf-8"))
    return {"users": {}, "sessions": {}, "reviews": {}, "evidence": {}, "reports": [], "activity": []}


def _save(db: dict) -> None:
    PATH.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")


def _log(db: dict, who: str, what: str) -> None:
    db["activity"] = (db.get("activity", []) + [{"at": _now(), "who": who, "what": what}])[-200:]


def login(email: str, role: str, otp: str, ward: str | None, contractor_id: str | None) -> dict:
    if otp != DEMO_OTP:
        raise ValueError("Incorrect OTP. Use 1234 for this demo.")
    if role not in ROLES:
        raise ValueError("Unknown role.")
    if role == "Ward Officer" and not ward:
        raise ValueError("Ward Officers must pick their ward.")
    if role == "Contractor" and not contractor_id:
        raise ValueError("Contractors must pick their company.")
    with _lock:
        db = _load()
        u = db["users"].get(email)
        if u and not u.get("active", True):
            raise PermissionError("This account has been deactivated by an admin.")
        if u and u["role"] != role and u.get("locked_role"):
            raise PermissionError(f"An admin has fixed this account's role to {u['role']}.")
        u = (u or {"created": _now(), "active": True}) | {
            "email": email, "role": role, "ward": ward, "contractor_id": contractor_id, "last_login": _now()}
        db["users"][email] = u
        token = secrets.token_urlsafe(24)
        db["sessions"][token] = email
        _log(db, email, f"signed in as {role}")
        _save(db)
    return {"token": token, "user": u}


def user_for(token: str | None) -> dict | None:
    if not token:
        return None
    db = _load()
    email = db["sessions"].get(token)
    u = db["users"].get(email) if email else None
    return u if u and u.get("active", True) else None


def logout(token: str) -> None:
    with _lock:
        db = _load()
        db["sessions"].pop(token, None)
        _save(db)


def all_data() -> dict:
    return _load()


def add_review(wo: str, who: str, status: str, note: str) -> dict:
    item = {"at": _now(), "by": who, "status": status, "note": note}
    with _lock:
        db = _load()
        db["reviews"].setdefault(wo, []).append(item)
        _log(db, who, f"marked {wo} as {status}")
        _save(db)
    return item


def add_evidence(wo: str, who: str, role: str, note: str) -> dict:
    item = {"at": _now(), "by": who, "role": role, "note": note}
    with _lock:
        db = _load()
        db["evidence"].setdefault(wo, []).append(item)
        _log(db, who, f"submitted evidence on {wo}")
        _save(db)
    return item


def add_report(who: str, report: dict) -> dict:
    with _lock:
        db = _load()
        rid = f"CP-{len(db['reports']) + 1:05d}"
        item = report | {"report_id": rid, "by": who, "at": _now(), "status": "Received"}
        db["reports"].append(item)
        _log(db, who, f"filed citizen report {rid}")
        _save(db)
    return item


DEFAULT_SETTINGS = {
    "claude_enabled": True,
    "auto_flag_dlp": True,
    "human_review_before_publish": True,
    "multilingual_parsing": True,
    "weekly_digest": False,
}


def get_settings() -> dict:
    return DEFAULT_SETTINGS | _load().get("settings", {})


def set_settings(admin: str, changes: dict) -> dict:
    with _lock:
        db = _load()
        s = DEFAULT_SETTINGS | db.get("settings", {}) | {k: bool(v) for k, v in changes.items() if k in DEFAULT_SETTINGS}
        db["settings"] = s
        _log(db, admin, f"changed settings: {changes}")
        _save(db)
    return s


def add_notice(target: str, kind: str, who: str, text: str) -> dict:
    """Record a recovery notice as issued (target = work order id or road id)."""
    item = {"at": _now(), "by": who, "kind": kind, "target": target, "text": text}
    with _lock:
        db = _load()
        db.setdefault("notices", []).append(item)
        if kind == "work_order":  # also show it on the work order's trail
            db["evidence"].setdefault(target, []).append(
                {"at": item["at"], "by": who, "role": "Ward Officer", "note": "📨 Recovery notice issued to the contractor."})
        _log(db, who, f"issued recovery notice for {target}")
        _save(db)
    return item


def update_report(who: str, report_id: str, status: str, work_order_id: str | None = None, note: str = "") -> dict:
    """Move a citizen report through its lifecycle (REQUIREMENTS §7.4) and keep the full history."""
    with _lock:
        db = _load()
        for r in db["reports"]:
            if r["report_id"] == report_id:
                r.setdefault("history", [{"status": "Open", "at": r["at"], "by": r["by"]}])
                r["status"] = status
                r["updated_by"] = who
                r["updated_at"] = _now()
                if work_order_id:
                    r["work_order_id"] = work_order_id
                r["history"].append({"status": status, "at": r["updated_at"], "by": who, "note": note,
                                     **({"work_order_id": work_order_id} if work_order_id else {})})
                _log(db, who, f"set citizen report {report_id} to {status}")
                _save(db)
                return r
    raise KeyError(report_id)


def upsert_project(who: str, project: dict) -> dict:
    """Create a project (ward budget allocation) or edit one — seeded projects get an override record."""
    with _lock:
        db = _load()
        items = db.setdefault("projects", [])
        cur = next((x for x in items if x["id"] == project.get("id")), None)
        if cur:
            cur.update({k: v for k, v in project.items() if k in {"allocated_inr", "status", "notes", "season", "ward_code", "created_by", "created_at"}})
            cur["updated_by"], cur["updated_at"] = who, _now()
            item = cur
        else:
            item = project | {"id": project.get("id") or f"PRJ-{len(items) + 1:04d}", "created_by": project.get("created_by", who),
                              "created_at": project.get("created_at", _now())}
            items.append(item)
        _log(db, who, f"saved project {item['id']} (ward {item['ward_code']}, {item['season']})")
        _save(db)
    return item


def add_submission(who: str, sub: dict) -> dict:
    with _lock:
        db = _load()
        items = db.setdefault("submissions", [])
        item = sub | {"id": f"SUB-{len(items) + 1:04d}", "by": who, "at": _now(), "review": None}
        items.append(item)
        _log(db, who, f"submitted progress on {sub['work_order_id']}: {sub['status']}")
        _save(db)
    return item


def review_submission(who: str, sub_id: str, decision: str, note: str) -> dict:
    with _lock:
        db = _load()
        s = next((x for x in db.get("submissions", []) if x["id"] == sub_id), None)
        if not s:
            raise KeyError(sub_id)
        s.update({"review": decision, "review_note": note, "reviewed_by": who, "reviewed_at": _now()})
        _log(db, who, f"{decision.lower()} contractor submission {sub_id} on {s['work_order_id']}")
        _save(db)
    return s


def add_pin(who: str, role: str, pin: dict) -> dict:
    with _lock:
        db = _load()
        pins = db.setdefault("pins", [])
        item = pin | {"id": f"PIN-{len(pins) + 1:04d}-{secrets.token_hex(2)}", "by": who, "role": role, "at": _now()}
        pins.append(item)
        _log(db, who, f"dropped map pin '{pin.get('title', '')}'")
        _save(db)
    return item


def delete_pin(who: str, role: str, pin_id: str) -> bool:
    with _lock:
        db = _load()
        pins = db.get("pins", [])
        p = next((x for x in pins if x["id"] == pin_id), None)
        if not p:
            raise KeyError(pin_id)
        if p["by"] != who and role != "Admin":
            raise PermissionError("Only the author or an admin can remove this pin.")
        db["pins"] = [x for x in pins if x["id"] != pin_id]
        _log(db, who, f"removed map pin {pin_id}")
        _save(db)
    return True


def update_user(admin: str, email: str, changes: dict) -> dict:
    with _lock:
        db = _load()
        if email not in db["users"]:
            raise KeyError(email)
        allowed = {k: v for k, v in changes.items() if k in {"role", "ward", "contractor_id", "active", "locked_role"}}
        db["users"][email].update(allowed)
        if allowed.get("active") is False:  # kill their sessions
            db["sessions"] = {t: e for t, e in db["sessions"].items() if e != email}
        _log(db, admin, f"updated user {email}: {allowed}")
        _save(db)
        return db["users"][email]
