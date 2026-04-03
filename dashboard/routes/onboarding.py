"""Onboarding chatbot API — conversational setup flow for new users.

Steps: name → phone → location → linkedin → github → resume →
       skills (auto-filled) → salary → keywords → locations → work_type → done
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from core.supabase_auth import UserContext, get_current_user
from core.database import get_db_client
from core.logger import logger
from core.resume_parser import get_parsed_resume, parse_resume

router = APIRouter(tags=["onboarding"])

# ---------------------------------------------------------------------------
# Step definitions
# ---------------------------------------------------------------------------

STEPS = [
    "name", "phone", "location", "linkedin", "github",
    "resume",          # resume upload (handled separately)
    "skills",          # auto-filled from resume, user confirms
    "salary",          # expected CTC in LPA
    "keywords",        # job search keywords
    "locations",       # preferred cities
    "work_type",       # remote / hybrid / onsite / any
    "done",
]

BOT_PROMPTS: dict[str, str] = {
    "name":      "👋 Hey! I'm your job search assistant. Let's get you set up in 2 minutes.\n\nWhat's your **full name**?",
    "phone":     "Nice to meet you, {name}! 📱 What's your **phone number**? (e.g. +91-9876543210)",
    "location":  "Got it! 🏙️ Which **city** are you based in? (e.g. Bangalore, Mumbai, Remote)",
    "linkedin":  "Perfect. Share your **LinkedIn URL** so I can optimize your profile. (or type 'skip')",
    "github":    "Great! Do you have a **GitHub / portfolio URL**? (or type 'skip')",
    "resume":    "Almost there! 📄 Please **upload your resume** (PDF or DOCX) so I can auto-fill your skills and experience.",
    "skills":    "I found these skills from your resume:\n**{skills}**\n\nType 'ok' to confirm, or add/remove skills.",
    "salary":    "💰 What's your **expected CTC** in LPA? (e.g. 18 for ₹18 LPA)",
    "keywords":  "🔍 What kind of **roles** are you targeting? (comma-separated, e.g. Python Developer, Backend Engineer)",
    "locations":  "📍 Which **cities** should I search in? (e.g. Bangalore, Remote, Mumbai)",
    "work_type": "🏠 Preferred **work type**? Reply with: remote / hybrid / onsite / any",
    "done":      "🚀 You're all set, {name}! I'm ready to start finding and applying to jobs for you.\n\nGo to the **Dashboard** and click **Start Auto-Applying**!",
}

FIELD_MAP: dict[str, str] = {
    "name":      "full_name",
    "phone":     "phone",
    "location":  "location",
    "linkedin":  "linkedin_url",
    "github":    "github_url",
    "salary":    "salary_min_inr",
    "keywords":  "search_keywords",
    "locations": "search_locations",
    "work_type": "work_type",
}

VALID_WORK_TYPES = {"remote", "hybrid", "onsite", "any"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bot_msg(text: str) -> dict:
    return {"role": "bot", "text": text, "ts": _now_ts()}


def _user_msg(text: str) -> dict:
    return {"role": "user", "text": text, "ts": _now_ts()}


def _next_step(current: str) -> str:
    idx = STEPS.index(current) if current in STEPS else -1
    return STEPS[idx + 1] if idx + 1 < len(STEPS) else "done"


def _format_prompt(step: str, collected: dict) -> str:
    tpl = BOT_PROMPTS.get(step, "")
    name = collected.get("full_name", "")
    skills = collected.get("skills_text", "")
    return tpl.format(name=name, skills=skills)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    text: str


@router.get("/api/onboarding/state")
async def get_onboarding_state(user: UserContext = Depends(get_current_user)):
    """Return current onboarding step + message history."""
    db = get_db_client()
    state = await db.select_one("onboarding_state", {"user_id": user.user_id})
    if not state:
        # First time — create row
        initial_msg = _bot_msg(BOT_PROMPTS["name"])
        await db.insert("onboarding_state", {
            "user_id": user.user_id,
            "step": "name",
            "messages": json.dumps([initial_msg]),
            "collected": json.dumps({}),
        })
        return {"step": "name", "messages": [initial_msg], "collected": {}}

    return {
        "step": state.get("step", "name"),
        "messages": state.get("messages") or [],
        "collected": state.get("collected") or {},
    }


@router.post("/api/onboarding/message")
async def send_message(
    body: ChatMessage,
    user: UserContext = Depends(get_current_user),
):
    """Process a user message and advance the onboarding step."""
    db = get_db_client()
    state = await db.select_one("onboarding_state", {"user_id": user.user_id})
    if not state:
        raise HTTPException(400, "Onboarding state not found. Call GET /api/onboarding/state first.")

    step = state.get("step", "name")
    messages: list = state.get("messages") or []
    collected: dict = state.get("collected") or {}
    text = body.text.strip()

    # Record user message
    messages.append(_user_msg(text))

    # Skip handling
    skip = text.lower() in ("skip", "s", "-", "none", "n/a")

    # ---------------------------------------------------------------------------
    # Validate + store per step
    # ---------------------------------------------------------------------------
    if step == "name":
        if len(text.split()) < 1 or len(text) < 2:
            bot_reply = "Hmm, that doesn't look like a name. What's your full name?"
        else:
            collected["full_name"] = text
            step = _next_step(step)
            bot_reply = _format_prompt(step, collected)

    elif step == "phone":
        if skip:
            step = _next_step(step)
            bot_reply = _format_prompt(step, collected)
        elif len(text.replace(" ", "").replace("-", "").replace("+", "")) < 7:
            bot_reply = "That doesn't look right. Please enter a valid phone number (e.g. +91-9876543210)"
        else:
            collected["phone"] = text
            step = _next_step(step)
            bot_reply = _format_prompt(step, collected)

    elif step == "location":
        if len(text) < 2:
            bot_reply = "Please enter a city (e.g. Bangalore, Mumbai, or Remote)"
        else:
            collected["location"] = text
            step = _next_step(step)
            bot_reply = _format_prompt(step, collected)

    elif step == "linkedin":
        if skip:
            step = _next_step(step)
            bot_reply = _format_prompt(step, collected)
        elif "linkedin.com" in text.lower():
            collected["linkedin_url"] = text.strip("/")
            step = _next_step(step)
            bot_reply = _format_prompt(step, collected)
        else:
            bot_reply = "Please enter a valid LinkedIn URL (e.g. https://linkedin.com/in/yourname) or type 'skip'"

    elif step == "github":
        if skip:
            step = _next_step(step)
            bot_reply = _format_prompt(step, collected)
        else:
            collected["github_url"] = text.strip("/")
            step = _next_step(step)
            bot_reply = _format_prompt(step, collected)

    elif step == "resume":
        # Resume is uploaded via separate endpoint; if user types something here, nudge them
        bot_reply = "📎 Please use the **Upload Resume** button above to upload your PDF or DOCX file."

    elif step == "skills":
        if text.lower() in ("ok", "yes", "looks good", "confirm", "correct"):
            step = _next_step(step)
            bot_reply = _format_prompt(step, collected)
        else:
            # User is editing skills
            collected["skills_text"] = text
            step = _next_step(step)
            bot_reply = f"✅ Skills updated! {_format_prompt(step, collected)}"

    elif step == "salary":
        try:
            lpa = float(text.replace("lpa", "").replace("L", "").replace(",", "").strip())
            collected["salary_min_inr"] = int(lpa * 100000)
            step = _next_step(step)
            bot_reply = _format_prompt(step, collected)
        except ValueError:
            bot_reply = "Please enter a number in LPA (e.g. 18 for ₹18 LPA)"

    elif step == "keywords":
        if len(text) < 3:
            bot_reply = "Please enter at least one role (e.g. Python Developer, Backend Engineer)"
        else:
            collected["search_keywords"] = text
            step = _next_step(step)
            bot_reply = _format_prompt(step, collected)

    elif step == "locations":
        if len(text) < 2:
            bot_reply = "Please enter at least one location (e.g. Bangalore, Remote)"
        else:
            collected["search_locations"] = text
            step = _next_step(step)
            bot_reply = _format_prompt(step, collected)

    elif step == "work_type":
        wt = text.lower().strip()
        if wt not in VALID_WORK_TYPES:
            bot_reply = f"Please choose one: remote / hybrid / onsite / any"
        else:
            collected["work_type"] = wt
            step = "done"
            bot_reply = _format_prompt("done", collected)
            # Save profile to Supabase
            await _save_profile(db, user.user_id, collected)

    else:
        bot_reply = "You're all set! Head to the Dashboard to start auto-applying. 🚀"

    messages.append(_bot_msg(bot_reply))

    # Persist updated state
    await db.update_by_field(
        "onboarding_state", "user_id", user.user_id,
        {
            "step": step,
            "messages": json.dumps(messages[-50:]),  # keep last 50 messages
            "collected": json.dumps(collected),
        }
    )

    return {
        "step": step,
        "bot_reply": bot_reply,
        "collected": collected,
        "done": step == "done",
    }


@router.post("/api/onboarding/upload-resume")
async def upload_resume_onboarding(
    file: UploadFile = File(...),
    user: UserContext = Depends(get_current_user),
):
    """Upload resume during onboarding — parse and auto-fill profile fields."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".pdf", ".docx", ".txt", ".md"):
        raise HTTPException(400, f"Unsupported file type: {ext}. Use PDF, DOCX, or TXT.")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "File too large — max 5 MB")

    # Save file
    user_dir = Path("resumes") / user.user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    dest = user_dir / f"resume{ext}"
    dest.write_bytes(content)

    # Also write as base_resume.txt for the agent
    resume_text = _extract_text(content, ext)
    if resume_text:
        (user_dir / "base_resume.txt").write_text(resume_text, encoding="utf-8")

    # Parse resume
    parsed = parse_resume(resume_text) if resume_text else None

    # Build auto-collected fields
    auto_filled: dict[str, Any] = {}
    missing_fields: list[str] = []

    if parsed:
        if parsed.skills:
            auto_filled["skills_text"] = parsed.skills_text
            auto_filled["skills"] = parsed.skills
        else:
            missing_fields.append("skills")

        if parsed.experience_years is not None:
            auto_filled["years_experience"] = int(parsed.experience_years)
        else:
            missing_fields.append("years_experience")

        if parsed.education:
            auto_filled["education"] = parsed.education
            auto_filled["education_text"] = parsed.education_text

        if parsed.current_title:
            auto_filled["current_title"] = parsed.current_title

        if parsed.summary:
            auto_filled["summary"] = parsed.summary

    # Update onboarding state → advance to skills step
    db = get_db_client()
    state = await db.select_one("onboarding_state", {"user_id": user.user_id})
    if state:
        collected = dict(state.get("collected") or {})
        collected.update(auto_filled)
        messages = list(state.get("messages") or [])

        if auto_filled.get("skills_text"):
            next_step = "skills"
            bot_reply = _format_prompt("skills", collected)
        else:
            next_step = "salary"
            bot_reply = "I couldn't find skills in your resume. " + _format_prompt("salary", collected)

        messages.append(_bot_msg(f"✅ Resume uploaded! I found:\n• **{len(parsed.skills if parsed else [])} skills**\n• **{auto_filled.get('years_experience', '?')} years** experience\n• **{auto_filled.get('current_title', 'N/A')}** as current title\n\n{bot_reply}"))

        await db.update_by_field(
            "onboarding_state", "user_id", user.user_id,
            {
                "step": next_step,
                "messages": json.dumps(messages[-50:]),
                "collected": json.dumps(collected),
            }
        )

    return {
        "parsed": auto_filled,
        "missing": missing_fields,
        "skills": auto_filled.get("skills", []),
        "experience_years": auto_filled.get("years_experience"),
        "current_title": auto_filled.get("current_title"),
    }


@router.get("/api/onboarding/complete")
async def check_complete(user: UserContext = Depends(get_current_user)):
    """Check if user has completed onboarding."""
    db = get_db_client()
    profile = await db.select_one("profiles", {"id": user.user_id})
    return {
        "complete": bool(profile and profile.get("onboarding_complete")),
        "profile": profile,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _save_profile(db, user_id: str, collected: dict) -> None:
    """Persist collected onboarding data to profiles table."""
    try:
        salary_inr = collected.get("salary_min_inr", 1200000)
        skills_json = json.dumps(collected.get("skills", []))

        profile_data = {
            "full_name":           collected.get("full_name", ""),
            "phone":               collected.get("phone", ""),
            "location":            collected.get("location", ""),
            "linkedin_url":        collected.get("linkedin_url", ""),
            "github_url":          collected.get("github_url", ""),
            "years_experience":    collected.get("years_experience", 0),
            "current_title":       collected.get("current_title", ""),
            "summary":             collected.get("summary", ""),
            "skills":              skills_json,
            "search_keywords":     collected.get("search_keywords", ""),
            "search_locations":    collected.get("search_locations", ""),
            "work_type":           collected.get("work_type", "any"),
            "salary_min_inr":      salary_inr,
            "onboarding_complete": True,
        }
        await db.upsert("profiles", {"id": user_id, **profile_data})
        logger.info("Onboarding complete — profile saved for user {}", user_id)
    except Exception as exc:
        logger.warning("Could not save profile: {}", exc)


def _extract_text(content: bytes, ext: str) -> str:
    """Extract plain text from uploaded file bytes."""
    if ext in (".txt", ".md"):
        return content.decode("utf-8", errors="ignore")

    if ext == ".pdf":
        try:
            import io
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        except ImportError:
            pass
        # fallback: pdftotext CLI
        import subprocess, tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                ["pdftotext", tmp_path, "-"],
                capture_output=True, timeout=10,
            )
            return result.stdout.decode("utf-8", errors="ignore")
        except Exception:
            return ""
        finally:
            os.unlink(tmp_path)

    if ext == ".docx":
        try:
            import io
            from docx import Document
            doc = Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            return ""

    return ""
