"""
Devin-API backend for the /ai web page (the "echtes Devin" mode).

Instead of running the small local think->act->observe loop (see ai_agent.py),
this module delegates the task to a real Devin session via the Devin v1 API and
streams Devin's progress back using the SAME event shape as ai_agent's
run_task_stream (start / step / notice / done / error). That lets the existing
browser worklog render Devin's run with no special-casing.

Continuity: the Devin session id for a chat is stored in the chat's workspace
(`.devin_session`). Follow-up messages in the same chat are sent to that running
session, so Devin keeps its context across turns.

Configuration (env vars):
  DEVIN_API_KEY   : required. Personal/Service API key (starts with `cog_` or
                    `apk_...`). Never hard-code it.
  DEVIN_API_BASE  : optional, defaults to https://api.devin.ai/v1
  DEVIN_POLL_SECS : optional poll interval, defaults to 4 seconds.
  DEVIN_MAX_WAIT  : optional max seconds to wait for a single turn, default 1800.
"""

import os
import time

import httpx

DEVIN_API_BASE = os.environ.get("DEVIN_API_BASE", "https://api.devin.ai/v1").rstrip("/")
DEVIN_API_KEY = os.environ.get("DEVIN_API_KEY", "")
POLL_SECS = float(os.environ.get("DEVIN_POLL_SECS", "4"))
MAX_WAIT = float(os.environ.get("DEVIN_MAX_WAIT", "1800"))

# Devin session states that mean "this turn is done, stop polling".
_DONE_STATES = {"finished", "expired"}
# "blocked" means Devin is waiting for the user — also stop and hand control back.
_BLOCKED_STATES = {"blocked"}

_SESSION_FILE = ".devin_session"


class DevinError(Exception):
    pass


def is_configured():
    """True if a Devin API key is available."""
    return bool(DEVIN_API_KEY)


def _headers():
    return {
        "Authorization": f"Bearer {DEVIN_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "ticket-webapp-ai/1.0",
    }


def _read_saved_session(workspace):
    if not workspace:
        return None
    try:
        with open(os.path.join(workspace, _SESSION_FILE)) as f:
            sid = f.read().strip()
            return sid or None
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


def _create_session(client, prompt):
    resp = client.post(f"{DEVIN_API_BASE}/sessions", headers=_headers(),
                       json={"prompt": prompt})
    if resp.status_code in (401, 403):
        raise DevinError(
            f"Devin auth failed (HTTP {resp.status_code}). Check DEVIN_API_KEY. "
            f"{resp.text[:200]}"
        )
    if resp.status_code != 200:
        raise DevinError(f"Create session failed (HTTP {resp.status_code}): "
                         f"{resp.text[:300]}")
    data = resp.json()
    return data["session_id"], data.get("url", "")


def _send_message(client, session_id, message):
    resp = client.post(f"{DEVIN_API_BASE}/sessions/{session_id}/message",
                       headers=_headers(), json={"message": message})
    if resp.status_code != 200:
        raise DevinError(f"Send message failed (HTTP {resp.status_code}): "
                         f"{resp.text[:300]}")


def _get_session(client, session_id):
    resp = client.get(f"{DEVIN_API_BASE}/sessions/{session_id}",
                      headers=_headers())
    if resp.status_code != 200:
        raise DevinError(f"Get session failed (HTTP {resp.status_code}): "
                         f"{resp.text[:300]}")
    return resp.json()


def _message_key(msg, idx):
    """Stable identity for a Devin message so we don't emit it twice."""
    return msg.get("event_id") or f"idx:{idx}"


def _is_devin_message(msg):
    origin = (msg.get("origin") or "").lower()
    # Emit Devin's own output; skip the user/api echoes of our own prompts.
    return origin not in ("user", "api", "human")


def run_devin_stream(task, workspace=None, history=None, cancel=None):
    """Run `task` on a real Devin session, yielding worklog events.

    Yields dicts shaped like ai_agent.run_task_stream so the same UI renders
    both backends: start, step (action="message"), notice, done, error.
    """
    backend = "Devin (api)"
    yield {"type": "start", "task": task, "backend": backend, "max_steps": 0}

    if not is_configured():
        yield {"type": "error", "error": (
            "Devin mode is not configured. Set the DEVIN_API_KEY environment "
            "variable (key starts with cog_ or apk_) and restart the server.")}
        return

    try:
        with httpx.Client(timeout=60) as client:
            existing = _read_saved_session(workspace)
            if existing:
                # Continue the existing Devin session for this chat.
                session_id = existing
                # Record which messages we've already shown before sending.
                try:
                    pre = _get_session(client, session_id)
                    seen = {_message_key(m, i)
                            for i, m in enumerate(pre.get("messages") or [])}
                except DevinError:
                    # Saved session is gone/invalid -> start a fresh one.
                    existing = None
                    seen = set()
                if existing:
                    _send_message(client, session_id, task)
                    yield {"type": "notice",
                           "message": f"Nachricht an bestehende Devin-Session "
                                      f"{session_id} gesendet."}
            if not existing:
                session_id, url = _create_session(client, task)
                _save_session(workspace, session_id)
                seen = set()
                yield {"type": "notice",
                       "message": f"Devin-Session erstellt: {session_id}"}
                if url:
                    yield {"type": "step", "step": 0, "action": "research",
                           "thought": "Devin-Session geöffnet",
                           "detail": "session", "observation": f"Session-URL: {url}"}

            step = 0
            result = None
            pr_url = None
            deadline = time.time() + MAX_WAIT
            while True:
                if cancel and cancel.is_set():
                    yield {"type": "done", "task": task, "backend": backend,
                           "steps": [], "result": "(abgebrochen)",
                           "finished": False, "files": []}
                    return
                if time.time() > deadline:
                    yield {"type": "notice",
                           "message": "Zeitlimit erreicht – Devin arbeitet evtl. "
                                      "noch weiter (siehe Session-URL)."}
                    break

                data = _get_session(client, session_id)
                messages = data.get("messages") or []
                for i, msg in enumerate(messages):
                    key = _message_key(msg, i)
                    if key in seen:
                        continue
                    seen.add(key)
                    if not _is_devin_message(msg):
                        continue
                    text = (msg.get("message") or "").strip()
                    if not text:
                        continue
                    step += 1
                    result = text
                    yield {"type": "step", "step": step, "action": "message",
                           "thought": "", "detail": "Devin",
                           "observation": text}

                pr = data.get("pull_request") or {}
                if isinstance(pr, dict) and pr.get("url"):
                    pr_url = pr["url"]

                status_enum = (data.get("status_enum") or "").lower()
                if status_enum in _DONE_STATES:
                    break
                if status_enum in _BLOCKED_STATES:
                    yield {"type": "notice",
                           "message": "Devin wartet auf deine Eingabe. Antworte "
                                      "im selben Chat, um fortzufahren."}
                    break

                time.sleep(POLL_SECS)

            summary_bits = []
            if result:
                summary_bits.append(result)
            if pr_url:
                summary_bits.append(f"Pull Request: {pr_url}")
            summary = "\n\n".join(summary_bits) or "Devin-Session beendet."

            yield {"type": "done", "task": task, "backend": backend,
                   "steps": [], "result": summary,
                   "finished": True, "files": []}
    except DevinError as e:
        yield {"type": "error", "error": str(e)}
    except (httpx.TimeoutException, httpx.TransportError) as e:
        yield {"type": "error", "error": f"Devin request failed: {e}"}
