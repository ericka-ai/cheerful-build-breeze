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

import html as html_module
import json
import os
import re
import subprocess
import tempfile
import time
from urllib.parse import parse_qs, urlparse

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
# API key for the OpenAI-compatible backend. Never hard-code a key here (it leaks
# in source control); configure it via the environment instead. AI_API_KEY wins,
# OPENAI_API_KEY is accepted as a fallback. Leave empty only for keyless
# providers (e.g. Pollinations).
AI_API_KEY = os.environ.get("AI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")

# Stronger free OpenRouter models tried as automatic fallbacks if the primary
# model is unavailable (404 / not-found) or keeps failing. The primary AI_MODEL
# is always tried FIRST, so this never changes behaviour when the primary works;
# it only keeps the agent alive (and smarter) when the primary is down. Override
# the whole chain with AI_MODELS="modelA,modelB,..." (comma-separated).
_DEFAULT_MODEL_CHAIN = [
    "deepseek/deepseek-r1:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
]


def _model_chain():
    """Ordered, de-duplicated list of models to try (primary first)."""
    env = os.environ.get("AI_MODELS", "").strip()
    if env:
        chain = [m.strip() for m in env.split(",") if m.strip()]
    else:
        chain = [AI_MODEL] + _DEFAULT_MODEL_CHAIN
    seen, out = set(), []
    for m in chain:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


MAX_STEPS = int(os.environ.get("AI_AGENT_MAX_STEPS", "40"))
CMD_TIMEOUT = int(os.environ.get("AI_AGENT_CMD_TIMEOUT", "240"))
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

# Token budget for the agent's main reasoning/JSON reply. Generous by default so
# weak free models don't truncate their JSON mid-step (a common failure). 0 =
# don't send a limit (let the provider decide). Override with AI_AGENT_MAX_TOKENS.
MAIN_MAX_TOKENS = int(os.environ.get("AI_AGENT_MAX_TOKENS", "2048"))


SYSTEM_PROMPT = """\
You are an autonomous software engineer, similar to Devin. You take a task and
complete it END TO END by yourself on a Linux machine: you plan, write code,
run it, read the real output, fix problems, and keep going until it truly works.

IMPORTANT: Show your FULL reasoning in the "thought" field. Write out your
complete chain of thought — what you understand about the task, what approaches
you're considering, why you choose one over another, what you expect to happen.
The user sees your thinking process in real time; make it thorough and detailed
so they can follow along. Think step by step. Never give just one sentence —
explain your reasoning fully.

You MUST reply with a SINGLE JSON object and nothing else. No prose outside the
JSON. The JSON has exactly these fields:
  {
    "thought": "<your FULL reasoning about the next step — be detailed and thorough>",
    "action": "<one of: plan, research, web_search, fetch_url, write_file, edit_file, read_file, list_files, run_bash, remember, finish>",
    "params": { ... }
  }

Action parameters:
  - plan:       {"steps": ["step 1", "step 2", ...]}   # use this FIRST, once
  - research:   {"query": "<a specific question>"}     # live web lookup; use it
                                                       # when unsure of a fact
  - web_search: {"query": "<search terms>"}            # find real pages (title +
                                                       # URL); then fetch_url one
  - fetch_url:  {"url": "<https://...>"}               # read a specific web page
                                                       # / doc / spec as text
  - write_file: {"path": "relative path", "content": "<full file content>"}
  - edit_file:  {"path": "relative path", "old": "<exact text>", "new": "<replacement>"}
                                                       # surgical change; "old"
                                                       # must match EXACTLY. Add
                                                       # "all": true to replace
                                                       # every occurrence. Prefer
                                                       # this over rewriting a big
                                                       # file for a small change.
  - read_file:  {"path": "relative path"}
  - list_files: {}                                     # see files made so far
  - run_bash:   {"command": "<one shell command>"}    # also to install deps,
                                                       # e.g. pip install <pkg>
  - remember:   {"note": "<fact or learning to remember>"}  # save a note for
                                                       # future tasks in this
                                                       # chat so you don't forget
  - finish:     {"message": "<what you built, the verified result, how to use it>"}

How to handle uploaded files (CRITICAL):
  - When the user uploads a file (script, code, data), ALWAYS start by reading it
    with read_file to understand its contents.
  - If the user asks you to MODIFY the file (e.g. "change X to Y", "make it do Z
    instead"), use edit_file for small changes or write a new version with
    write_file. Give the new file a DESCRIPTIVE NAME that reflects the change
    (e.g. "script_5bit.py" instead of "script.py" when changing from 4-bit to
    5-bit). ALWAYS keep the original file intact.
  - After modifying, RUN the modified file to verify it works.
  - In your finish message, clearly state what you changed and that the new file
    is ready for download.
  - NEVER just describe what changes would be needed — actually MAKE the changes
    and produce the modified file.

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
  - THINK THOROUGHLY AND SHOW YOUR WORK. In every "thought" field, write out your
    full reasoning — what you see, what you conclude, what your next move is and
    why. The user watches your thinking in real time, so make it transparent and
    educational. This is one of your most important features.
  - RESEARCH WHEN UNSURE. If you are not certain about a fact, a standard, a wire
    format, a field layout, an algorithm, a library API, or any detail — do NOT
    guess or invent it. Use the `research` action or `web_search` + `fetch_url`
    to look it up first, then build on the real answer. This is exactly how a
    senior engineer works: confirm the spec, then implement. When a topic is
    complex, do MULTIPLE research queries to gather enough information.
  - Write code carefully BEFORE running it: re-read it for syntax (matched
    parentheses/quotes/colons) so you don't waste a step on a trivial error.
  - If something fails (non-zero exit code or wrong output), read the error
    carefully, fix the SPECIFIC problem, and run it again. Be persistent: keep
    iterating until the output is correct. Do not give up early.
  - You may create multiple files and install packages with pip as needed.
  - Write clean, correct, general-purpose code. No placeholders, no "...".
  - NEVER hand back placeholder, "illustrative", "stub", "demonstration" or
    "not implemented" work, and never just DESCRIBE what the code *would* do.
    Actually implement the real thing and make it run. Phrases like "in a real
    implementation", "left as an exercise", "this is illustrative" or "recovery
    not performed" are FORBIDDEN in your code and final answer — if you catch
    yourself writing one, stop and implement it for real instead.
  - PROVE success with real output. When the task is to RECOVER / CRACK / SOLVE /
    BREAK / DECRYPT something (e.g. recover a private key from leaked nonce bits
    via an LLL/BKZ lattice attack), you must ACTUALLY recover the value, then
    VERIFY it: compare the recovered value to the ground truth in code
    (`assert recovered == real`) and print both. Do not claim it works unless
    the program itself prints proof that it does.
  - TAKE YOUR TIME. You have many steps available — use them. It is far better to
    think, research, implement carefully, run, debug, and iterate than to rush to
    a quick but wrong/placeholder answer. Do not finish early just to be fast.
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
  - SELF-REVIEW before you finish. In your final "thought", explicitly check:
    (1) did I address EVERY part of the task? (2) did I actually RUN it and see
    correct real output (not a placeholder)? (3) are the deliverable files
    present (use list_files)? (4) for a recover/crack/solve task, did I PROVE the
    result with a verification/assert? If any check fails, do NOT finish — fix it
    first.
  - EDITING: to change an existing file, prefer `edit_file` (exact-match
    search/replace) over rewriting the whole file with write_file — it is faster
    and avoids accidentally dropping working code. Rewrite in full only for big
    or structural changes.
  - DON'T GET STUCK. If the same action keeps giving the same failure, stop
    repeating it: change your approach, inspect the inputs, add debug output, or
    research the exact error message. Repeating an identical failing step wastes
    your budget.
  - USE REMEMBER. When you learn something useful during a task (a library trick,
    a pattern, a user preference), save it with the `remember` action so you can
    recall it in future turns of this chat.

General engineering skill:
  - You are a strong generalist engineer. Beyond crypto you are fluent in data
    processing (JSON/CSV/SQL/pandas), web/HTTP and APIs, parsing & binary
    formats, regex, algorithms & data structures, concurrency, testing, shell
    scripting, and debugging. Pick the right tool for the job and use real,
    well-known libraries (pip install as needed) instead of reinventing them.
  - When facts, specs, formats, or library APIs are uncertain, use `research` for
    a quick answer or `fetch_url` to read the exact documentation/spec page, then
    implement against the confirmed details rather than guessing.
  - Prefer correct, readable, general-purpose solutions over clever hacks. Handle
    edge cases and error paths, validate inputs, and make output easy to verify.

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

Cryptanalysis / attack toolbox (lattices, RSA, etc.):
  - For LATTICE attacks (LLL/BKZ) install fpylll: `pip install fpylll` (or use
    `sage` if available). Build the basis as an `IntegerMatrix`, reduce with
    `LLL.reduction(M)` (or `BKZ.reduction(M, BKZ.Param(block_size))`), then read
    short vectors back out. For pure-Python without fpylll you may `pip install
    olll` for a simple LLL.
  - DSA/ECDSA NONCE-LEAK key recovery (Hidden Number Problem) with N signatures
    sharing a partial nonce leak (e.g. known MSBs/LSBs of each k): write each
    leak as k_i = a_i + b_i*t_i with small unknown t_i, derive the HNP relations
    t_i ≡ A_i*x + B_i (mod q) from s_i = k_i^-1 (H(m_i) + r_i*x) mod q, build the
    lattice (the standard (N+1) or (N+2)-dim basis with a scaling/embedding row),
    LLL/BKZ-reduce it, and read x out of the short vector. ALWAYS finish by
    verifying: recompute the public key / `assert recovered_x == real_x` and
    print both. If too few signatures or too few leaked bits make it infeasible,
    say so honestly and state how many would be needed.
  - RSA: small-e / stereotyped-message and partial-key-exposure attacks use
    Coppersmith (`sympy` for small cases, or sage's `small_roots`); common-modulus,
    Wiener (small d, via continued fractions), and Fermat (close primes) are pure
    Python. Factor small/weak n with `sympy.factorint` or `pip install pycryptodome`
    utilities. Verify by decrypting/recovering d and checking against the target.
  - Whatever the attack: actually run it on the given data and PROVE it worked
    (print the recovered secret and an equality/verification check). Never stop at
    a placeholder or "this would recover ...".

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


class AuthError(AgentError):
    """LLM auth failure (bad/missing key) — affects every model, so we don't
    fall back to other models when this is raised."""
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
    """Call the LLM, auto-falling-back through `_model_chain()`.

    The primary model is tried first; if it is unavailable (e.g. HTTP 404) or
    keeps failing, the next model in the chain is tried. Pass `model` to pin a
    single model (no fallback). Auth failures abort immediately since a bad key
    affects every model. `on_retry(message)` surfaces retries/switches in the
    live worklog.
    """
    candidates = [model] if model else _model_chain()
    last = None
    for i, m in enumerate(candidates):
        try:
            return _llm_chat_one(messages, m, on_retry=on_retry,
                                 json_mode=json_mode, max_tokens=max_tokens)
        except AuthError:
            raise
        except AgentError as e:
            last = e
            if i < len(candidates) - 1 and on_retry:
                on_retry(f"Modell '{m}' nicht verf\u00fcgbar \u2013 wechsle zu "
                         f"'{candidates[i + 1]}'\u2026")
            continue
    raise last if last else AgentError("LLM request failed (no model).")


def _llm_chat_one(messages, model, on_retry=None, json_mode=None,
                  max_tokens=None):
    """Call the OpenAI-compatible chat API for ONE model, retrying transient
    failures. Raises AuthError on 401/403, AgentError on other failures."""
    url = f"{AI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "ubuntu-agent/1.0",
    }
    # Keyless providers (e.g. Pollinations) need no Authorization header; only
    # send one when an API key is configured.
    if AI_API_KEY:
        headers["Authorization"] = f"Bearer {AI_API_KEY}"
    payload = {"model": model, "messages": messages,
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
            # Auth failures: give an actionable hint instead of a raw 401.
            if resp.status_code in (401, 403):
                raise AuthError(
                    f"LLM auth failed (HTTP {resp.status_code}). Set a valid "
                    f"AI_API_KEY (or OPENAI_API_KEY) for {AI_PROVIDER}, or switch "
                    f"to Devin mode. Details: {resp.text[:200]}"
                )
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


# Files the agent itself produces are the deliverables we hand back to the user.
# We hide internal/noise entries so the download list only shows real artifacts.
_IGNORED_FILE_NAMES = {".gitignore"}

# Extensions that represent runnable code. Writing one of these without ever
# running anything triggers the "you must test before finishing" guard.
_RUNNABLE_EXTS = {
    ".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl",
    ".php", ".go", ".rs", ".java", ".c", ".cpp", ".cc", ".cs", ".lua",
}


def list_workspace_files(workspace):
    """Return the artifacts in a workspace as [{path, size}], newest first.

    Walks the whole workspace (not just the top level) so files the agent
    creates in sub-directories are delivered too. Hidden files/dirs and a few
    internal names are skipped. Paths are relative to the workspace root.
    """
    if not workspace or not os.path.isdir(workspace):
        return []
    items = []
    for root, dirs, files in os.walk(workspace):
        # Don't descend into hidden or virtualenv-style dirs.
        dirs[:] = [d for d in dirs if not d.startswith(".")
                   and d not in ("__pycache__", "node_modules")]
        for name in files:
            if name.startswith(".") or name in _IGNORED_FILE_NAMES:
                continue
            abspath = os.path.join(root, name)
            try:
                st = os.stat(abspath)
            except OSError:
                continue
            rel = os.path.relpath(abspath, workspace)
            items.append({"path": rel, "size": st.st_size, "mtime": st.st_mtime})
    items.sort(key=lambda it: it["mtime"], reverse=True)
    for it in items:
        it.pop("mtime", None)
    return items


def _format_file_list(files):
    """Human-readable bullet list of produced files for the finish summary."""
    if not files:
        return ""
    lines = [f"  - {f['path']} ({f['size']} bytes)" for f in files[:50]]
    more = "" if len(files) <= 50 else f"\n  - ... (+{len(files) - 50} more)"
    return "Files produced (downloadable):\n" + "\n".join(lines) + more


# Phrases that betray fake / unfinished work — the agent describing what code
# *would* do instead of making it actually do it. Kept specific on purpose so
# legit code (e.g. a "todo" app) is not flagged. If any of these appear in the
# finish message or in the produced code, we push the agent to really finish.
_PLACEHOLDER_MARKERS = (
    "placeholder",
    "not performed",
    "is illustrative",
    "illustrative)",
    "for demonstration",
    "for illustration",
    "not implemented",
    "notimplementederror",
    "to be implemented",
    "in a real implementation",
    "in a real attack",
    "in a real-world",
    "in practice you would",
    "in practice, you would",
    "left as an exercise",
    "this is a stub",
    "pseudo-code",
    "pseudocode",
    "real attack is more",
    "real implementation would",
    "would actually recover",
    "does not actually",
)


def _find_placeholder(text):
    """Return the first placeholder marker present in `text`, else None."""
    if not text:
        return None
    low = text.lower()
    for marker in _PLACEHOLDER_MARKERS:
        if marker in low:
            return marker
    return None


def _workspace_code_placeholder(workspace, files):
    """Scan produced runnable files for placeholder markers.

    Returns (relpath, marker) for the first hit, else (None, None). Only small
    runnable source files are read so this stays cheap.
    """
    for f in files:
        rel = f.get("path", "")
        _, ext = os.path.splitext(rel.lower())
        if ext not in _RUNNABLE_EXTS:
            continue
        if (f.get("size") or 0) > 200_000:
            continue
        try:
            with open(os.path.join(workspace, rel), encoding="utf-8",
                      errors="ignore") as fh:
                marker = _find_placeholder(fh.read())
        except OSError:
            continue
        if marker:
            return rel, marker
    return None, None


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


def _edit_file(workspace, params):
    """Replace an exact substring in an existing file (surgical edit).

    params: {"path", "old", "new", optional "all": bool}. `old` must match
    EXACTLY (including whitespace). Refuses ambiguous matches unless "all" is
    set, so the agent can change one spot without rewriting the whole file.
    """
    path = params.get("path")
    old = params.get("old")
    new = params.get("new", "")
    if not path or old is None:
        return "ERROR: edit_file needs 'path' and 'old' (and usually 'new')."
    abspath = _safe_path(workspace, path)
    try:
        with open(abspath, encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError as e:
        return f"ERROR reading {path}: {e}"
    if old == "":
        return "ERROR: 'old' must be a non-empty substring to replace."
    n = content.count(old)
    if n == 0:
        return (f"ERROR: 'old' not found in {path}. It must match exactly "
                f"(whitespace included). Use read_file to copy the exact text.")
    replace_all = bool(params.get("all"))
    if n > 1 and not replace_all:
        return (f"ERROR: 'old' matches {n} places in {path}. Add more "
                f"surrounding context to make it unique, or set \"all\": true "
                f"to replace every occurrence.")
    updated = content.replace(old, new) if replace_all else content.replace(old, new, 1)
    try:
        with open(abspath, "w", encoding="utf-8") as f:
            f.write(updated)
    except OSError as e:
        return f"ERROR writing {path}: {e}"
    return (f"Edited {path}: replaced {n if replace_all else 1} occurrence(s). "
            f"New size {len(updated)} bytes.")


def _list_files(workspace, params):
    """List the files produced in the workspace so far (path + size)."""
    files = list_workspace_files(workspace)
    if not files:
        return "(no files yet)"
    return _format_file_list(files)


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


def _html_to_text(html):
    """Crude HTML -> readable text: drop script/style, strip tags, unescape."""
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = html_module.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _fetch_url(workspace, params):
    """Fetch a single URL and return its text (HTML reduced to readable text).

    A lightweight 'browser': lets the agent read live docs/specs/pages without a
    heavyweight headless browser. Follows redirects; size-limited output.
    """
    url = (params.get("url") or "").strip()
    if not url:
        return "ERROR: fetch_url needs a 'url'."
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "ubuntu-agent/1.0"})
    except (httpx.TimeoutException, httpx.TransportError) as e:
        return f"ERROR: fetch failed ({type(e).__name__}): {e}"
    ctype = resp.headers.get("content-type", "")
    body = resp.text or ""
    if "html" in ctype.lower() or re.search(r"(?i)<html", body[:2000]):
        body = _html_to_text(body)
    body = body[:MAX_OUTPUT_CHARS]
    return (f"HTTP {resp.status_code} {ctype}\nURL: {resp.url}\n"
            f"--- content ---\n{body}")


def _web_search(workspace, params):
    """Search the web (DuckDuckGo) and return the top results as title + URL.

    A real link finder: the agent can then `fetch_url` the most relevant result.
    Complements `research` (LLM answer) with actual sources.
    """
    query = (params.get("query") or params.get("q") or "").strip()
    if not query:
        return "ERROR: web_search needs a 'query'."
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.post(
                "https://html.duckduckgo.com/html/", data={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 "
                         "Safari/537.36"})
    except (httpx.TimeoutException, httpx.TransportError) as e:
        return f"ERROR: search failed ({type(e).__name__}): {e}"
    html = resp.text or ""
    results = []
    pat = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.S | re.I)
    for m in pat.finditer(html):
        href, title = m.group(1), _html_to_text(m.group(2))
        url = href
        if "uddg=" in href:
            qs = parse_qs(urlparse(href).query)
            if qs.get("uddg"):
                url = qs["uddg"][0]
        if title and url:
            results.append((title, url))
        if len(results) >= 8:
            break
    if not results:
        return (f"No results parsed (HTTP {resp.status_code}). Try the "
                f"`research` action or refine the query.")
    lines = [f"{i}. {t}\n   {u}" for i, (t, u) in enumerate(results, 1)]
    return f"Web results for: {query}\n" + "\n".join(lines)


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


def _notes_path(workspace):
    """Path to the agent's memory notes file in the workspace."""
    return os.path.join(workspace, ".agent_notes.json")


def _load_notes(workspace):
    """Load remembered notes from the workspace."""
    path = _notes_path(workspace)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _save_note(workspace, note):
    """Append a note to the agent's memory file."""
    notes = _load_notes(workspace)
    notes.append({"text": note, "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
    path = _notes_path(workspace)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)
    return notes


def _session_context(workspace, history):
    """Build a context message so the agent has memory + sees existing files."""
    parts = []
    hist = _format_history(history)
    if hist:
        parts.append("EARLIER IN THIS CHAT SESSION (for context, do not redo):\n" + hist)
    try:
        files = sorted(f for f in os.listdir(workspace)
                       if not f.startswith("."))
    except OSError:
        files = []
    if files:
        parts.append(
            "Your workspace ALREADY contains these files from earlier turns; "
            "reuse them instead of regenerating: " + ", ".join(files)
        )
    # Load remembered notes so the agent has persistent memory.
    notes = _load_notes(workspace)
    if notes:
        note_lines = [f"  - {n['text']}" for n in notes[-20:]]
        parts.append(
            "YOUR REMEMBERED NOTES (from earlier turns in this chat):\n"
            + "\n".join(note_lines)
        )
    return "\n\n".join(parts)


# Keep the LLM context bounded on long runs so we don't blow the model's token
# limit (which would otherwise abort a task that's making progress). The full
# transcript is still preserved in `steps` for the user; this only trims what we
# resend to the model.
_CTX_MAX_MESSAGES = int(os.environ.get("AI_AGENT_CTX_MAX_MESSAGES", "44"))
_CTX_KEEP_RECENT = int(os.environ.get("AI_AGENT_CTX_KEEP_RECENT", "20"))


def _trim_messages(messages):
    """Bound conversation length: keep the system prompt + the initial
    task/context messages + the most recent exchanges, summarising the gap.

    Returns a (possibly new) list; the original is not mutated.
    """
    if len(messages) <= _CTX_MAX_MESSAGES:
        return messages
    # Head = system prompt + up to the first 2 setup messages (context + TASK).
    head_count = min(3, len(messages))
    head = messages[:head_count]
    recent = messages[-_CTX_KEEP_RECENT:]
    dropped = len(messages) - head_count - len(recent)
    if dropped <= 0:
        return messages
    note = {
        "role": "user",
        "content": (f"[... {dropped} earlier step(s) omitted to save space. "
                    f"Your files persist on disk \u2013 use list_files / read_file "
                    f"to re-check anything you need. Keep following your plan. ...]"),
    }
    return head + [note] + recent


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
    tools = {"write_file": _write_file, "read_file": _read_file,
             "edit_file": _edit_file, "list_files": _list_files,
             "run_bash": _run_bash, "fetch_url": _fetch_url,
             "web_search": _web_search}

    # Track whether the agent actually exercised its work. We refuse the first
    # `finish` that comes after writing code without ever running it, so the
    # agent can't claim success without testing (a common failure of weaker
    # free models). `wrote_code` only counts runnable artifacts.
    wrote_code = False
    ran_bash = False
    forced_test_nudges = 0
    placeholder_nudges = 0
    _MAX_TEST_NUDGES = 3
    _MAX_PLACEHOLDER_NUDGES = 2
    # Loop detection: if the agent repeats the exact same action over and over
    # (a classic weak-model failure), push it to change approach.
    action_sig_counts = {}
    loop_nudges = 0
    _MAX_LOOP_NUDGES = 3

    for step in range(1, max_steps + 1):
        if cancel and cancel.is_set():
            yield {"type": "done", "task": task, "backend": backend,
                   "steps": steps, "result": "(cancelled)", "finished": False}
            return

        notices = []
        try:
            reply, reasoning = _llm_chat(_trim_messages(messages),
                                         on_retry=notices.append,
                                         max_tokens=MAIN_MAX_TOKENS or None)
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
                     "thought": reply.strip()[:2000], "reasoning": reasoning[:4000],
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
            finish_msg = params.get("message", "(done)")
            files = list_workspace_files(workspace)

            # Guard 1: don't let the agent declare success on code it never ran.
            if wrote_code and not ran_bash and forced_test_nudges < _MAX_TEST_NUDGES:
                forced_test_nudges += 1
                nudge = (
                    "You called finish but you have NOT run your code yet. "
                    "Do not finish until you have actually executed it with a "
                    "run_bash action and read the real output. Run it now, fix "
                    "any errors, and only finish once it verifiably works."
                )
                entry = {"step": step, "action": "notice", "message": nudge}
                steps.append(entry)
                yield {"type": "notice", "message": nudge}
                messages.append({"role": "assistant", "content": json.dumps(action)})
                messages.append({"role": "user", "content": nudge})
                continue

            # Guard 2: reject placeholder / "illustrative" / stub work. The
            # agent must really do the task, not describe what code *would* do.
            ph_rel, ph_marker = _workspace_code_placeholder(workspace, files)
            ph_in_msg = _find_placeholder(finish_msg)
            if (ph_rel or ph_in_msg) and placeholder_nudges < _MAX_PLACEHOLDER_NUDGES:
                placeholder_nudges += 1
                where = (f"your file '{ph_rel}' (\"{ph_marker}\")" if ph_rel
                         else f"your finish message (\"{ph_in_msg}\")")
                nudge = (
                    f"This is not finished: {where} contains placeholder / "
                    "illustrative / not-implemented content. Do NOT hand back a "
                    "stub or a description of what the code *would* do. Implement "
                    "the REAL thing now so it actually performs the task, run it "
                    "with run_bash, and PROVE it worked with the real output "
                    "(e.g. for a recovery/attack task, actually recover the value "
                    "and assert it equals the true value, then print it). Only "
                    "finish once it genuinely works end to end."
                )
                entry = {"step": step, "action": "notice", "message": nudge}
                steps.append(entry)
                yield {"type": "notice", "message": nudge}
                messages.append({"role": "assistant", "content": json.dumps(action)})
                messages.append({"role": "user", "content": nudge})
                continue

            result = finish_msg
            # If guards were exhausted without resolution, flag it honestly so
            # the user knows the result may be unverified rather than trusting it.
            warnings = []
            if wrote_code and not ran_bash:
                warnings.append("\u26a0\ufe0f Achtung: Der Code wurde NICHT "
                                "ausgef\u00fchrt \u2013 das Ergebnis ist unbest\u00e4tigt.")
            if _workspace_code_placeholder(workspace, files)[0] or _find_placeholder(result):
                warnings.append("\u26a0\ufe0f Achtung: Der Code enth\u00e4lt evtl. "
                                "Platzhalter \u2013 bitte pr\u00fcfen, ob die Aufgabe "
                                "wirklich gel\u00f6st wurde.")
            if warnings:
                result = result + "\n\n" + "\n".join(warnings)
            file_summary = _format_file_list(files)
            observation = result if not file_summary else f"{result}\n\n{file_summary}"
            entry = {"step": step, "action": "finish",
                     "thought": thought, "reasoning": reasoning[:4000],
                     "observation": observation}
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
                     "thought": thought, "reasoning": reasoning[:4000],
                     "detail": "Plan",
                     "observation": observation}
            steps.append(entry)
            yield {"type": "step", **entry}
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content":
                             "Plan recorded. Now execute step 1 with a single action."})
            continue

        if name == "remember":
            note_text = (params.get("note") or "").strip()
            if note_text:
                saved = _save_note(workspace, note_text)
                observation = f"Noted ({len(saved)} notes saved). Continue."
            else:
                observation = "ERROR: remember needs a 'note' text."
            entry = {"step": step, "action": "remember", "thought": thought,
                     "reasoning": reasoning[:4000],
                     "detail": note_text[:80],
                     "observation": observation}
            steps.append(entry)
            yield {"type": "step", **entry}
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content": observation})
            continue

        if name == "research":
            query = params.get("query") or params.get("question") or ""
            rnotices = []
            observation = _research(query, on_retry=rnotices.append)
            for note in rnotices:
                yield {"type": "notice", "message": note}
            entry = {"step": step, "action": "research", "thought": thought,
                     "reasoning": reasoning[:4000],
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

        if name == "run_bash":
            ran_bash = True
        elif name in ("write_file", "edit_file") and not str(observation).startswith("ERROR"):
            path = (params.get("path") or "").lower()
            _, ext = os.path.splitext(path)
            if ext in _RUNNABLE_EXTS:
                wrote_code = True

        entry = {
            "step": step,
            "action": name,
            "thought": thought,
            "reasoning": reasoning[:4000],
            "detail": (params.get("path") or params.get("command")
                       or params.get("url") or params.get("query") or ""),
            "observation": observation[:MAX_OUTPUT_CHARS],
        }
        steps.append(entry)
        yield {"type": "step", **entry}
        messages.append({"role": "assistant", "content": json.dumps(action)})
        messages.append({"role": "user", "content": f"OBSERVATION:\n{observation}"})

        # Loop detection: same action+args repeated many times means the agent is
        # stuck. Nudge it to try a genuinely different approach.
        sig = f"{name}|{entry['detail']}|{str(observation)[:200]}"
        action_sig_counts[sig] = action_sig_counts.get(sig, 0) + 1
        if action_sig_counts[sig] >= 3 and loop_nudges < _MAX_LOOP_NUDGES:
            loop_nudges += 1
            nudge = (
                "You have repeated the SAME action with the same result several "
                "times \u2013 you are stuck in a loop. Stop repeating it. Re-read the "
                "latest output, form a DIFFERENT hypothesis, and try a genuinely "
                "different approach (e.g. inspect inputs with list_files/read_file, "
                "add debug prints, fix the root cause, or research the error). Do "
                "NOT issue that same action again."
            )
            steps.append({"step": step, "action": "notice", "message": nudge})
            yield {"type": "notice", "message": nudge}
            messages.append({"role": "user", "content": nudge})

    yield {
        "type": "done",
        "task": task,
        "backend": backend,
        "steps": steps,
        "result": result,
        "finished": result is not None,
        "files": list_workspace_files(workspace),
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
        "files": final.get("files", []),
    }
