# Ultra Job Agent

**Ultra Job Agent** is an autonomous job-search assistant: it can scrape public job listings, score them with a free LLM (OpenRouter), tailor resume PDFs, attempt browser-based applications, and track everything in a FastAPI dashboard with optional Telegram and email alerts. It is built for free-tier services and self-hosting.

**Demo:** *Add your deployed URL here after you ship (e.g. Render/Railway).*  
**Screenshot:** *Add a dashboard screenshot to your repo or docs when ready.*

## What it does

- Scrapes LinkedIn and Indeed for roles matching your keywords
- Scores each job with an LLM (OpenRouter free models)
- Tailors a PDF resume per job (ReportLab)
- Attempts browser-based applications with Playwright (best-effort; many sites need manual follow-up)
- Exposes a live FastAPI dashboard with Kanban, logs, and Jarvis chat
- Sends Telegram and email summaries

## Free accounts needed

| Service | Use | Sign up |
|--------|-----|---------|
| [supabase.com](https://supabase.com) | PostgreSQL | Free tier |
| [upstash.com](https://upstash.com) | Redis (REST), optional — live log panel | Free tier |
| [openrouter.ai](https://openrouter.ai) | LLM API | Free models, no card |
| Telegram @BotFather | Alerts | Free |
| Gmail app password | SMTP | Free |
| [render.com](https://render.com) or [railway.app](https://railway.app) | Hosting | Free tier |

## Setup (numbered)

1. **Clone and install**
   ```bash
   git clone <your-repo-url>
   cd ultra-job-agent
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   python main.py setup
   ```
2. **Supabase** — New project → Settings → API: copy `SUPABASE_URL`, `SUPABASE_KEY`. Run `migrations/001_initial.sql` in the SQL Editor.
3. **OpenRouter** — Create an API key (free). Put it in `.env` as `OPENROUTER_API_KEY`.
4. **Upstash (optional)** — Create Redis → REST URL + token for the dashboard live log stream.
5. **Telegram / Gmail (optional)** — For notifications; see `.env.example`.
6. **Configure**
   ```bash
   cp .env.example .env
   # Edit .env with your values (never commit .env)
   ```
7. **Resume** — Edit `resumes/base_resume.txt` with your plain-text resume.
8. **Run**
   ```bash
   python main.py serve
   ```
   Open [http://localhost:8000](http://localhost:8000) (or `APP_HOST` / `APP_PORT` from `.env`).

## Run commands

| Command | Purpose |
|--------|---------|
| `python main.py serve` | FastAPI + scheduler |
| `python main.py setup` | Playwright Chromium + ensure `.env` exists |
| `python main.py scrape` | Run `ScraperAgent` once |
| `python main.py apply` | Run `ResumeAgent` then `ApplyAgent` once |
| `python main.py test-notify` | Send daily summary via Telegram/email |
| `pytest tests/ -v` | Run tests |

## Deploy to Render

1. Push this repo to GitHub.
2. In [Render](https://render.com) → **New** → **Web Service** → connect the repo.
3. Use **`render.yaml`** (Blueprint) or set manually:
   - **Build:** `pip install -r requirements.txt && playwright install chromium`
   - **Start:** `uvicorn dashboard.app:app --host 0.0.0.0 --port $PORT`
4. Add the same variables as in `.env` under **Environment** (especially `SUPABASE_*`, `OPENROUTER_API_KEY`, `PORT` is set by Render).

## Deploy to Railway

1. Push the repo to GitHub.
2. New Railway project → deploy from GitHub.
3. Set environment variables from `.env.example`.
4. `railway.json` installs Playwright Chromium on start.

## Tests

```bash
pytest tests/ -v
```

## Notes

- Configuration is **`.env` only** (`pydantic-settings`). Optional: dashboard **Config** tab stores non-secret overrides in Redis (`config:overrides`).
- Without Supabase, list endpoints return empty data; without Redis, there is no live log tail; without `OPENROUTER_API_KEY`, the app still starts but LLM features return a clear error.

## License

Use and modify for your own job search at your own risk. Respect site terms of service and rate limits.
