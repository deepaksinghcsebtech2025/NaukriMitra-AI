"""Resume upload, variant generation, and performance API."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from agents.resume import ResumeVariantAgent
from core.database import get_db_client
from core.logger import logger

router = APIRouter()

UPLOAD_DIR = Path("resumes/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


class VariantGenerateBody(BaseModel):
    """Optional single style to generate."""
    style: str | None = None


# ---------------------------------------------------------------------------
# Resume upload
# ---------------------------------------------------------------------------

@router.post("/resume/upload")
async def upload_resume(file: UploadFile = File(...)) -> dict:
    """Upload a resume file (PDF, DOCX, TXT). Extracts text for LLM use."""

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".pdf", ".docx", ".txt", ".md"):
        raise HTTPException(status_code=400, detail="Allowed formats: PDF, DOCX, TXT, MD")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 5 MB limit")

    # Save to disk
    safe_name = file.filename.replace(" ", "_").replace("/", "_")
    dest = UPLOAD_DIR / safe_name
    dest.write_bytes(content)

    # Extract text content based on type
    text_content = ""
    if ext == ".txt" or ext == ".md":
        text_content = content.decode("utf-8", errors="replace")
    elif ext == ".pdf":
        text_content = _extract_pdf_text(dest)
    elif ext == ".docx":
        text_content = _extract_docx_text(dest)

    # Optionally save to DB for tracking
    db = get_db_client()
    try:
        row = await db.insert("resume_uploads", {
            "filename": safe_name,
            "file_path": str(dest),
            "file_size": len(content),
            "content_text": text_content[:50000] if text_content else "",
            "is_primary": True,
        })
    except Exception as exc:
        logger.warning("Could not save resume upload to DB: {}", exc)
        row = {"filename": safe_name, "file_path": str(dest)}

    # Also update base_resume.txt if we got text
    if text_content.strip():
        base_path = Path("resumes/base_resume.txt")
        base_path.write_text(text_content[:10000], encoding="utf-8")
        logger.info("Updated base_resume.txt from uploaded {}", safe_name)

    return {
        "filename": safe_name,
        "size": len(content),
        "text_extracted": bool(text_content),
        "text_preview": text_content[:500] if text_content else "",
        "saved_as_base": bool(text_content.strip()),
    }


def _extract_pdf_text(path: Path) -> str:
    """Extract text from PDF using reportlab's rl_accel or fallback."""
    try:
        # Try pdfplumber if available
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages[:20]]
            return "\n\n".join(pages)
    except ImportError:
        pass
    try:
        # Fallback: use subprocess with pdftotext
        import subprocess
        result = subprocess.run(
            ["pdftotext", str(path), "-"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return ""


def _extract_docx_text(path: Path) -> str:
    """Extract text from DOCX using python-docx if available."""
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        pass
    return ""


# ---------------------------------------------------------------------------
# List uploaded resumes
# ---------------------------------------------------------------------------

@router.get("/resume/uploads")
async def list_uploads() -> dict:
    """List all uploaded resume files."""
    files = []
    if UPLOAD_DIR.exists():
        for p in sorted(UPLOAD_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if p.is_file():
                files.append({
                    "filename": p.name,
                    "size": p.stat().st_size,
                    "path": str(p),
                })
    return {"uploads": files}


# ---------------------------------------------------------------------------
# Variant generation and performance
# ---------------------------------------------------------------------------

@router.get("/resume/variants")
async def list_variants() -> dict:
    """List saved variant files and DB rows."""
    db = get_db_client()
    rows = await db.select("resume_variants", limit=100, offset=0)
    files = []
    vdir = Path("resumes/variants")
    if vdir.exists():
        files = [p.name for p in vdir.glob("*.txt")]
    return {"database": rows, "files": files}


@router.post("/resume/variants")
async def create_resume_variants(body: VariantGenerateBody | None = None) -> dict:
    """Generate one variant style or all four."""
    agent = ResumeVariantAgent()
    if body and body.style:
        base = Path("resumes/base_resume.txt")
        text = base.read_text(encoding="utf-8") if base.exists() else ""
        path = await agent.create_variant(text, body.style)
        return {"generated": path}
    return await agent.run()


@router.get("/resume/performance")
async def resume_performance() -> dict:
    """A/B style stats by resume_variant on applications."""
    agent = ResumeVariantAgent()
    return await agent.analyze_performance()
