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

import httpx

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

MAX_STEPS = int(os.environ.get("AI_AGENT_MAX_STEPS", "12"))
CMD_TIMEOUT = int(os.environ.get("AI_AGENT_CMD_TIMEOUT", "30"))
MAX_OUTPUT_CHARS = 3000


SYSTEM_PROMPT = """\
You are ubuntu-agent, an autonomous software engineer on a Linux machine.
You complete the user's task end to end by yourself.

You MUST reply with a SINGLE JSON object and nothing else. No prose outside
the JSON. The JSON has exactly these fields:
  {
    "thought": "<short reasoning about the next step>",
    "action": "<one of: write_file, read_file, run_bash, finish>",
    "params": { ... }
  }

Action parameters:
  - write_file: {"path": "relative path", "content": "<full file content>"}
  - read_file:  {"path": "relative path"}
  - run_bash:   {"command": "<a single shell command>"}
  - finish:     {"message": "<summary of what you built and how to use it>"}

Rules you MUST follow:
  - Work step by step: one action per reply.
  - After you WRITE a script, you MUST RUN it with run_bash and inspect the
    output to verify it actually works. Never finish without running it.
  - If a command fails, read the error, fix the file, and run it again.
  - Use only relative paths inside the current workspace directory.
  - Keep file content complete and runnable (no placeholders / no "...").
  - Only use "finish" once you have verified the result works correctly.

Respond now with the first JSON action."""


class AgentError(Exception):
    pass


def _groq_chat(messages):
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
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, headers=headers, json=payload)
    if resp.status_code != 200:
        raise AgentError(f"LLM request failed (HTTP {resp.status_code}): {resp.text[:300]}")
    return resp.json()["choices"][0]["message"]["content"]


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


def run_task(task, max_steps=MAX_STEPS):
    """Run the agent loop for `task`. Returns a dict with the transcript."""
    workspace = tempfile.mkdtemp(prefix="ai_agent_")
    steps = []
    result = None
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"TASK: {task}"},
    ]
    tools = {"write_file": _write_file, "read_file": _read_file, "run_bash": _run_bash}

    for step in range(1, max_steps + 1):
        reply = _groq_chat(messages)
        action = extract_json(reply)

        if not action or "action" not in action:
            steps.append({"step": step, "action": "invalid",
                          "thought": reply.strip()[:300], "observation": ""})
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
            steps.append({"step": step, "action": "finish",
                          "thought": thought, "observation": result})
            break

        tool = tools.get(name)
        if not tool:
            observation = f"ERROR: unknown action '{name}'."
        else:
            observation = tool(workspace, params)

        steps.append({
            "step": step,
            "action": name,
            "thought": thought,
            "detail": params.get("path") or params.get("command") or "",
            "observation": observation[:MAX_OUTPUT_CHARS],
        })
        messages.append({"role": "assistant", "content": json.dumps(action)})
        messages.append({"role": "user", "content": f"OBSERVATION:\n{observation}"})

    return {
        "task": task,
        "backend": f"Groq ({GROQ_MODEL})",
        "steps": steps,
        "result": result,
        "finished": result is not None,
    }
