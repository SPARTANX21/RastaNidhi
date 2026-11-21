r"""Capture homepage + role dashboard screenshots for the RastaNidhi documentation.

Run against a throwaway server so the demo store.json is untouched:
    set RUPEE_STORE=%TEMP%\docs_store.json & set PORT=8077 & python server.py
    python tools/capture_screens.py http://127.0.0.1:8077
Needs Playwright with Microsoft Edge (channel="msedge").
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8077"
OUT = Path(__file__).resolve().parents[1] / "docs" / "screens"
OUT.mkdir(parents=True, exist_ok=True)


def call(path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(BASE + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


opts = call("/api/options")
contractor = opts["contractors"][0]["contractor_id"]
SHOTS = {  # role -> (login extras, [(page key, file name)])
    "Admin": ({}, [("overview", "admin_overview"), ("users", "admin_users"), ("settings", "admin_settings")]),
    "Ward Officer": ({"ward": "L"}, [("ward", "officer_ward"), ("planner", "officer_planner"), ("map", "officer_map")]),
    "Contractor": ({"contractor_id": contractor}, [("jobs", "contractor_jobs"), ("scorecards", "contractor_scorecard")]),
    "Auditor / Verifier": ({}, [("review", "auditor_review"), ("reviewdash", "auditor_dashboard")]),
    "Citizen": ({"ward": "L"}, [("track", "citizen_track"), ("ask", "citizen_ask"), ("reports", "citizen_report")]),
    "Researcher": ({}, [("season", "researcher_season"), ("findings", "researcher_findings")]),
}

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge")
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
    page.goto(BASE + "/")
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT / "home_hero.png"))
    for role, (extra, pages) in SHOTS.items():
        email = role.split()[0].lower() + "@demo.in"
        tok = call("/api/login", dict(email=email, role=role, otp="1234", **extra))["token"]
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
        pg = ctx.new_page()
        pg.goto(BASE + "/")
        pg.evaluate(f"sessionStorage.setItem('cp_token', '{tok}')")
        for key, name in pages:
            pg.goto(f"{BASE}/dashboard#{key}")
            pg.wait_for_selector(".page-title", timeout=60000)
            try:  # most pages clear their loaders quickly; a few keep a lazy panel, so don't block on those
                pg.wait_for_function("() => !document.querySelector('#view .loading, #view .skel')", timeout=12000)
            except Exception:
                print("  (still loading after 12 s, capturing anyway)", name)
            pg.wait_for_timeout(2500 if key == "map" else 1500)
            pg.screenshot(path=str(OUT / f"{name}.png"))
            print("saved", name)
        ctx.close()
    browser.close()
