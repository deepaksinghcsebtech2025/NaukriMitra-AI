"""Ultra Job Agent CLI: serve, setup, scrape, apply, test notifications."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Dispatch CLI subcommands."""

    parser = argparse.ArgumentParser(prog="ultra-job-agent", description="Ultra Job Agent CLI")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="Start web server + scheduler")
    sub.add_parser("setup", help="Install Playwright + check connections")
    sub.add_parser("scrape", help="Run scraper agent once")
    sub.add_parser("apply", help="Run resume + apply agents once")
    sub.add_parser("test-notify", help="Send test notification")
    args = parser.parse_args()

    if args.cmd == "setup":
        print("Installing Playwright browsers...")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
        if not Path(".env").exists():
            shutil.copy(".env.example", ".env")
            print("Created .env from .env.example — please fill in your values!")
        else:
            print(".env exists ✅")
        print("\nSetup complete!")
        print("Next: Edit .env with your values, then run: python main.py serve")

    elif args.cmd == "scrape":
        from agents.scraper import ScraperAgent

        result = asyncio.run(ScraperAgent().run())
        print(f"Scrape complete: {result}")

    elif args.cmd == "apply":

        async def run_both() -> dict:
            from agents.apply import ApplyAgent
            from agents.resume import ResumeAgent

            r = await ResumeAgent().run()
            a = await ApplyAgent().run()
            return {"resume": r, "apply": a}

        result = asyncio.run(run_both())
        print(f"Apply complete: {result}")

    elif args.cmd == "test-notify":
        from agents.notifier import NotifierAgent

        asyncio.run(NotifierAgent().send_daily_summary())
        print("Test notification sent!")

    else:
        try:
            import uvicorn
        except ModuleNotFoundError:
            print(
                "uvicorn is not installed in this Python environment.\n"
                f"  Interpreter: {sys.executable}\n"
                "  Fix:        python -m pip install -r requirements.txt",
                file=sys.stderr,
            )
            raise SystemExit(1) from None

        from core.config import get_settings

        s = get_settings()
        uvicorn.run(
            "dashboard.app:app",
            host=s.app_host,
            port=int(s.app_port),
            reload=False,
        )


if __name__ == "__main__":
    main()
