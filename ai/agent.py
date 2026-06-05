#!/usr/bin/env python3
"""
ubuntu-agent: a small autonomous coding agent for Ubuntu.

Give it a task in natural language (e.g. "create a script that backs up a folder").
The agent will:
  1. think about a plan,
  2. write the script/files itself,
  3. RUN them and inspect the output,
  4. fix errors automatically and retry until it actually works.

It runs on a free, local LLM via Ollama by default (no paid API key needed),
and can also use any OpenAI-compatible API (OpenAI, Groq, ...) via env vars.

Usage:
    python3 agent.py "create a bash script that prints the 10 biggest files in a dir"
    python3 agent.py            # interactive prompt

Backends (auto-detected, in priority order):
    GROQ_API_KEY set        -> Groq free API (fast). Model from GROQ_MODEL
                               (default llama-3.3-70b-versatile).
    OPENAI_API_KEY set      -> OpenAI-compatible API
                               (OPENAI_BASE_URL, OPENAI_MODEL override defaults)
    otherwise               -> local Ollama at OLLAMA_HOST (default localhost:11434)
                               model from OLLAMA_MODEL (default qwen2.5-coder:3b)
"""

import json
import os
import re
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

WORKSPACE = os.environ.get(
    "AGENT_WORKSPACE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")
)
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "20"))
CMD_TIMEOUT = int(os.environ.get("AGENT_CMD_TIMEOUT", "120"))

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:3b")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


# --------------------------------------------------------------------------- #
# Pretty printing
# --------------------------------------------------------------------------- #

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    BLUE = "\033[34m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"


def banner(text, color=C.CYAN):
    print(f"{color}{C.BOLD}{text}{C.RESET}")


def info(label, text, color=C.BLUE):
    print(f"{color}{C.BOLD}{label}{C.RESET} {text}")


# --------------------------------------------------------------------------- #
# LLM backends
# --------------------------------------------------------------------------- #

def _http_post(url, payload, headers=None, timeout=600):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    # Some providers sit behind Cloudflare, which blocks the default
    # "Python-urllib" User-Agent (error 1010). Use a normal UA.
    req.add_header("User-Agent", "ubuntu-agent/1.0")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _openai_compatible_chat(messages, base_url, api_key, model):
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {"model": model, "messages": messages, "temperature": 0.2}
    headers = {"Authorization": f"Bearer {api_key}"}
    out = _http_post(url, payload, headers)
    return out["choices"][0]["message"]["content"]


def llm_chat(messages):
    """Send a chat conversation to the active backend and return the reply text."""
    if GROQ_API_KEY:
        return _openai_compatible_chat(messages, GROQ_BASE_URL, GROQ_API_KEY, GROQ_MODEL)

    if OPENAI_API_KEY:
        return _openai_compatible_chat(messages, OPENAI_BASE_URL, OPENAI_API_KEY, OPENAI_MODEL)

    # Default: local Ollama
    url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    out = _http_post(url, payload)
    return out["message"]["content"]


def backend_name():
    if GROQ_API_KEY:
        return f"Groq API ({GROQ_MODEL})"
    if OPENAI_API_KEY:
        return f"OpenAI-compatible API ({OPENAI_MODEL} @ {OPENAI_BASE_URL})"
    return f"Ollama local ({OLLAMA_MODEL} @ {OLLAMA_HOST})"


# --------------------------------------------------------------------------- #
# Tools the agent can use
# --------------------------------------------------------------------------- #

def tool_write_file(params):
    path = params.get("path")
    content = params.get("content", "")
    if not path:
        return "ERROR: write_file needs a 'path'."
    abspath = path if os.path.isabs(path) else os.path.join(WORKSPACE, path)
    os.makedirs(os.path.dirname(abspath) or ".", exist_ok=True)
    with open(abspath, "w") as f:
        f.write(content)
    return f"Wrote {len(content)} bytes to {abspath}"


def tool_read_file(params):
    path = params.get("path")
    if not path:
        return "ERROR: read_file needs a 'path'."
    abspath = path if os.path.isabs(path) else os.path.join(WORKSPACE, path)
    try:
        with open(abspath) as f:
            content = f.read()
    except OSError as e:
        return f"ERROR reading {abspath}: {e}"
    return content[:8000]


def tool_run_bash(params):
    command = params.get("command")
    if not command:
        return "ERROR: run_bash needs a 'command'."
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=CMD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {CMD_TIMEOUT}s."
    out = (proc.stdout or "")[-4000:]
    err = (proc.stderr or "")[-4000:]
    return f"exit_code: {proc.returncode}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"


TOOLS = {
    "write_file": tool_write_file,
    "read_file": tool_read_file,
    "run_bash": tool_run_bash,
}


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = textwrap.dedent(
    """\
    You are ubuntu-agent, an autonomous software engineer working on an Ubuntu
    Linux machine. You complete the user's task end to end by yourself.

    You MUST reply with a SINGLE JSON object and nothing else. No prose outside
    the JSON. The JSON has exactly these fields:
      {
        "thought": "<short reasoning about the next step>",
        "action": "<one of: write_file, read_file, run_bash, finish>",
        "params": { ... }
      }

    Action parameters:
      - write_file: {"path": "relative/or/abs path", "content": "<full file content>"}
      - read_file:  {"path": "..."}
      - run_bash:   {"command": "<a single shell command>"}
      - finish:     {"message": "<summary of what you built and how to use it>"}

    Rules you MUST follow:
      - Work step by step: one action per reply.
      - After you WRITE a script, you MUST RUN it with run_bash and inspect the
        output to verify it actually works. Never finish without running it.
      - If a command fails (non-zero exit code or error output), read the error,
        fix the file, and run it again. Keep iterating until it works.
      - Prefer creating files in the current workspace with relative paths.
      - Make scripts executable and test realistic inputs where it makes sense.
      - Only use "finish" once you have verified the result works correctly.
      - Keep file content complete and runnable (no placeholders / no "...").

    Respond now with the first JSON action.
    """
)


# --------------------------------------------------------------------------- #
# JSON extraction (robust to small models adding stray text)
# --------------------------------------------------------------------------- #

def extract_json(text):
    """Find and parse the first balanced JSON object in text."""
    # Strip code fences if present.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = []
    if fenced:
        candidates.append(fenced.group(1))

    # Balanced-brace scan.
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
                        candidates.append(text[start : i + 1])
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


# --------------------------------------------------------------------------- #
# Main agent loop
# --------------------------------------------------------------------------- #

def run_agent(task):
    os.makedirs(WORKSPACE, exist_ok=True)
    banner("ubuntu-agent")
    info("Backend:", backend_name())
    info("Workspace:", WORKSPACE)
    info("Task:", task, C.GREEN)
    print()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"TASK: {task}"},
    ]

    for step in range(1, MAX_STEPS + 1):
        banner(f"── step {step}/{MAX_STEPS} ──", C.DIM)
        try:
            reply = llm_chat(messages)
        except urllib.error.URLError as e:
            print(f"{C.RED}LLM request failed: {e}{C.RESET}")
            print("Is the backend running? (e.g. `ollama serve` / model pulled?)")
            return 1

        action = extract_json(reply)
        if not action or "action" not in action:
            info("Model:", reply.strip()[:500], C.YELLOW)
            messages.append({"role": "assistant", "content": reply})
            messages.append(
                {
                    "role": "user",
                    "content": "That was not valid. Reply with ONLY the JSON "
                    "object {thought, action, params} as instructed.",
                }
            )
            continue

        thought = action.get("thought", "")
        name = action.get("action")
        params = action.get("params", {}) or {}

        if thought:
            info("think:", thought, C.CYAN)

        if name == "finish":
            print()
            banner("DONE", C.GREEN)
            print(params.get("message", "(no message)"))
            return 0

        tool = TOOLS.get(name)
        if not tool:
            observation = f"ERROR: unknown action '{name}'."
        else:
            if name == "write_file":
                info("write_file:", params.get("path", "?"), C.YELLOW)
            elif name == "run_bash":
                info("run_bash:", params.get("command", "?"), C.YELLOW)
            elif name == "read_file":
                info("read_file:", params.get("path", "?"), C.YELLOW)
            observation = tool(params)

        print(f"{C.DIM}{observation[:1500]}{C.RESET}")
        print()

        messages.append({"role": "assistant", "content": json.dumps(action)})
        messages.append({"role": "user", "content": f"OBSERVATION:\n{observation}"})

    banner("Reached max steps without finishing.", C.RED)
    return 1


def main():
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        try:
            task = input("What should the agent build? ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
    if not task:
        print("No task given.")
        return 1
    return run_agent(task)


if __name__ == "__main__":
    sys.exit(main())
