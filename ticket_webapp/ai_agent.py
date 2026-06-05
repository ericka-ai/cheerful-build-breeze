"""
Server-side autonomous coding agent used by the /ai web page.

Given a natural-language task it runs a think -> act -> observe loop:
the LLM writes files and runs shell commands (to test its own work) inside
an isolated per-request workspace, and keeps iterating until it calls finish.

Uses Groq's free OpenAI-compatible API. Set GROQ_API_KEY in the environment.
A standalone CLI version of the same idea lives in ../ai/agent.py.
"""

import json
import os
import re
import subprocess
import tempfile
import time

import httpx

# Prefer the GROQ_API_KEY env var (e.g. set in Render). Embedded fallback below
# is used only if the env var is unset. Repo is private; rotate the key if leaked.
_EMBEDDED_GROQ_API_KEY = "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"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "") or _EMBEDDED_GROQ_API_KEY
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

MAX_STEPS = int(os.environ.get("AI_AGENT_MAX_STEPS", "18"))
CMD_TIMEOUT = int(os.environ.get("AI_AGENT_CMD_TIMEOUT", "30"))
MAX_OUTPUT_CHARS = 3000

# Automatic retry/backoff for transient Groq errors (rate limits, 5xx, network).
# The Groq free tier has tight per-minute token limits (e.g. 12k tokens/min),
# so a short HTTP 429 is expected under load and usually clears within seconds.
MAX_RETRIES = int(os.environ.get("AI_AGENT_MAX_RETRIES", "5"))
RETRY_BASE_DELAY = float(os.environ.get("AI_AGENT_RETRY_BASE_DELAY", "2.0"))
RETRY_MAX_DELAY = float(os.environ.get("AI_AGENT_RETRY_MAX_DELAY", "30.0"))
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


SYSTEM_PROMPT = """\
You are an autonomous software engineer, similar to Devin. You take a task and
complete it END TO END by yourself on a Linux machine: you plan, write code,
run it, read the real output, fix problems, and keep going until it truly works.

You MUST reply with a SINGLE JSON object and nothing else. No prose outside the
JSON. The JSON has exactly these fields:
  {
    "thought": "<your reasoning about the next step, in clear language>",
    "action": "<one of: plan, write_file, read_file, run_bash, finish>",
    "params": { ... }
  }

Action parameters:
  - plan:       {"steps": ["step 1", "step 2", ...]}   # use this FIRST, once
  - write_file: {"path": "relative path", "content": "<full file content>"}
  - read_file:  {"path": "relative path"}
  - run_bash:   {"command": "<one shell command>"}    # also to install deps,
                                                       # e.g. pip install <pkg>
  - finish:     {"message": "<what you built, the verified result, how to use it>"}

How to work (like Devin):
  - START with a "plan" action that lists the concrete steps you will take.
  - Then do ONE action per reply, following your plan.
  - ALWAYS verify your work by RUNNING it with run_bash and reading the output.
    Never "finish" without having actually run it and checked the result.
  - If something fails (non-zero exit code or wrong output), read the error
    carefully, fix the file, and run it again. Be persistent: keep iterating
    until the output is correct. Do not give up early.
  - You may create multiple files and install packages with pip as needed.
  - Write clean, correct, general-purpose code. No placeholders, no "...".
  - Use only relative paths inside the current workspace directory.
  - When everything works, "finish" with a clear summary that includes the
    verified result and how to use it.

Cryptography expertise:
  - You are also a cryptography expert. You can confidently handle symmetric
    encryption (AES in GCM/CBC/CTR modes), asymmetric crypto (RSA, ECC,
    X25519/Ed25519), hashing (SHA-2/SHA-3, BLAKE2), HMAC and message
    authentication, digital signatures, key derivation (PBKDF2, scrypt,
    Argon2, HKDF), random/nonce generation and secure key handling.
  - Two strong crypto libraries are ALREADY INSTALLED and importable, so use
    them directly instead of hand-rolling primitives:
      * `cryptography` (import e.g. `from cryptography.hazmat.primitives ...`)
      * `pycryptodome` (import as `from Crypto.Cipher import AES`, etc.)
  - Follow best practices: never reuse a nonce/IV, prefer authenticated
    encryption (AES-GCM), use cryptographically secure randomness
    (`os.urandom` / `secrets`), and verify signatures/tags before trusting data.

Begin now with your "plan" action."""


class AgentError(Exception):
    pass


def _retry_after_seconds(resp, attempt):
    """How long to wait before the next retry.

    Honour the server's Retry-After header when present (Groq sends it on 429),
    otherwise fall back to exponential backoff capped at RETRY_MAX_DELAY.
    """
    header = resp.headers.get("Retry-After") if resp is not None else None
    if header:
        try:
            return min(max(float(header), 0.0), RETRY_MAX_DELAY)
        except ValueError:
            pass
    return min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)


def _groq_chat(messages, on_retry=None):
    """Call the Groq chat API, retrying transient failures with backoff.

    `on_retry`, if given, is called as on_retry(message:str) before each wait so
    the live worklog can show that a short rate limit is being handled.
    """
    if not GROQ_API_KEY:
        raise AgentError(
            "GROQ_API_KEY is not set on the server. Add it in the Render "
            "dashboard (Environment) and redeploy. Get a free key at "
            "https://console.groq.com/keys"
        )
    url = f"{GROQ_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "ubuntu-agent/1.0",
    }
    payload = {"model": GROQ_MODEL, "messages": messages, "temperature": 0.2}

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        resp = None
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            if resp.status_code in _RETRYABLE_STATUS and attempt < MAX_RETRIES:
                delay = _retry_after_seconds(resp, attempt)
                reason = ("rate limit (429)" if resp.status_code == 429
                          else f"server error ({resp.status_code})")
                if on_retry:
                    on_retry(
                        f"Groq {reason} \u2013 retrying in {delay:.0f}s "
                        f"(attempt {attempt + 1}/{MAX_RETRIES})\u2026"
                    )
                time.sleep(delay)
                continue
            # Non-retryable, or out of retries: surface a clear error.
            raise AgentError(
                f"LLM request failed (HTTP {resp.status_code}): {resp.text[:300]}"
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_error = e
            if attempt < MAX_RETRIES:
                delay = _retry_after_seconds(None, attempt)
                if on_retry:
                    on_retry(
                        f"Groq network error ({type(e).__name__}) \u2013 retrying "
                        f"in {delay:.0f}s (attempt {attempt + 1}/{MAX_RETRIES})\u2026"
                    )
                time.sleep(delay)
                continue
            raise AgentError(f"LLM request failed after retries: {e}") from e

    raise AgentError(f"LLM request failed after retries: {last_error}")


def extract_json(text):
    """Find and parse the first balanced JSON object in text."""
    candidates = []
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1))

    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[start:i + 1])
                        break
        start = text.find("{", start + 1)
        if len(candidates) > 5:
            break

    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    return None


def _safe_path(workspace, path):
    """Resolve a user path inside the workspace, blocking traversal."""
    abspath = os.path.realpath(os.path.join(workspace, path))
    if not (abspath == workspace or abspath.startswith(workspace + os.sep)):
        raise AgentError(f"path escapes the workspace: {path}")
    return abspath


def _write_file(workspace, params):
    path = params.get("path")
    content = params.get("content", "")
    if not path:
        return "ERROR: write_file needs a 'path'."
    abspath = _safe_path(workspace, path)
    os.makedirs(os.path.dirname(abspath) or workspace, exist_ok=True)
    with open(abspath, "w") as f:
        f.write(content)
    return f"Wrote {len(content)} bytes to {path}"


def _read_file(workspace, params):
    path = params.get("path")
    if not path:
        return "ERROR: read_file needs a 'path'."
    abspath = _safe_path(workspace, path)
    try:
        with open(abspath) as f:
            return f.read()[:MAX_OUTPUT_CHARS]
    except OSError as e:
        return f"ERROR reading {path}: {e}"


def _run_bash(workspace, params):
    command = params.get("command")
    if not command:
        return "ERROR: run_bash needs a 'command'."
    try:
        proc = subprocess.run(
            command, shell=True, cwd=workspace, capture_output=True,
            text=True, timeout=CMD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {CMD_TIMEOUT}s."
    out = (proc.stdout or "")[-MAX_OUTPUT_CHARS:]
    err = (proc.stderr or "")[-MAX_OUTPUT_CHARS:]
    return f"exit_code: {proc.returncode}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"


def run_task_stream(task, max_steps=MAX_STEPS):
    """Run the agent loop for `task`, yielding events as they happen.

    This powers the live worklog (Devin-style): the caller receives a "start"
    event, one "step" event per action the moment it completes, optional
    "notice" events (e.g. a rate-limit backoff), and finally a "done" event
    summarising the run. Errors are yielded as an "error" event.

    Each yielded value is a JSON-serialisable dict with a "type" field.
    """
    backend = f"Groq ({GROQ_MODEL})"
    yield {"type": "start", "task": task, "backend": backend, "max_steps": max_steps}

    workspace = tempfile.mkdtemp(prefix="ai_agent_")
    steps = []
    result = None
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"TASK: {task}"},
    ]
    tools = {"write_file": _write_file, "read_file": _read_file, "run_bash": _run_bash}

    for step in range(1, max_steps + 1):
        # Collect any backoff notices raised during the LLM call so they can be
        # streamed to the client right after the call returns.
        notices = []
        try:
            reply = _groq_chat(messages, on_retry=notices.append)
        except AgentError as e:
            for note in notices:
                yield {"type": "notice", "message": note}
            yield {"type": "error", "error": str(e)}
            return
        for note in notices:
            yield {"type": "notice", "message": note}

        action = extract_json(reply)

        if not action or "action" not in action:
            entry = {"step": step, "action": "invalid",
                     "thought": reply.strip()[:300], "observation": ""}
            steps.append(entry)
            yield {"type": "step", **entry}
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content":
                             "That was not valid. Reply with ONLY the JSON object "
                             "{thought, action, params} as instructed."})
            continue

        name = action.get("action")
        params = action.get("params", {}) or {}
        thought = action.get("thought", "")

        if name == "finish":
            result = params.get("message", "(done)")
            entry = {"step": step, "action": "finish",
                     "thought": thought, "observation": result}
            steps.append(entry)
            yield {"type": "step", **entry}
            break

        if name == "plan":
            plan_steps = params.get("steps") or []
            if isinstance(plan_steps, str):
                plan_steps = [plan_steps]
            observation = "\n".join(
                f"{i}. {s}" for i, s in enumerate(plan_steps, 1)
            ) or "(empty plan)"
            entry = {"step": step, "action": "plan",
                     "thought": thought, "detail": "Plan",
                     "observation": observation}
            steps.append(entry)
            yield {"type": "step", **entry}
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content":
                             "Plan recorded. Now execute step 1 with a single action."})
            continue

        tool = tools.get(name)
        if not tool:
            observation = f"ERROR: unknown action '{name}'."
        else:
            observation = tool(workspace, params)

        entry = {
            "step": step,
            "action": name,
            "thought": thought,
            "detail": params.get("path") or params.get("command") or "",
            "observation": observation[:MAX_OUTPUT_CHARS],
        }
        steps.append(entry)
        yield {"type": "step", **entry}
        messages.append({"role": "assistant", "content": json.dumps(action)})
        messages.append({"role": "user", "content": f"OBSERVATION:\n{observation}"})

    yield {
        "type": "done",
        "task": task,
        "backend": backend,
        "steps": steps,
        "result": result,
        "finished": result is not None,
    }


def run_task(task, max_steps=MAX_STEPS):
    """Run the agent loop for `task`. Returns a dict with the full transcript.

    Backwards-compatible wrapper around run_task_stream for the non-streaming
    /api/ai/run endpoint. If the run errors out, the error is raised so callers
    can report it the same way as before.
    """
    final = None
    for event in run_task_stream(task, max_steps=max_steps):
        if event["type"] == "error":
            raise AgentError(event["error"])
        if event["type"] == "done":
            final = event
    if final is None:
        return {
            "task": task,
            "backend": f"Groq ({GROQ_MODEL})",
            "steps": [],
            "result": None,
            "finished": False,
        }
    return {
        "task": final["task"],
        "backend": final["backend"],
        "steps": final["steps"],
        "result": final["result"],
        "finished": final["finished"],
    }
