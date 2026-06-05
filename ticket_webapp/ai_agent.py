"""
Server-side autonomous coding agent used by the /ai web page.

Given a natural-language task it runs a think -> act -> observe loop:
the LLM writes files and runs shell commands (to test its own work) inside
an isolated per-request workspace, and keeps iterating until it calls finish.

Uses a free, OpenAI-compatible LLM API. The default provider is OpenRouter's
free tier (model openai/gpt-oss-120b:free), which returns clean JSON and reasons
well. Any other OpenAI-compatible endpoint can be used by setting the
AI_BASE_URL / AI_MODEL / AI_API_KEY env vars (see below).
A standalone CLI version of the same idea lives in ../ai/agent.py.
"""

import json
import os
import re
import subprocess
import tempfile
import time

import httpx

# --- LLM provider configuration --------------------------------------------
# Defaults to OpenRouter's free tier (OpenAI-compatible). Point the agent at any
# other OpenAI-compatible endpoint just by setting these env vars -- no code
# change required.
#   AI_BASE_URL : OpenAI-compatible base URL (the part before /chat/completions)
#   AI_MODEL    : model name to request
#   AI_API_KEY  : bearer token (leave empty for keyless providers)
#   AI_PROVIDER : human-readable label shown in the UI / worklog
AI_PROVIDER = os.environ.get("AI_PROVIDER", "OpenRouter")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://openrouter.ai/api/v1")
AI_MODEL = os.environ.get("AI_MODEL", "openai/gpt-oss-120b:free")
# Embedded free OpenRouter key so the agent works out of the box. The env var
# wins if set. Repo is private; rotate the key at openrouter.ai/keys if leaked.
_EMBEDDED_AI_API_KEY = "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"
AI_API_KEY = os.environ.get("AI_API_KEY", "") or _EMBEDDED_AI_API_KEY

MAX_STEPS = int(os.environ.get("AI_AGENT_MAX_STEPS", "25"))
CMD_TIMEOUT = int(os.environ.get("AI_AGENT_CMD_TIMEOUT", "120"))
MAX_OUTPUT_CHARS = 6000

# Automatic retry/backoff for transient errors (rate limits, 5xx, network).
# Free public endpoints can briefly return HTTP 429 under load; it usually
# clears within seconds, so we retry with exponential backoff.
MAX_RETRIES = int(os.environ.get("AI_AGENT_MAX_RETRIES", "5"))
RETRY_BASE_DELAY = float(os.environ.get("AI_AGENT_RETRY_BASE_DELAY", "2.0"))
RETRY_MAX_DELAY = float(os.environ.get("AI_AGENT_RETRY_MAX_DELAY", "30.0"))
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Ask the model to guarantee a valid JSON object in the reply. If a provider
# doesn't support response_format we transparently fall back. Set
# AI_AGENT_JSON_MODE=0 to disable.
JSON_MODE = os.environ.get("AI_AGENT_JSON_MODE", "1") not in ("0", "false", "")

# Model used for the agent's `research` action. Defaults to the main model; set
# AI_AGENT_RESEARCH_MODEL to a web-capable model (e.g. an OpenRouter ":online"
# variant) if you want the agent to look facts up on the live web.
RESEARCH_MODEL = os.environ.get("AI_AGENT_RESEARCH_MODEL", "") or AI_MODEL
RESEARCH_MAX_TOKENS = int(os.environ.get("AI_AGENT_RESEARCH_MAX_TOKENS", "1200"))


SYSTEM_PROMPT = """\
You are an autonomous software engineer, similar to Devin. You take a task and
complete it END TO END by yourself on a Linux machine: you plan, write code,
run it, read the real output, fix problems, and keep going until it truly works.

You MUST reply with a SINGLE JSON object and nothing else. No prose outside the
JSON. The JSON has exactly these fields:
  {
    "thought": "<your reasoning about the next step, in clear language>",
    "action": "<one of: plan, research, write_file, read_file, run_bash, finish>",
    "params": { ... }
  }

Action parameters:
  - plan:       {"steps": ["step 1", "step 2", ...]}   # use this FIRST, once
  - research:   {"query": "<a specific question>"}     # live web lookup; use it
                                                       # when unsure of a fact
  - write_file: {"path": "relative path", "content": "<full file content>"}
  - read_file:  {"path": "relative path"}
  - run_bash:   {"command": "<one shell command>"}    # also to install deps,
                                                       # e.g. pip install <pkg>
  - finish:     {"message": "<what you built, the verified result, how to use it>"}

How to work (like Devin):
  - START with a "plan" action that lists the concrete steps you will take.
  - Then do ONE action per reply, following your plan.
  - CHECK WHAT ALREADY EXISTS FIRST. Your workspace persists across turns in the
    same chat. Before creating anything, run `ls -la` (and read_file as needed)
    to see files produced in earlier turns, and REUSE them. Do NOT regenerate or
    overwrite an artifact (a key, a file, a result) that already exists — if the
    user refers to "that"/"it" or to something from before, find it and use it.
  - ALWAYS verify your work by RUNNING it with run_bash and reading the output.
    Never "finish" without having actually run it and checked the result.
  - THINK, AND RESEARCH WHEN UNSURE. If you are not certain about a fact, a
    standard, a wire format, a field layout, an algorithm, a library API, or any
    detail — do NOT guess or invent it. Use the `research` action to look it up
    on the live web first, then build on the real answer. This is exactly how a
    senior engineer works: confirm the spec, then implement. Prefer one focused
    research query over several vague ones.
  - Write code carefully BEFORE running it: re-read it for syntax (matched
    parentheses/quotes/colons) so you don't waste a step on a trivial error.
  - If something fails (non-zero exit code or wrong output), read the error
    carefully, fix the SPECIFIC problem, and run it again. Be persistent: keep
    iterating until the output is correct. Do not give up early.
  - You may create multiple files and install packages with pip as needed.
  - Write clean, correct, general-purpose code. No placeholders, no "...".
  - Use only relative paths inside the current workspace directory.
  - BE THOROUGH AND PRECISE. Read the task carefully and address EVERY part of
    it. Re-read what the user actually asked before finishing — do not solve a
    simpler or different problem than the one requested. If the task has several
    requirements, satisfy all of them and confirm each in your final summary.
  - If a task is genuinely impossible or under-specified (e.g. it asks for
    something mathematically infeasible, or needs information you weren't given),
    do NOT silently fail or pretend. Explain clearly WHY in your thoughts, do the
    closest correct thing you can, and state the limitation honestly in finish.
  - When everything works, "finish" with a clear summary that includes the
    verified result and how to use it. If the user asked for specific values,
    PUT THE ACTUAL VALUES in the finish message, not just "it worked".

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
  - To output the NUMERIC parameters of an EXISTING key, load that key file and
    print the integers — do NOT generate a new key:
      * DSA: `load_pem_private_key(...)`, then `.private_numbers()` gives `x` and
        `.public_numbers.y`; the group params are `.public_numbers.parameter_numbers`
        -> `.p`, `.q`, `.g`. Print them as decimal `int`s.
      * RSA: `.private_numbers()` -> `p`, `q`, `d`; `.public_numbers()` -> `n`, `e`.
    Print very large integers in full (decimal); the user wants the real digits.

Barcodes & transit ticketing expertise:
  - You are knowledgeable about 2D barcode symbologies and transport ticketing
    standards. Useful background (verify exact details with `research` when it
    matters):
      * UIC 918.3 / ERA TAP-TSI "barcode" rail e-ticket: payload is carried in
        an Aztec Code, container starts with magic "#UT", a version, a 4-char
        RICS issuer/security-provider code and a key id, then a DSA/ECDSA
        signature over a zlib-DEFLATE-compressed ASN.1 record set (record ids
        like U_HEAD, U_TLAY, U_FLEX...). Flexible content uses ASN.1 (UPER).
      * VDV-KA / "VDV eTicket Deutschland" barcode (a.k.a. VDV-Barcode / EFS):
        static ticket data in a TLV/ASN.1 structure with a signature, encoded in
        an Aztec Code. Distinct from UIC 918.3.
      * Symbologies: Aztec, QR, PDF417, DataMatrix, Code128 — know their
        capacity, error-correction and typical use.
      * Encodings: ASN.1 BER/DER/PER/UPER, TLV, base64, zlib/DEFLATE.
  - Relevant libraries are commonly available and you may pip install as needed:
    `asn1tools` (ASN.1 schemas), `ber_tlv` (TLV), `aztec_code_generator`
    (Aztec), `pyzbar`/`zxing` (decoding), plus the crypto libs above.
  - When a task touches a specific standard or field layout you are not 100%
    sure about, RESEARCH it first (e.g. "UIC 918.3 barcode header byte layout"),
    then implement against the confirmed spec instead of guessing.

Begin now with your "plan" action."""


class AgentError(Exception):
    pass


def _extract_message_text(data):
    """Pull the assistant text and optional reasoning out of a response.

    Returns (content, reasoning). Reasoning models (e.g. gpt-oss) keep their
    chain-of-thought in a separate `reasoning` field; if a model instead inlines
    a <think>...</think> block we split it out.
    """
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning") or ""
    if "</think>" in content:
        parts = content.rsplit("</think>", 1)
        if not reasoning:
            reasoning = parts[0].replace("<think>", "").strip()
        content = parts[1]
    return content.strip(), reasoning.strip()


def _retry_after_seconds(resp, attempt):
    """How long to wait before the next retry.

    Honour the server's Retry-After header when present (sent on 429),
    otherwise fall back to exponential backoff capped at RETRY_MAX_DELAY.
    """
    header = resp.headers.get("Retry-After") if resp is not None else None
    if header:
        try:
            return min(max(float(header), 0.0), RETRY_MAX_DELAY)
        except ValueError:
            pass
    return min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)


def _llm_chat(messages, on_retry=None, model=None, json_mode=None,
              max_tokens=None):
    """Call the OpenAI-compatible chat API, retrying transient failures.

    `on_retry`, if given, is called as on_retry(message:str) before each wait so
    the live worklog can show that a short rate limit is being handled.
    `model`/`json_mode`/`max_tokens` override the defaults (used by the research
    action, which talks to a web-capable model and does not want JSON mode).
    """
    url = f"{AI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "ubuntu-agent/1.0",
    }
    # Keyless providers (e.g. Pollinations) need no Authorization header; only
    # send one when an API key is configured.
    if AI_API_KEY:
        headers["Authorization"] = f"Bearer {AI_API_KEY}"
    payload = {"model": model or AI_MODEL, "messages": messages,
               "temperature": 0.2}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    # Force valid JSON so the agent never wastes a step on an unparseable reply.
    # If a model doesn't support JSON mode we transparently fall back below.
    use_json = JSON_MODE if json_mode is None else json_mode
    if use_json:
        payload["response_format"] = {"type": "json_object"}

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        resp = None
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                content, reasoning = _extract_message_text(resp.json())
                return content, reasoning
            if resp.status_code == 400 and use_json:
                # Model likely rejected response_format; drop it and retry once
                # without consuming a backoff attempt.
                use_json = False
                payload.pop("response_format", None)
                continue
            if resp.status_code in _RETRYABLE_STATUS and attempt < MAX_RETRIES:
                delay = _retry_after_seconds(resp, attempt)
                reason = ("rate limit (429)" if resp.status_code == 429
                          else f"server error ({resp.status_code})")
                if on_retry:
                    on_retry(
                        f"{AI_PROVIDER} {reason} \u2013 retrying in {delay:.0f}s "
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
                        f"{AI_PROVIDER} network error ({type(e).__name__}) \u2013 "
                        f"retrying in {delay:.0f}s "
                        f"(attempt {attempt + 1}/{MAX_RETRIES})\u2026"
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
    # Return content preview so the live worklog can show what was written.
    lines = content.splitlines()
    if len(lines) > 80:
        preview = "\n".join(lines[:70]) + f"\n... ({len(lines) - 70} more lines)"
    else:
        preview = content
    return f"Wrote {len(content)} bytes to {path}\n--- content ---\n{preview}"


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


_RESEARCH_SYSTEM = (
    "You are a precise research assistant with live web access. Answer the "
    "question factually and concretely: give exact specifics (numbers, field "
    "names, byte layouts, algorithm names, standard/version identifiers) rather "
    "than vague summaries. Name the relevant standards/sources inline. If the "
    "answer is uncertain or contested, say so explicitly. Be concise."
)


def _research(query, on_retry=None):
    """Look a fact up on the live web via a web-capable model.

    This is the agent's self-research ability: when it is unsure about a fact,
    standard, or format it can call `research` instead of guessing.
    """
    query = (query or "").strip()
    if not query:
        return "ERROR: research needs a non-empty 'query'."
    messages = [
        {"role": "system", "content": _RESEARCH_SYSTEM},
        {"role": "user", "content": query},
    ]
    try:
        answer, _ = _llm_chat(messages, on_retry=on_retry, model=RESEARCH_MODEL,
                              json_mode=False, max_tokens=RESEARCH_MAX_TOKENS)
    except AgentError as e:
        return f"research failed: {e}"
    return (answer or "(no answer)")[:MAX_OUTPUT_CHARS]


def _format_history(history):
    """Render prior turns of this chat into a compact context string."""
    lines = []
    for turn in history or []:
        role = (turn.get("role") or "").lower()
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        who = "User asked" if role == "user" else "You (agent) answered"
        lines.append(f"- {who}: {text[:500]}")
    return "\n".join(lines)


def _session_context(workspace, history):
    """Build a context message so the agent has memory + sees existing files."""
    parts = []
    hist = _format_history(history)
    if hist:
        parts.append("EARLIER IN THIS CHAT SESSION (for context, do not redo):\n" + hist)
    try:
        files = sorted(f for f in os.listdir(workspace) if not f.startswith("."))
    except OSError:
        files = []
    if files:
        parts.append(
            "Your workspace ALREADY contains these files from earlier turns; "
            "reuse them instead of regenerating: " + ", ".join(files)
        )
    return "\n\n".join(parts)


def run_task_stream(task, max_steps=MAX_STEPS, workspace=None, history=None,
                    cancel=None):
    """Run the agent loop for `task`, yielding events as they happen.

    This powers the live worklog (Devin-style): the caller receives a "start"
    event, one "step" event per action the moment it completes, optional
    "notice" events (e.g. a rate-limit backoff), and finally a "done" event
    summarising the run. Errors are yielded as an "error" event.

    `workspace` (if given) is a directory reused across turns of the same chat so
    artifacts persist; `history` is a list of {"role","text"} prior turns so the
    agent has memory of what it already did. Each yielded value is a
    JSON-serialisable dict with a "type" field.
    `cancel` is an optional threading.Event; when set, the loop aborts early.
    """
    backend = f"{AI_PROVIDER} ({AI_MODEL})"
    yield {"type": "start", "task": task, "backend": backend, "max_steps": max_steps}

    if workspace:
        os.makedirs(workspace, exist_ok=True)
    else:
        workspace = tempfile.mkdtemp(prefix="ai_agent_")
    steps = []
    result = None
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    context = _session_context(workspace, history)
    if context:
        messages.append({"role": "user", "content": context})
    messages.append({"role": "user", "content": f"TASK: {task}"})
    tools = {"write_file": _write_file, "read_file": _read_file, "run_bash": _run_bash}

    for step in range(1, max_steps + 1):
        if cancel and cancel.is_set():
            yield {"type": "done", "task": task, "backend": backend,
                   "steps": steps, "result": "(cancelled)", "finished": False}
            return

        notices = []
        try:
            reply, reasoning = _llm_chat(messages, on_retry=notices.append)
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
                     "thought": reply.strip()[:300], "reasoning": reasoning[:600],
                     "observation": ""}
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
                     "thought": thought, "reasoning": reasoning[:600],
                     "observation": result}
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
                     "thought": thought, "reasoning": reasoning[:600],
                     "detail": "Plan",
                     "observation": observation}
            steps.append(entry)
            yield {"type": "step", **entry}
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content":
                             "Plan recorded. Now execute step 1 with a single action."})
            continue

        if name == "research":
            query = params.get("query") or params.get("question") or ""
            rnotices = []
            observation = _research(query, on_retry=rnotices.append)
            for note in rnotices:
                yield {"type": "notice", "message": note}
            entry = {"step": step, "action": "research", "thought": thought,
                     "reasoning": reasoning[:600],
                     "detail": query.strip()[:80],
                     "observation": observation[:MAX_OUTPUT_CHARS]}
            steps.append(entry)
            yield {"type": "step", **entry}
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user",
                             "content": f"RESEARCH RESULT:\n{observation}"})
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
            "reasoning": reasoning[:600],
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


def run_task(task, max_steps=MAX_STEPS, workspace=None, history=None):
    """Run the agent loop for `task`. Returns a dict with the full transcript.

    Backwards-compatible wrapper around run_task_stream for the non-streaming
    /api/ai/run endpoint. If the run errors out, the error is raised so callers
    can report it the same way as before.
    """
    final = None
    for event in run_task_stream(task, max_steps=max_steps,
                                 workspace=workspace, history=history):
        if event["type"] == "error":
            raise AgentError(event["error"])
        if event["type"] == "done":
            final = event
    if final is None:
        return {
            "task": task,
            "backend": f"{AI_PROVIDER} ({AI_MODEL})",
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
