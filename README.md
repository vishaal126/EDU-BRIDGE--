# EduBridge-AI

AI-powered learning community built with **Python + Streamlit**: tutor marketplace, tutor–student connections with messaging,
a three-way **Student Skill Exchange** with real matching, an AI learning assistant, notifications and profiles.

## Features
- **Auth**: email/password (scrypt-hashed), Google OAuth, GitHub OAuth, remember-me sessions, email password reset (60-min single-use tokens)
- **Tutor marketplace**: tutor profiles, search + subject filter, connection requests, accept/decline, connection history, end connection
- **Messaging**: authenticated 1-to-1 chat per accepted connection (participants only), history persisted, auto-refresh every 5 s
- **Skill Exchange**: list skills to teach/learn, automatic matching (2-person swaps and 3-person cycles, e.g. Python → Design → Video → Python), invitations, groups of 2–3, group chat, scheduled sessions, completion, feedback ratings, leave group
- **AI assistant**: Anthropic API, 4 modes, conversation history stored per user, graceful errors and retry
- **Notifications** (requests, responses, messages, invitations, group changes, sessions) with read/unread
- **Profiles**: avatar upload, student/tutor details, account settings, password change

## Project layout
| File | Purpose |
|---|---|
| `app.py` | Entry point: routing, session restore, OAuth callback, sidebar |
| `auth_service.py` / `auth_ui.py` | Auth logic / login, register, forgot & reset screens |
| `services.py` | Profiles, marketplace, connections, messaging, skills, groups, sessions, feedback, notifications, AI history |
| `matching.py` | Pure skill-matching algorithm |
| `ai_service.py` / `ui_ai.py` | AI backend / assistant page |
| `ui_market.py`, `ui_exchange.py`, `ui_dashboard.py`, `ui_profile.py`, `ui_common.py` | Pages and shared UI helpers |
| `theme.py` | Dark + neon theme |
| `database.py` / `models.py` / `config.py` | DB layer (SQLite or PostgreSQL), schema, settings |
| `tests/` | `test_backend.py` (28 tests), `ui_smoke.py`, `app_smoke.py` |

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then fill in values
streamlit run app.py
```
Open http://localhost:8501. With no database setting the app creates `data/edubridge.db` (SQLite) automatically.
Tables are created on startup (`init_db()` is idempotent). Run tests: `python tests/test_backend.py`.

## Configuration (environment variables or Streamlit secrets)
| Key | Required | Notes |
|---|---|---|
| `APP_BASE_URL` | yes (hosted) | Public URL, no trailing slash, e.g. `https://yourapp.streamlit.app` |
| `OAUTH_REDIRECT_URI` | no | Defaults to `APP_BASE_URL + "/"` |
| `DATABASE_URL` | recommended when hosted | `postgresql://user:pass@host:5432/db`. If empty, SQLite at `DATABASE_PATH` (default `data/edubridge.db`) |
| `ANTHROPIC_API_KEY` | for AI | From console.anthropic.com. `AI_MODEL` optional (default `claude-sonnet-5-5`) |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | for Google login | See below |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | for GitHub login | See below |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | for password reset | Port 587 = STARTTLS, 465 = SSL |

Features whose keys are missing show a clear message instead of failing (the OAuth buttons appear disabled, AI input is disabled, reset says email is not configured).

### Google OAuth
1. console.cloud.google.com → APIs & Services → Credentials → **Create OAuth client ID** → *Web application*.
2. **Authorized redirect URI**: `<APP_BASE_URL>/` (exactly, with the trailing slash; add `http://localhost:8501/` for local testing).
3. Configure the OAuth consent screen (add your email as a test user while in *Testing* mode).
4. Copy the client ID and secret into `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.

### GitHub OAuth
1. GitHub → Settings → Developer settings → OAuth Apps → **New OAuth App**.
2. **Authorization callback URL**: `<APP_BASE_URL>/`. (GitHub allows one callback per app; make a second app for localhost.)
3. Generate a client secret; set `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`. Users need a verified email on GitHub.

### Password-reset email (SMTP)
Any SMTP provider works (Gmail with an app password, Brevo, SendGrid SMTP, Mailgun…). Fill the `SMTP_*` keys. The reset link is `<APP_BASE_URL>/?reset=<token>`.

## Database
- **Local**: SQLite, nothing to install.
- **Hosted**: use PostgreSQL (free tiers: Neon, Supabase, Render Postgres). Streamlit Cloud and Render free web services have **ephemeral disks**, so SQLite data is lost on restart/redeploy. Set `DATABASE_URL` and tables are created on first start.

## Deploy

### Streamlit Community Cloud
1. Push to GitHub (below). 2. share.streamlit.io → **New app** → repo, branch `main`, **Main file path: `app.py`**.
3. Advanced settings → **Secrets**: paste your values (same format as `secrets.toml.example`; include `APP_BASE_URL` = the app's URL, and `DATABASE_URL`).
4. Add that URL + `/` as the redirect URI in Google/GitHub.

### Render (Web Service)
- **Root directory**: leave empty (repo root) · **Runtime**: Python 3
- **Build command**: `pip install -r requirements.txt`
- **Start command**: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
- **Environment variables**: all keys from the table above; set `PYTHON_VERSION` to `3.12.3` (or another 3.10+).
- Use a Render/Neon PostgreSQL `DATABASE_URL`.

> GitHub Pages hosts only static sites and **cannot** run this Python/Streamlit app. Use Streamlit Cloud, Render, or similar.

## Upload to GitHub
```bash
git init
git add .
git status            # confirm .streamlit/secrets.toml and data/ are NOT listed
git commit -m "Initial commit: EduBridge-AI"
git branch -M main
git remote add origin https://github.com/<you>/edubridge-ai.git
git push -u origin main
```
`.gitignore` already excludes secrets, local databases and caches. If you ever commit a key by mistake, revoke and regenerate it.

## Security notes and known limits
- Passwords: scrypt with per-user salt. Reset/session tokens are stored only as SHA-256 hashes. Reset links are single-use and expire in 60 min; resetting signs out all sessions.
- All data access functions check that the acting user is a participant (messages, groups, AI history, connections). User text is HTML-escaped before display.
- **Session persistence uses a token in the URL (`?sid=`)** because Streamlit cannot set cookies natively. It survives page refresh, but anyone with that exact URL could use the session until it expires or you log out, so don't share it. Sessions last 12 h (30 days with "Remember me").
- Messaging refreshes by polling every 5 s, not WebSockets.
- Skill matching compares normalised names (case/space-insensitive): "Python" ≠ "Python programming". The skills tab lists popular names to encourage consistent wording.
- Times in the UI are server-local; timestamps in notifications/chats are UTC.

## What has and hasn't been tested
Tested automatically (`tests/`): registration/login/validation, password hashing, sessions, reset-token flow (single-use, expiry), OAuth account creation/linking (with the provider calls mocked), connection lifecycle, message access control, skill rules, 2- and 3-person matching, group invite/accept/decline/leave/complete, sessions, feedback, notifications, AI history isolation, and every page executing against a stubbed Streamlit.

**Not tested here** (needs real credentials/infrastructure): live Google/GitHub sign-in, SMTP delivery, real AI API calls, PostgreSQL, the actual Streamlit server rendering and responsive layout. Follow the setup steps above and try each once after deploying.
