"""Lightweight near-duplicate clustering by normalized titles."""

from __future__ import annotations

import hashlib
import re

_CVE_RE = re.compile(r"\bcve-\d{4}-\d+\b", re.I)
_NOISE = re.compile(
    r"\b(breaking|update|analysis|report|advisory|security|news|blog)\b",
    re.I,
)
_NON_ALNUM = re.compile(r"[^a-z0-9а-яё\s]+", re.I)
_SPACES = re.compile(r"\s+")


def extract_cves(text: str) -> list[str]:
    return sorted({m.group(0).upper() for m in _CVE_RE.finditer(text or "")})


def normalize_title(title: str) -> str:
    text = (title or "").lower()
    text = _CVE_RE.sub(" ", text)
    text = _NOISE.sub(" ", text)
    text = _NON_ALNUM.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    return text[:120]


def cluster_key(title: str, summary: str | None = None) -> str:
    cves = extract_cves(f"{title} {summary or ''}")
    if cves:
        base = "|".join(cves)
    else:
        base = normalize_title(title) or (title or "unknown").lower()[:80]
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
