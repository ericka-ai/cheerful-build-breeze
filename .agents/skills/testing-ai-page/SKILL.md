---
name: testing-ai-page
description: Test the /ai page end-to-end. Use when verifying /ai page UI, auth, chat, sessions, or agent features.
---

# Testing the /ai Page

The `/ai` page is a self-contained HTML/CSS/JS page served from FastAPI at `ticket_webapp/app.py`. All JavaScript is embedded in a Python triple-quoted string — watch for Python string escaping issues (e.g. `'\n'` vs `'\\n'`).

## Prerequisites

1. Start the FastAPI server:
   ```bash
   cd /home/ubuntu/cheerful-build-breeze
   python -m uvicorn ticket_webapp.app:app --host 0.0.0.0 --port 8000 &
   ```

2. Register a test account via API (skip if already registered):
   ```bash
   curl -s -X POST http://localhost:8000/api/register \
     -H 'Content-Type: application/json' \
     -d '{"email":"testuser@example.com","password":"Test1234"}'
   ```
   If verification is required, check server logs for the code and verify:
   ```bash
   curl -s -X POST http://localhost:8000/api/verify \
     -H 'Content-Type: application/json' \
     -d '{"email":"testuser@example.com","code":"CODE_FROM_LOGS"}'
   ```

## Test Credentials

- Email: `testuser@example.com`
- Password: `Test1234`

## Key Functions to Test

All functions are defined in the embedded JS within `ticket_webapp/app.py`:

| Function | What it does |
|----------|-------------|
| `doLogin()` | Login with email/password |
| `doRegister()` | Register new account |
| `doVerify()` | Verify email code |
| `doLogout()` | Logout user |
| `newChat()` | Create new chat session |
| `loadSession(id)` | Load existing session |
| `deleteSession(id)` | Delete session with confirmation |
| `send()` | Send message and stream agent response |
| `toggleRightPanel()` | Toggle right panel visibility |
| `switchRpTab(tab)` | Switch right panel tab |
| `stopAgent()` | Abort streaming agent |

## Test Procedure

1. **Auth Flow**: Logout -> Login -> verify dashboard loads with user email displayed
2. **Registration Form**: Click "Kostenlos registrieren" -> verify form fields -> switch back to login
3. **Sidebar Navigation**: Verify Sessions, Ask, Wiki, Review, Automations (with Beta badge) are present
4. **Session Management**: Create new session (+), switch between sessions, delete with confirmation dialog
5. **Right Panel**: Toggle panel open/close, switch between Worklog/Changes/Shell/Desktop/IDE tabs
6. **Suggestion Chips**: Click greet.sh/Primzahlen/Fibonacci chips -> verify textarea populates
7. **Chat Send**: Select "Lokaler Agent (gratis)", type message, send -> verify message appears and session auto-renames
8. **File Upload**: Click 📎 button -> verify native file picker opens
9. **Agent Mode**: Toggle between "Devin (empfohlen)" and "Lokaler Agent (gratis)" radio buttons

## Known Issues

- **Local Agent LLM**: The local agent mode might fail with HTTP 401 if no `AI_API_KEY` or `OPENAI_API_KEY` is set on the server. This is an environment config issue, not a code bug. The error should be displayed in a red error box.
- **Python string escaping**: When editing JS inside the Python triple-quoted string in `app.py`, use `'\\n'` (double backslash) for JS newlines, not `'\n'` (single backslash). A single `'\n'` becomes a literal newline in the rendered HTML, breaking the JS parser and causing ALL subsequent function definitions to fail silently.
- **Console debugging**: If functions like `doLogin` are `undefined`, check the browser console for "Invalid or unexpected token" errors — this usually indicates a string escaping issue in the Python source.

## Devin Secrets Needed

No secrets required for basic UI testing. For full LLM agent testing, the server needs `AI_API_KEY` or `OPENAI_API_KEY` environment variable set.
