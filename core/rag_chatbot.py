"""Aamchi Road Audit AI — ChromaDB RAG + DuckDB SQL + Gemini tool-calling (ported from the Colab pipeline).

Changes from the notebook, so it runs inside RastaNidhi:
* Data comes from the local dataset folder (no git clone, no /content paths).
* The Gemini key comes from the GEMINI_API_KEY env var or the Admin settings page (kept in memory only), not Colab Secrets.
* The index is built once, lazily / in a background thread, and shared by all requests.
* `run_sql` only accepts a single read-only SELECT/WITH statement (the notebook ran any SQL).
* Without a key the bot still answers in "retrieval-only" mode with the most relevant passages.
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

from .data import DATA_DIR

REPO_DIR = Path(DATA_DIR).parent
ROLES = {
    "Citizen": (
        "Always reply in all three languages—English, Hindi (Devanagari), and Marathi (Devanagari)—with clear headings "
        "(`### English`, `### हिन्दी`, `### मराठी`) for each. Focus on complaint status, linked work_order_id, "
        "contractor, repair method, cost, SLA, and whether the repair held up."
    ),
    "Corporator": (
        "Reply like a ward money-trail briefing for a Mumbai corporator: budget vs spend, spend by contractor "
        "and repair type, spend on fixes failing within 30 days, and fair weather/tide/jurisdiction context."
    ),
    "Ward Officer": (
        "Reply like a technical BMC ward engineering audit: one-line anomaly flags (rate card, duplicate billing "
        "without linked complaint, under-DLP repairs, missed SLAs, re-opens), predicted risk, and durable repair methods."
    ),
    "Judge / Auditor": (
        "Reply concisely with exact IDs, verified SQL numbers, weather/tide/flood fairness context, "
        "and clear next-rupee priorities."
    ),
}
PREFERRED_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash"]
SKIP_EXT = {".csv", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pyc", ".parquet", ".db", ".sqlite"}

_lock = threading.Lock()
_state: dict = {"ready": False, "building": False, "error": None, "built_in_s": None}
_api_key: str | None = None
_client = None
_models: list[str] | None = None


# ---------------------------------------------------------------------------- key / client
def set_api_key(key: str | None) -> None:
    global _api_key, _client, _models
    _api_key, _client, _models = (key or "").strip() or None, None, None


def has_key() -> bool:
    return bool(_api_key or os.environ.get("GEMINI_API_KEY"))


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=_api_key or os.environ.get("GEMINI_API_KEY"))
    return _client


def _active_models() -> list[str]:
    """Same logic as the notebook: preferred names first, then any other 'flash' text model the key can use."""
    global _models
    if _models is not None:
        return _models
    try:
        listed = []
        for m in _get_client().models.list():
            short = (getattr(m, "name", "") or "").replace("models/", "")
            supported = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None) or []
            if (not supported or "generateContent" in supported or "generate_content" in supported) and \
                    not any(x in short.lower() for x in ("tts", "image", "transcribe")):
                listed.append(short)
        ordered = [m for m in PREFERRED_MODELS if m in listed] + [m for m in listed if "flash" in m.lower() and m not in PREFERRED_MODELS]
        _models = ordered or PREFERRED_MODELS
    except Exception:
        _models = PREFERRED_MODELS
    return _models


# ---------------------------------------------------------------------------- index (DuckDB + Chroma)
def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    text = (text or "").strip()
    chunks, start = [], 0
    while text and start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks


def _build() -> None:
    import chromadb
    import duckdb
    from sentence_transformers import SentenceTransformer

    t0 = time.time()
    con = duckdb.connect(database=":memory:")
    for path in sorted(Path(DATA_DIR).glob("*.csv")):
        con.execute(f"CREATE TABLE {path.stem} AS SELECT * FROM read_csv_auto('{path.as_posix()}')")
    con.execute("""
    CREATE OR REPLACE VIEW complaints_clean AS
    SELECT *,
        CASE WHEN LOWER(CAST(description AS VARCHAR)) IN ('test', 'asdfgh')
               OR LOWER(CAST(description AS VARCHAR)) LIKE '%garbage%' OR LOWER(CAST(description AS VARCHAR)) LIKE '%mosquito%'
               OR LOWER(CAST(description AS VARCHAR)) LIKE '%street light%' OR LOWER(CAST(description AS VARCHAR)) LIKE '%hawkers%'
               OR LOWER(CAST(description AS VARCHAR)) LIKE '%noise from construction%' OR LOWER(CAST(description AS VARCHAR)) LIKE '%tree branch%'
               OR CAST(status AS VARCHAR) IN ('Rejected - Not road issue', 'Forwarded to SWM dept')
             THEN TRUE ELSE FALSE END AS is_noise,
        CASE WHEN LOWER(CAST(description AS VARCHAR)) LIKE '%reopened%' OR LOWER(CAST(description AS VARCHAR)) LIKE '%phir se khul gaya%'
               OR CAST(description AS VARCHAR) LIKE '%पुन्हा उखडले%'
             THEN TRUE ELSE FALSE END AS is_repeat_failure,
        CASE WHEN CAST(status AS VARCHAR) IN ('Forwarded to MMRDA/PWD', 'Rejected - Not BMC road') THEN TRUE ELSE FALSE END AS is_non_bmc
    FROM complaints;""")
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    schema = "\n".join(f"- {t}: {[c[0] for c in con.execute(f'DESCRIBE {t}').fetchall()]}" for t in tables)

    items = []
    for root, dirs, files in os.walk(REPO_DIR):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fname in sorted(files):
            fpath = Path(root) / fname
            if fpath.suffix.lower() in SKIP_EXT:
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            rel = fpath.relative_to(REPO_DIR).as_posix()
            items += [{"id": f"{rel}#c{i}", "source": rel, "text": ch} for i, ch in enumerate(_chunk_text(content))]
    for t in tables:
        cols = [c[0] for c in con.execute(f"DESCRIBE {t}").fetchall()]
        sample = con.execute(f"SELECT * FROM {t} LIMIT 3").fetchdf().to_json(orient="records", date_format="iso")
        items.append({"id": f"duckdb:{t}", "source": f"duckdb/{t}", "text": f"Table `{t}` columns: {', '.join(cols)}\nSample rows: {sample}"})

    embedder = SentenceTransformer("all-MiniLM-L6-v2")
    coll = chromadb.Client().get_or_create_collection(name="aamchi_road_audit_rag", metadata={"hnsw:space": "cosine"})
    if coll.count() == 0 and items:
        vecs = embedder.encode([i["text"] for i in items], batch_size=32, show_progress_bar=False, normalize_embeddings=True).tolist()
        coll.add(ids=[i["id"] for i in items], documents=[i["text"] for i in items],
                 metadatas=[{"source": i["source"]} for i in items], embeddings=vecs)
    _state.update(con=con, schema=schema, tables=tables, embedder=embedder, collection=coll,
                  ready=True, built_in_s=round(time.time() - t0, 1), docs=len(items))


def ensure_ready(block: bool = True) -> bool:
    if _state["ready"]:
        return True
    with _lock:
        if _state["ready"]:
            return True
        if _state["building"] and not block:
            return False
        _state.update(building=True, error=None)
        try:
            _build()
        except Exception as e:   # surfaced in /status; the app keeps working
            _state["error"] = f"{type(e).__name__}: {e}"
        finally:
            _state["building"] = False
    return _state["ready"]


def warm_up_in_background() -> None:
    threading.Thread(target=ensure_ready, daemon=True, name="roadbot-index").start()


def status() -> dict:
    s = {k: _state.get(k) for k in ("ready", "building", "error", "built_in_s", "docs")}
    if _state["ready"]:
        s |= {"vectors": _state["collection"].count(), "tables": len(_state["tables"])}
    return s | {"gemini_key": has_key(), "models": _models, "personas": list(ROLES)}


# ---------------------------------------------------------------------------- tools
def chroma_rag_search(query: str, top_k: int = 5) -> list[dict]:
    coll, emb = _state["collection"], _state["embedder"]
    res = coll.query(query_embeddings=emb.encode([query], normalize_embeddings=True).tolist(), n_results=min(top_k, max(coll.count(), 1)))
    return [{"id": i, "source": (m or {}).get("source", ""), "text": d}
            for i, d, m in zip((res.get("ids") or [[]])[0], (res.get("documents") or [[]])[0], (res.get("metadatas") or [[]])[0])]


_READ_ONLY = re.compile(r"^\s*(select|with)\b", re.I)
_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|create|alter|attach|detach|copy|export|import|install|load|pragma|set|call|checkpoint|vacuum)\b", re.I)


def safe_sql(query: str) -> str:
    """Single read-only SELECT/WITH statement, max 15 rows returned (the notebook allowed any SQL)."""
    q = (query or "").strip().rstrip(";").strip()
    if not _READ_ONLY.match(q) or ";" in q or _FORBIDDEN.search(re.sub(r"'[^']*'", "''", q)):
        return "SQL Error: only a single read-only SELECT (or WITH … SELECT) query is allowed."
    try:
        cur = _state["con"].cursor()          # DuckDB cursors are safe to use from request threads
        return cur.execute(q).fetchdf().head(15).to_json(orient="records", date_format="iso")
    except Exception as e:
        return f"SQL Error: {e}"


def _extract_reply_text(resp) -> str:
    direct = getattr(resp, "text", None)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    chunks = []
    for cand in getattr(resp, "candidates", None) or []:
        for part in getattr(getattr(cand, "content", None), "parts", None) or []:
            txt = getattr(part, "text", None)
            if isinstance(txt, str) and txt.strip():
                chunks.append(txt.strip())
    return "\n".join(chunks).strip()


def _snippet(text: str, n: int = 260) -> str:
    t = re.sub(r"[#*`>|_]+", " ", text)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0]
    return cut + " …"


def _retrieval_only(message: str, role_key: str, hits: list[dict], rag_ids: list[str]) -> dict:
    sql_log, facts = [], []
    for cid in dict.fromkeys(re.findall(r"BMC25-\d{6}", message.upper())):
        q = ("SELECT c.complaint_id, c.received_at, c.category_reported, c.locality_text, c.ward_code, c.status, c.resolved_at, "
             "w.work_order_id, w.contractor_name, w.repair_method, w.cost_inr, w.sla_met, w.reopened_within_30d "
             f"FROM complaints_clean c LEFT JOIN work_orders w ON w.linked_complaint_ids LIKE '%' || c.complaint_id || '%' WHERE c.complaint_id = '{cid}'")
        sql_log.append(q); facts.append((cid, safe_sql(q)))
    for wid in dict.fromkeys(re.findall(r"WO25-\d{5}", message.upper())):
        q = ("SELECT work_order_id, ward_code, road_id, work_type, repair_method, contractor_name, assigned_at, completed_at, "
             f"area_sqm, cost_inr, sla_hours, sla_met, reopened_within_30d, engineer_remark FROM work_orders WHERE work_order_id = '{wid}'")
        sql_log.append(q); facts.append((wid, safe_sql(q)))
    import json
    lines = ["**Retrieval-only mode** — no Gemini key is configured, so this answer is the exact records plus the closest passages, "
             "without an AI-written summary. An admin can add the key under *Users & roles → Road Audit AI*.", ""]
    for key, js in facts:
        try:
            rows = json.loads(js)
        except Exception:
            rows = []
        if not rows:
            lines.append(f"**{key}**: not found in the dataset.")
            continue
        r = rows[0]
        lines.append(f"**{key}**")
        lines += [f"- {k.replace('_', ' ')}: {str(v)[:16].replace('T', ' ') if k.endswith('_at') and v else v}" for k, v in r.items() if v not in (None, "", "NaN")]
        lines.append("")
    lines.append("**Closest passages**")
    lines += [f"- *{h['source']}* — {_snippet(h['text'])}" for h in hits[:4]]
    return {"reply": "\n".join(lines), "role": role_key, "model": None, "vector_db": "chromadb (all-MiniLM-L6-v2)",
            "chroma_count": _state["collection"].count(), "rag_hits": rag_ids, "sql_queries": sql_log, "mode": "retrieval-only"}


# ---------------------------------------------------------------------------- chat
def ask_chatbot(message: str, role: str = "Citizen", scope_note: str = "") -> dict:
    role_key = role if role in ROLES else "Citizen"
    if not _state["ready"]:
        if not _state["building"]:
            warm_up_in_background()
        return {"reply": "The audit index is still being built (first start takes about a minute). Please try again shortly.",
                "role": role_key, "model": None, "rag_hits": [], "sql_queries": [], "mode": "warming-up"} | {"status": status()}
    hits = chroma_rag_search(f"{role_key}: {message}", top_k=5)
    rag_ids = [h["id"] for h in hits]
    rag_context = "\n\n---\n\n".join(f"[{h['id']} | {h['source']}]\n{h['text']}" for h in hits)
    sql_log: list[str] = []

    if not has_key():   # still useful without Gemini: exact records for any IDs asked about + tidy passages
        return _retrieval_only(message, role_key, hits, rag_ids)

    from google.genai import types

    def retrieve_rag(query: str) -> str:
        """Retrieve semantically similar chunks from the Chroma vector database."""
        more = chroma_rag_search(query, top_k=5)
        rag_ids.extend(h["id"] for h in more if h["id"] not in rag_ids)
        return "\n\n---\n\n".join(f"[{h['id']} | {h['source']}]\n{h['text']}" for h in more)

    def run_sql(query: str) -> str:
        """Run a read-only DuckDB SELECT query (LIMIT 15) across all loaded CSV tables."""
        sql_log.append(query)
        return safe_sql(query)

    system_instruction = (
        f"You are Aamchi Road Audit AI Chatbot using ChromaDB RAG + DuckDB SQL.\n"
        f"Role: {role_key} — {ROLES[role_key]}\n"
        f"{scope_note}\n"
        f"Always use `retrieve_rag` and `run_sql` to ground answers with exact IDs and numbers.\n"
        f"Filter `complaints_clean WHERE NOT is_noise` for citizen complaints.\n"
        f"Account for `rainfall_daily`, `tides`, and `flood_hotspots` before assigning blame.\n"
        f"All data is synthetic and contractors are fictional; never accuse anyone of fraud — say a job 'needs review'.\n"
        f"Tables:\n{_state['schema']}\n\nRETRIEVED CHROMA RAG CONTEXT:\n{rag_context}"
    )
    errors = []
    for model_name in _active_models():
        for attempt in range(2):
            try:
                chat = _get_client().chats.create(model=model_name, config=types.GenerateContentConfig(
                    system_instruction=system_instruction, tools=[retrieve_rag, run_sql], temperature=0.2))
                resp = chat.send_message(message)
                for _ in range(5):   # manual loop, in case automatic function calling is off
                    calls = getattr(resp, "function_calls", None) or []
                    if not calls:
                        break
                    parts = []
                    for fc in calls:
                        args = dict(fc.args or {})
                        out = retrieve_rag(**args) if fc.name == "retrieve_rag" else run_sql(**args) if fc.name == "run_sql" else f"Unknown tool {fc.name}"
                        parts.append(types.Part.from_function_response(name=fc.name, response={"result": out}))
                    resp = chat.send_message(parts)
                reply = _extract_reply_text(resp) or f"Model `{model_name}` ran {len(sql_log)} SQL queries but returned empty text."
                return {"reply": reply, "role": role_key, "model": model_name, "vector_db": "chromadb (all-MiniLM-L6-v2)",
                        "chroma_count": _state["collection"].count(), "rag_hits": rag_ids, "sql_queries": sql_log, "mode": "gemini"}
            except Exception as e:
                err = str(e)
                errors.append(f"{model_name} (try {attempt + 1}): {err[:300]}")
                if "404" in err or "NOT_FOUND" in err:
                    break
                if "503" in err or "UNAVAILABLE" in err:
                    time.sleep(1.5 * (attempt + 1))
                else:
                    break
    return {"reply": "Chatbot error across models:\n" + "\n".join(errors), "role": role_key, "model": None,
            "vector_db": "chromadb (all-MiniLM-L6-v2)", "chroma_count": _state["collection"].count(),
            "rag_hits": rag_ids, "sql_queries": sql_log, "mode": "error"}
