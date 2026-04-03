"""Salary estimation utilities — extract and normalize salary from job descriptions."""

from __future__ import annotations

import re
from typing import Optional


# Common INR salary patterns
_INR_PATTERNS = [
    # "₹10,00,000 - ₹15,00,000" or "Rs 10,00,000 - 15,00,000"
    r'(?:₹|rs\.?|inr)\s*([\d,]+)\s*(?:-|to|–)\s*(?:₹|rs\.?|inr)?\s*([\d,]+)',
    # "10 LPA - 15 LPA" or "10-15 LPA"
    r'([\d.]+)\s*(?:-|to|–)\s*([\d.]+)\s*(?:lpa|lakhs?\s*(?:per\s*annum)?|l\.?p\.?a)',
    # "10 LPA" single
    r'([\d.]+)\s*(?:lpa|lakhs?\s*(?:per\s*annum)?|l\.?p\.?a)',
    # "CTC: 10-15 lakhs"
    r'ctc[:\s]*([\d.]+)\s*(?:-|to|–)\s*([\d.]+)\s*(?:lakhs?|lacs?)',
    # USD patterns "80,000 - 120,000" or "$80k - $120k"
    r'\$\s*([\d,]+)\s*(?:-|to|–)\s*\$?\s*([\d,]+)',
    r'\$\s*([\d]+)\s*k\s*(?:-|to|–)\s*\$?\s*([\d]+)\s*k',
]


def _parse_number(s: str) -> float:
    """Remove commas, convert Indian number format."""
    return float(s.replace(",", "").strip())


def estimate_salary(text: str) -> dict[str, Optional[int | str]]:
    """Extract salary range from job description text.

    Returns:
        {"min": int|None, "max": int|None, "currency": "INR"|"USD"|None, "raw": str|None}
    """
    if not text:
        return {"min": None, "max": None, "currency": None, "raw": None}

    text_lower = text.lower()

    # Try LPA patterns first (most common for Indian jobs)
    for pattern in _INR_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if not match:
            continue

        groups = match.groups()
        raw = match.group(0)

        if "lpa" in pattern or "lakhs" in pattern or "lacs" in pattern:
            if len(groups) >= 2:
                min_lpa = float(groups[0])
                max_lpa = float(groups[1])
                return {
                    "min": int(min_lpa * 100_000),
                    "max": int(max_lpa * 100_000),
                    "currency": "INR",
                    "raw": raw,
                }
            elif len(groups) == 1:
                lpa = float(groups[0])
                return {
                    "min": int(lpa * 100_000),
                    "max": int(lpa * 100_000),
                    "currency": "INR",
                    "raw": raw,
                }
        elif "$" in pattern or "k" in pattern.lower():
            if "k" in raw.lower():
                min_val = int(float(groups[0]) * 1000)
                max_val = int(float(groups[1]) * 1000) if len(groups) >= 2 else min_val
            else:
                min_val = int(_parse_number(groups[0]))
                max_val = int(_parse_number(groups[1])) if len(groups) >= 2 else min_val
            return {
                "min": min_val,
                "max": max_val,
                "currency": "USD",
                "raw": raw,
            }
        else:
            # INR direct numbers
            min_val = int(_parse_number(groups[0]))
            max_val = int(_parse_number(groups[1])) if len(groups) >= 2 else min_val
            return {
                "min": min_val,
                "max": max_val,
                "currency": "INR",
                "raw": raw,
            }

    return {"min": None, "max": None, "currency": None, "raw": None}


def extract_experience_range(text: str) -> dict[str, Optional[int]]:
    """Extract experience requirements from description.

    Returns: {"min": int|None, "max": int|None}
    """
    if not text:
        return {"min": None, "max": None}

    text_lower = text.lower()

    patterns = [
        r'(\d+)\s*(?:-|to|–)\s*(\d+)\s*(?:years?|yrs?)\s*(?:of\s*)?(?:experience|exp)',
        r'(?:experience|exp)[:\s]*(\d+)\s*(?:-|to|–)\s*(\d+)\s*(?:years?|yrs?)',
        r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of\s*)?(?:experience|exp)',
        r'(?:minimum|at\s*least|min)\s*(\d+)\s*(?:years?|yrs?)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            groups = match.groups()
            if len(groups) >= 2:
                return {"min": int(groups[0]), "max": int(groups[1])}
            elif len(groups) == 1:
                val = int(groups[0])
                return {"min": val, "max": val + 3}

    return {"min": None, "max": None}


def detect_remote_type(text: str) -> str:
    """Detect work arrangement from description.

    Returns: 'remote' | 'hybrid' | 'onsite' | 'unknown'
    """
    if not text:
        return "unknown"

    text_lower = text.lower()

    remote_signals = ["fully remote", "100% remote", "work from home", "wfh", "remote only", "anywhere"]
    hybrid_signals = ["hybrid", "2 days office", "3 days office", "flexible work", "partial remote"]
    onsite_signals = ["on-site only", "office only", "in-office required", "no remote", "onsite only"]

    for sig in remote_signals:
        if sig in text_lower:
            return "remote"
    for sig in hybrid_signals:
        if sig in text_lower:
            return "hybrid"
    for sig in onsite_signals:
        if sig in text_lower:
            return "onsite"

    # Check location field
    if "remote" in text_lower:
        return "remote"

    return "unknown"
