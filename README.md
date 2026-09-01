# Telegram Autonomous Conversation Assistant

A modular, secure, restart-safe, and production-ready Python application that operates a **Telegram USER ACCOUNT** through MTProto (via Telethon) and uses an LLM (OpenAI-compatible API) to generate conversational responses.

It features an anonymous chat workflow with `@anonrubot`, private chat automation, sliding-window memory with auto-summarization, media management, secret sanitization, and owner controls.

---

## Table of Contents

1. [Features](#features)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Telegram API Credentials Setup](#telegram-api-credentials-setup)
5. [Configuration (.env)](#configuration-env)
6. [First Login & Interactive Authentication](#first-login--interactive-authentication)
7. [Running the Application](#running-the-application)
   - [Dry-Run Mode (Safe Testing)](#dry-run-mode-safe-testing)
   - [Normal Production Mode](#normal-production-mode)
   - [CLI Commands](#cli-commands)
8. [soul.md & Personality Configuration](#soulmd--personality-configuration)
9. [Anonymous Chat Workflow (@anonrubot)](#anonymous-chat-workflow-anonrubot)
10. [Global Owner Control Commands](#global-owner-control-commands)
11. [Database & Persistence](#database--persistence)
12. [Security & Session Protection](#security--session-protection)
13. [Troubleshooting](#troubleshooting)
14. [Testing](#testing)

---

## Features

- **MTProto User Client**: Uses Telethon to operate a real Telegram user profile (no Bot API tokens needed).
- **Anonymous Chat State Machine**: Automated greeting ("Привет)", "М или Д?"), skips male partners via `/next`, initiates active dialogue with female partners, detects and handles username exchanges.
- **LLM Integration**: Works with any OpenAI-compatible API endpoint (OpenAI, OpenRouter, Ollama, vLLM, DeepSeek, etc.).
- **Truthful & Safe Identity**: Adheres strictly to truthful identity disclosure if directly queried, enforces age safety (owner is 21, zero romantic interactions with minors).
- **Structured JSON Validation**: Pydantic validates all LLM output (`reply`, `next`, `stop`, `ignore`, `send_authorized_photo`).
- **Memory & Summaries**: Short-term sliding window (configurable) + automatic long-term LLM dialogue summarization saved in SQLite.
- **Anti-Leak Filter & Sanitized Logs**: Sensitive API keys, session data, and auth codes are automatically scrubbed from logs and outgoing texts.
- **Owner Remote Control**: Execute `/autopilot_on`, `/autopilot_off`, `/pause`, `/resume`, `/status`, `/reload_soul`, `/reload_config`, `/stop` directly from Telegram.
- **Hard Stop `/enough`**: Halts conversation immediately and persists stopped state across restarts.

---

## Requirements

- Python 3.11 or higher
- Telegram account with `api_id` and `api_hash` from [my.telegram.org](https://my.telegram.org)
- LLM API key (e.g. OpenAI, OpenRouter, or local LLM server)

---

## Installation

### 1. Clone or navigate to the repository
```bash
cd d:\projects\ai-chat
```

### 2. Create and activate a virtual environment

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell / Command Prompt):**
```powershell
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

---

## Telegram API Credentials Setup

1. Go to [https://my.telegram.org](https://my.telegram.org) and log in with your Telegram account phone number.
2. Click on **API development tools**.
3. Create a new application (app title and short name can be anything, e.g. `UserAssistant`).
4. Copy your **`api_id`** (an integer) and **`api_hash`** (a 32-character hexadecimal string).

---

## Configuration (.env)

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```
*(On Windows: `copy .env.example .env`)*

Open `.env` and fill in your details:

```env
# ==========================================
# Telegram API Credentials
# ==========================================
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_telegram_api_hash_here
TELEGRAM_PHONE=+1234567890

TELEGRAM_SESSION=telegram_ai

# ==========================================
# LLM Provider Configuration
# ==========================================
LLM_API_KEY=your_llm_api_key_here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
MAX_RESPONSE_TOKENS=300

# ==========================================
# Database Configuration
# ==========================================
DATABASE_URL=sqlite+aiosqlite:///data/app.db

# ==========================================
# Autopilot & Safety Controls
# ==========================================
AUTOPILOT_ENABLED=false
DRY_RUN=true
DRAFT_MODE=false

PRIVATE_CHAT_AUTOPILOT=false
GROUP_CHAT_AUTOPILOT=false

# ==========================================
# Owner Profile & Bot Target
# ==========================================
OWNER_USERNAME=@mlsv06
OWNER_USER_ID=
ANONYMOUS_BOT_USERNAME=anonrubot

# ==========================================
# Pacing & History
# ==========================================
MIN_REPLY_DELAY_SECONDS=1.5
MAX_REPLY_DELAY_SECONDS=5.0
MAX_HISTORY_MESSAGES=30
LOG_LEVEL=INFO
```

---

## First Login & Interactive Authentication

On your very first run, Telethon will interactively request your phone number, the verification code sent to your Telegram app, and your 2FA password (if enabled).

```bash
python run.py --dry-run
```

Once logged in, Telethon creates `telegram_ai.session` in your root directory. Subsequent launches will authenticate automatically.

---

## Running the Application

### Dry-Run Mode (Safe Testing - Default)
In dry-run mode, the bot connects to Telegram, receives messages, evaluates state machines, calls the LLM, and logs what **would** be sent without actually transmitting any message:
```bash
python run.py --dry-run
```

### Normal Production Mode
To start sending live replies:
1. Set `DRY_RUN=false` and `AUTOPILOT_ENABLED=true` in `.env` (or use Telegram owner command `/autopilot_on`).
2. Run:
```bash
python run.py --no-dry-run
```

### CLI Options
- `python run.py --check-config`: Validates `.env` and `soul.md` presence and exits.
- `python run.py --init-db`: Pre-creates SQLite database tables in `data/app.db` and exits.
- `python run.py --debug`: Enables verbose DEBUG logging.
- `python run.py --dry-run`: Force dry-run mode.
- `python run.py --no-dry-run`: Force disable dry-run mode.

---

## soul.md & Personality Configuration

The assistant's conversational voice is configured via [`soul.md`](./soul.md).
You can edit [`soul.md`](./soul.md) while the app is running and reload it live without stopping by sending `/reload_soul` from your owner Telegram account.

---

## Anonymous Chat Workflow (@anonrubot)

```
New Chat Event
     ↓
Sends "Привет)" and "М или Д?"
     ↓
Evaluates answer:
   ├── Answer is Male (м, парень, etc.) → Sends /next → Marks conversation skipped
   ├── Answer is Female (д, девушка, etc.) → State = ACTIVE → Generates LLM response
   └── Answer is Unclear → Politely asks for clarification
     ↓
Active Conversation:
   ├── Normal chat using soul.md + memory context
   ├── Disclosed Telegram handle detected → Saves handle, sends friendly sign-off with OWNER_USERNAME, issues /next
   └── /enough received → Hard stop immediately
```

---

## Global Owner Control Commands

Only the owner (verified by `OWNER_USER_ID` or `OWNER_USERNAME`) can issue these commands:

| Command | Action |
| :--- | :--- |
| `/autopilot_on` | Enable autonomous outgoing messages |
| `/autopilot_off` | Disable outgoing autonomous replies |
| `/status` | View connection, mode, and health status |
| `/pause` | Temporarily pause processing incoming messages |
| `/resume` | Resume normal processing |
| `/reload_soul` | Hot-reload `soul.md` from disk |
| `/reload_config` | Hot-reload safe runtime settings from `.env` |
| `/stop` | Cleanly terminate the application |
| `/enough` | Conversation-level hard stop (available in any chat) |

---

## Database & Persistence

- Data is persisted in SQLite via SQLAlchemy: `data/app.db`.
- **Tables**: `users`, `conversations`, `conversation_state`, `messages`, `conversation_summaries`, `processed_updates`, `control_events`, `media_registry`.
- The state survives restarts and network disconnections.

---

## Security & Session Protection

> [!WARNING]
> The `.session` file generated by Telethon contains full session keys to your Telegram account.
> **NEVER commit `*.session`, `*.session-journal`, or `.env` to Git.**

- `.gitignore` is preconfigured to ignore all credential files, database files, and logs.
- The built-in `SensitiveDataFilter` masks tokens, hashes, and secrets before writing to `logs/app.log` and `logs/error.log`.
- Outgoing LLM responses are inspected by `ResponseSafetyValidator` to block secret leaks or unauthorized system prompts.

---

## How to Stop the Application

- **Locally**: Press `Ctrl + C` in the terminal. The app shuts down Telethon and SQLite connections cleanly.
- **Remotely**: Send `/stop` from your owner Telegram account.

---

## Troubleshooting

- **FloodWaitError**: Telethon will automatically wait the exact required seconds and retry safely.
- **SessionPasswordNeededError**: Your Telegram account has Two-Step Verification (2FA). Enter your password when prompted during first login.
- **LLM Timeout**: Ensure `LLM_BASE_URL` and `LLM_API_KEY` are correct and reachable.

---

## Testing

Run the full automated test suite with pytest:

```bash
pytest -v
```
