"""
Devin-API backend for the /ai web page (the "echtes Devin" mode).

Instead of running the small local think->act->observe loop (see ai_agent.py),
this delegates the task to a REAL Devin session via the Devin v3 organizations
API and streams progress back using the SAME event shape as ai_agent's
run_task_stream (start / step / notice / done / error). The existing browser
worklog then renders Devin's run with no special-casing.

Why v3/organizations (not v1): the provided key is an org-scoped key
(prefix `cog_`). It returns 403 on /v1/* and on /v3/enterprise/*, but works on
/v3/organizations/{org_id}/* — confirmed empirically.

Endpoints used:
  POST {base}/organizations/{org}/sessions                      -> create
  GET  {base}/organizations/{org}/sessions/{devin_id}           -> poll status
  POST {base}/organizations/{org}/sessions/{devin_id}/messages  -> follow-up

Continuity: the Devin session id for a chat is stored in the chat's workspace
(`.devin_session`). Follow-up messages in the same chat are sent to that session
so Devin keeps its context across turns.

Configuration (env vars; sensible defaults are baked in so it works out of the
box per the owner's request — override any of these via the environment):
  DEVIN_API_KEY  : API key (overrides the baked-in default).
  DEVIN_ORG_ID   : organization id (overrides the baked-in default).
  DEVIN_API_BASE : API base, defaults to https://api.devin.ai/v3
  DEVIN_POLL_SECS: poll interval, default 5 seconds.
  DEVIN_MAX_WAIT : max seconds to wait for one turn, default 1800.
"""

import json
import os
import time

import httpx

# Baked-in defaults so Devin mode works without any server config. The repo
# owner explicitly asked for the key to be hard-coded and accepts it is not
# secret; the env var still wins if set. Rotate at app.devin.ai if needed.
_DEFAULT_API_KEY = "cog_3dqty3buuo3nlp5qvtup4ocgneki37rn6atwclvmydvqmoemkjia"
_DEFAULT_ORG_ID = "org-dbd58308cf23435ba7cdd165fd91c183"

DEVIN_API_BASE = os.environ.get("DEVIN_API_BASE", "https://api.devin.ai/v3").rstrip("/")
DEVIN_API_KEY = os.environ.get("DEVIN_API_KEY", "") or _DEFAULT_API_KEY
DEVIN_ORG_ID = os.environ.get("DEVIN_ORG_ID", "") or _DEFAULT_ORG_ID
POLL_SECS = float(os.environ.get("DEVIN_POLL_SECS", "5"))
MAX_WAIT = float(os.environ.get("DEVIN_MAX_WAIT", "1800"))

_SESSION_FILE = ".devin_session"

# `status` values that mean the turn is over.
_STATUS_DONE = {"exit"}
_STATUS_ERROR = {"error"}
_STATUS_SUSPENDED = {"suspended"}
# `status_detail` values that mean Devin needs the user / is done.
_DETAIL_DONE = {"finished"}
_DETAIL_WAIT = {"waiting_for_user", "waiting_for_approval"}


class DevinError(Exception):
    pass


def is_configured():
    return bool(DEVIN_API_KEY and DEVIN_ORG_ID)


def _headers():
    return {
        "Authorization": f"Bearer {DEVIN_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "ticket-webapp-ai/1.0",
    }


def _sessions_url():
    return f"{DEVIN_API_BASE}/organizations/{DEVIN_ORG_ID}/sessions"


def _read_saved_session(workspace):
    if not workspace:
        return None
    try:
        with open(os.path.join(workspace, _SESSION_FILE)) as f:
            return f.read().strip() or None
    except OSError:
        return None


def _save_session(workspace, session_id):
    if not workspace or not session_id:
        return
    try:
        with open(os.path.join(workspace, _SESSION_FILE), "w") as f:
            f.write(session_id)
    except OSError:
        pass


def _check(resp, what):
    if resp.status_code in (401, 403):
        raise DevinError(
            f"Devin auth failed (HTTP {resp.status_code}) on {what}. The API key "
            f"is not authorized for org {DEVIN_ORG_ID}. {resp.text[:200]}")
    if resp.status_code not in (200, 201):
        raise DevinError(f"{what} failed (HTTP {resp.status_code}): {resp.text[:300]}")


def _create_session(client, prompt):
    resp = client.post(_sessions_url(), headers=_headers(), json={"prompt": prompt})
    _check(resp, "create session")
    data = resp.json()
    return data["session_id"], data.get("url", "")


def _send_message(client, session_id, message):
    resp = client.post(f"{_sessions_url()}/{session_id}/messages",
                       headers=_headers(), json={"message": message})
    _check(resp, "send message")


def _get_session(client, session_id):
    resp = client.get(f"{_sessions_url()}/{session_id}", headers=_headers())
    _check(resp, "get session")
    return resp.json()


def _status_line(data):
    status = data.get("status") or "?"
    detail = data.get("status_detail")
    acus = data.get("acus_consumed")
    line = f"Status: {status}" + (f" / {detail}" if detail else "")
    if acus:
        line += f"  (ACUs: {acus})"
    return line


def run_devin_stream(task, workspace=None, history=None, cancel=None):
    """Run `task` on a real Devin session, yielding worklog events.

    Yields dicts shaped like ai_agent.run_task_stream so the same UI renders
    both backends: start, step (action="message"/"research"), notice, done,
    error.
    """
    backend = "Devin (api v3)"
    yield {"type": "start", "task": task, "backend": backend, "max_steps": 0}

    if not is_configured():
        yield {"type": "error", "error": (
            "Devin mode is not configured. Set DEVIN_API_KEY and DEVIN_ORG_ID.")}
        return

    try:
        with httpx.Client(timeout=60) as client:
            existing = _read_saved_session(workspace)
            session_id = None
            url = ""
            if existing:
                try:
                    info = _get_session(client, existing)
                    session_id = existing
                    url = info.get("url", "")
                    _send_message(client, session_id, task)
                    yield {"type": "notice",
                           "message": f"Nachricht an bestehende Devin-Session "
                                      f"gesendet ({session_id})."}
                except DevinError:
                    session_id = None  # stale -> create a fresh one below

            if not session_id:
                session_id, url = _create_session(client, task)
                _save_session(workspace, session_id)
                yield {"type": "notice",
                       "message": f"Devin-Session erstellt: {session_id}"}

            if url:
                yield {"type": "step", "step": 0, "action": "research",
                       "thought": "Devin arbeitet jetzt an der Aufgabe.",
                       "detail": "Live verfolgen",
                       "observation": f"Session live verfolgen: {url}"}

            step = 0
            last_line = None
            pr_urls = []
            structured = None
            deadline = time.time() + MAX_WAIT
            outcome = "running"
            while True:
                if cancel and cancel.is_set():
                    yield {"type": "done", "task": task, "backend": backend,
                           "steps": [], "result": "(abgebrochen)",
                           "finished": False, "files": []}
                    return
                if time.time() > deadline:
                    yield {"type": "notice",
                           "message": "Zeitlimit erreicht – Devin arbeitet evtl. "
                                      "weiter. Über die Session-URL ansehen."}
                    outcome = "timeout"
                    break

                data = _get_session(client, session_id)
                line = _status_line(data)
                if line != last_line:
                    last_line = line
                    step += 1
                    yield {"type": "step", "step": step, "action": "message",
                           "thought": "", "detail": "Devin",
                           "observation": line}

                for pr in (data.get("pull_requests") or []):
                    u = pr.get("pr_url")
                    if u and u not in pr_urls:
                        pr_urls.append(u)
                if data.get("structured_output"):
                    structured = data["structured_output"]

                status = (data.get("status") or "").lower()
                detail = (data.get("status_detail") or "").lower()
                if status in _STATUS_ERROR or detail == "error":
                    outcome = "error"
                    break
                if status in _STATUS_DONE or detail in _DETAIL_DONE:
                    outcome = "finished"
                    break
                if detail in _DETAIL_WAIT:
                    outcome = "waiting"
                    yield {"type": "notice",
                           "message": "Devin wartet auf deine Eingabe. Antworte "
                                      "im selben Chat, um fortzufahren."}
                    break
                if status in _STATUS_SUSPENDED:
                    outcome = "suspended"
                    yield {"type": "notice",
                           "message": f"Devin-Session pausiert ({detail or status})."}
                    break

                time.sleep(POLL_SECS)

            bits = []
            if outcome == "finished":
                bits.append("Devin hat die Aufgabe abgeschlossen.")
            elif outcome == "waiting":
                bits.append("Devin wartet auf deine Antwort (siehe Session-URL).")
            elif outcome == "error":
                bits.append("Devin-Session mit Fehler beendet (siehe Session-URL).")
            elif outcome == "suspended":
                bits.append("Devin-Session pausiert (siehe Session-URL).")
            elif outcome == "timeout":
                bits.append("Zeitlimit erreicht – Lauf evtl. noch aktiv.")
            if structured:
                try:
                    bits.append("Ergebnis:\n" + json.dumps(structured, indent=2,
                                                           ensure_ascii=False))
                except (TypeError, ValueError):
                    bits.append(f"Ergebnis: {structured}")
            for u in pr_urls:
                bits.append(f"Pull Request: {u}")
            if url:
                bits.append(f"Session: {url}")
            summary = "\n\n".join(bits) or "Devin-Session beendet."

            yield {"type": "done", "task": task, "backend": backend,
                   "steps": [], "result": summary,
                   "finished": outcome in ("finished", "waiting"), "files": []}
    except DevinError as e:
        yield {"type": "error", "error": str(e)}
    except (httpx.TimeoutException, httpx.TransportError) as e:
        yield {"type": "error", "error": f"Devin request failed: {e}"}
