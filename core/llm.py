"""Claude layer. Numbers are always computed in pandas; Claude only explains them in plain language.

Every function degrades to a template when no credentials are configured, so the app works offline.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"

FAIRNESS = (
    "You write for Mumbai citizens and corporators. Use only the numbers given to you; never invent figures. "
    "Cite work order IDs as evidence when you mention a specific job. Be fair: mention context such as "
    "low-lying wards, heavy rain or tide that may explain poor results. Never accuse anyone of corruption or fraud; "
    "say a job 'needs review' or 'should be checked'. All data is synthetic and contractors are fictional. "
    "Use ₹ with lakh/crore. Plain language, short sentences, no jargon."
)


def has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or (Path.home() / ".config" / "anthropic").exists())


_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def reset_client():
    global _client
    _client = None


def _text(resp) -> str:
    if resp.stop_reason == "refusal":
        return "_Claude declined this request._"
    out = "".join(b.text for b in resp.content if b.type == "text").strip()
    if resp.stop_reason == "max_tokens":
        out += "\n\n_(cut off – answer hit the length limit)_"
    return out


def ask(system: str, prompt: str, effort: str = "medium", max_tokens: int = 8000) -> str:
    """One Claude call with server-side refusal fallback; falls back to a plain call if the beta isn't available."""
    kw = dict(model=MODEL, max_tokens=max_tokens, system=system,
              messages=[{"role": "user", "content": prompt}], output_config={"effort": effort})
    try:
        try:
            resp = client().beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
        except anthropic.BadRequestError:
            resp = client().messages.create(**kw)
        return _text(resp)
    except anthropic.AuthenticationError:
        return "⚠️ Claude: invalid API key. Set it in the sidebar."
    except anthropic.RateLimitError:
        return "⚠️ Claude is rate-limited right now. Try again in a minute."
    except anthropic.APIStatusError as e:
        return f"⚠️ Claude API error ({e.status_code}): {e.message}"
    except anthropic.APIConnectionError:
        return "⚠️ Could not reach the Claude API (network)."


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, indent=1)


# ---------------------------------------------------------------- narratives

def ward_memo(ward_row: dict, trail: dict, flags_sample: list[dict], top_plan: list[dict], language: str) -> str:
    prompt = (
        f"Write a one-page monsoon road-repair report for ward {ward_row['ward_code']} ({ward_row['ward_name']}) "
        f"in {language}. Sections: 1) Where the money went 2) Did the fixes last 3) What needs review "
        f"4) Where the next rupee should go. Max 350 words, use bullet points.\n\n"
        f"WARD SUMMARY:\n{_j(ward_row)}\n\nSPEND BY CONTRACTOR:\n{_j(trail['by_contractor'])}\n\n"
        f"SPEND BY METHOD:\n{_j(trail['by_method'])}\n\nAUDIT FLAGS (sample):\n{_j(flags_sample)}\n\n"
        f"TOP OPEN ISSUES BY RISK:\n{_j(top_plan)}"
    )
    return ask(FAIRNESS, prompt, effort="medium")


def contractor_card(row: dict, flags_sample: list[dict], language: str) -> str:
    prompt = (
        f"Write a fair, plain-language scorecard in {language} for this contractor, for a citizen audience. "
        "Cover speed (SLA), how long repairs lasted (compare observed vs expected re-open rate, which already "
        "accounts for flood-prone wards and heavy rain), cost vs the rate card, and ONE concrete thing to improve. "
        f"Under 150 words, no accusations.\n\nSCORECARD:\n{_j(row)}\n\nEXAMPLE FLAGS:\n{_j(flags_sample)}"
    )
    return ask(FAIRNESS, prompt, effort="low", max_tokens=4000)


def explain_flags(flags: list[dict]) -> str:
    prompt = ("These audit flags were raised by deterministic rules. For a ward officer, group them, explain in "
              "plain words what to check first and why, and what document would clear each one (bill, measurement "
              f"book, DLP register). Max 250 words.\n\n{_j(flags)}")
    return ask(FAIRNESS, prompt, effort="medium")


def plan_explainer(ward: str, budget: float, plan: list[dict], chronic: list[dict], language: str) -> str:
    prompt = (f"Ward {ward} has ₹{budget:,.0f} left in its monsoon repair budget. Explain in {language}, for the "
              "corporator, the recommended order of repairs and why, which methods to use (prefer durable fixes), "
              "which jobs the original DLP contractor should do for free, which roads should be resurfaced "
              "instead of patched again. "
              f"Max 300 words.\n\nRANKED PLAN:\n{_j(plan)}\n\nCHRONIC ROADS:\n{_j(chronic)}")
    return ask(FAIRNESS, prompt, effort="medium")


def citizen_answer(question: str, context: dict) -> str:
    system = FAIRNESS + (
        " You are 'Mera Complaint', BMC's citizen helpdesk bot. Reply in the SAME language and script the citizen "
        "used (English, Hinglish, Marathi or Hindi). Answer only from the CONTEXT. If the complaint can't be found, "
        "say so and ask for the complaint ID (format BMC25-000123) or the exact locality. Keep it under 120 words."
    )
    return ask(system, f"CITIZEN: {question}\n\nCONTEXT:\n{_j(context)}", effort="low", max_tokens=4000)


def classify_posts(posts: list[dict]) -> str:
    prompt = ("Classify each post: type (fresh report / repeat complaint / sarcasm / thank-you / forward-unverified / "
              "chatter), issue (pothole, waterlogging, manhole, cave-in, drain, paver, none), locality, and whether "
              "BMC should act (yes/no). Return a markdown table with post_id.\n\n" + _j(posts))
    return ask("You analyse Mumbai civic social posts in English, Hinglish, Hindi and Marathi.", prompt, effort="low")
