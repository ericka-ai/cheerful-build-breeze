# ubuntu-agent

A small **autonomous coding agent** for Ubuntu — a lightweight, readable version of
the core "Devin" loop. You give it a task in plain language and it builds the
solution by itself, **runs it, checks the output, and fixes errors until it
actually works.**

```
You: "create a bash script that prints the 5 largest files in a directory"

agent:
  think  → I'll write bigfiles.sh, then run it to verify
  write_file bigfiles.sh
  run_bash  bash bigfiles.sh .      → exit_code 0, output looks right
  finish  → "Created bigfiles.sh. Usage: bash bigfiles.sh [dir]"
```

## How it works

The agent runs a simple **think → act → observe** loop:

1. The LLM receives the task and replies with a single JSON action.
2. The agent executes one of these tools:
   - `write_file` — create/overwrite a file
   - `read_file` — read a file back
   - `run_bash` — run a shell command (this is how it **tests** its own work)
3. The result (stdout/stderr/exit code) is fed back to the LLM.
4. Repeat until the LLM calls `finish` — but only after it has run and verified
   the result.

All work happens in `./workspace/` by default.

## Requirements

- Python 3 (standard library only — no `pip install` needed)
- An LLM backend (see below)

## LLM backends (auto-detected)

The agent picks a backend automatically based on environment variables:

| Priority | Condition | Backend |
|----------|-----------|---------|
| 1 | `OPENAI_API_KEY` is set | OpenAI-compatible API |
| 2 | `AGENT_BACKEND=ollama` | **Local Ollama** (free, offline) — default model `qwen2.5-coder:3b` |
| 3 | otherwise (default) | **Free OpenRouter API** — ships with an embedded free key |

### Option A — Free OpenRouter (default, recommended)

Nothing to set up — it just works:

```bash
python3 agent.py "create a python script that renames all .jpeg files to .jpg"
```

This uses the free, OpenAI-compatible [OpenRouter](https://openrouter.ai) tier
(default model `openai/gpt-oss-120b:free`). To use your own key or a different
OpenAI-compatible endpoint, override `AI_API_KEY`, `AI_BASE_URL` and `AI_MODEL`.

### Option B — Local Ollama (free, no key, runs offline)

Slower on CPU-only machines, but needs no account.

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:3b
AGENT_BACKEND=ollama python3 agent.py "create a script that backs up a folder to a .tar.gz"
```

### Option C — OpenAI (or any OpenAI-compatible endpoint, incl. a free key)

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://api.openai.com/v1   # optional
export OPENAI_MODEL=gpt-4o-mini                     # optional
python3 agent.py "..."
```

## Usage

```bash
# one-shot
python3 agent.py "your task here"

# interactive
python3 agent.py
```

## Configuration (env vars)

| Variable | Default | Meaning |
|----------|---------|---------|
| `AGENT_WORKSPACE` | `./workspace` | where the agent creates files |
| `AGENT_MAX_STEPS` | `20` | max think/act iterations per task |
| `AGENT_CMD_TIMEOUT` | `120` | per-command timeout (seconds) |
| `AI_BASE_URL` | `https://openrouter.ai/api/v1` | default OpenAI-compatible base URL |
| `AI_MODEL` | `openai/gpt-oss-120b:free` | default model |
| `AI_API_KEY` | _(embedded free key)_ | bearer token for the default backend |
| `AGENT_BACKEND` | _(empty)_ | set to `ollama` to use local Ollama |
| `OLLAMA_MODEL` | `qwen2.5-coder:3b` | local model |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |

## Safety note

The agent runs shell commands on your machine to test its work. Run it on a
machine where that is acceptable (e.g. a VM or container), and read what it does —
output is printed for every step.
