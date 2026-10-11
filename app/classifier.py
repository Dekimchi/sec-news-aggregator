from __future__ import annotations

import re

LEGISLATION_PATTERNS = [
    r"\bgdpr\b",
    r"\bccpa\b",
    r"\bhipaa\b",
    r"\blegislat",
    r"\blawmakers?\b",
    r"\bcongress\b",
    r"\bsenate bill\b",
    r"\bparliament\b",
    r"\bact of congress\b",
    r"\bprivacy law\b",
    r"\bdata protection act\b",
    r"\bdata protection regulation\b",
    r"\bcybersecurity law\b",
    r"\bregulatory (?:fine|penalty|compliance)\b",
    r"\bcompliance (?:law|regulation|mandate)\b",
    r"\bfines?\b.{0,40}\b(regulat|gdpr|privacy law)",
    r"\bзаконопроект\b",
    r"\bзаконодател",
    r"\bрегулятор(?:н|ы)",
]

OFFENSIVE_KEYWORDS = [
    "exploit",
    "poc",
    "proof of concept",
    "rce",
    "remote code execution",
    "privilege escalation",
    "bypass",
    "payload",
    "red team",
    "offensive",
    "pentest",
    "penetration test",
    "0day",
    "zero-day",
    "zeroday",
    "weaponiz",
    "cve-",
    "vulnerability",
    "shellcode",
    "reverse shell",
    "эксплойт",
    "уязвимост",
    "пентест",
    "обход",
]

DEFENSIVE_KEYWORDS = [
    "detection",
    "mitigation",
    "patch",
    "harden",
    "blue team",
    "soc",
    "siem",
    "xdr",
    "edr",
    "incident response",
    "forensic",
    "threat hunting",
    "defense",
    "defensive",
    "secure configuration",
    "advisory",
    "fix update",
    "remediat",
    "обнаружен",
    "митигац",
    "патч",
    "реагирован",
    "форенз",
]

CONTENT_TYPE_RULES: list[tuple[str, list[str]]] = [
    (
        "incident_report",
        [
            "incident report",
            "incident response",
            "dfir",
            "post-mortem",
            "postmortem",
            "threat report",
            "apt report",
            "case study",
            "investigation",
            "breach report",
            "intrusion",
            "how the attack",
            "attack chain",
            "расследован",
            "разбор инцидент",
            "отчет об инцидент",
            "отчёт об инцидент",
            "анализ атак",
            "разбор атак",
            "кейс расследован",
            "форенз",
            "реакция на инцидент",
            "анализ кампании",
        ],
    ),
    ("advisory", ["advisory", "security update", "security bulletin", "cve-", "бюллетень"]),
    ("writeup", ["writeup", "walkthrough", "ctf", "how we hacked", "разбор ctf"]),
    ("release", ["release", "announcing", "launched", "open source", "github.com", "релиз"]),
    ("research", ["research", "analysis", "deep dive", "paper", "whitepaper", "исследован"]),
]

TECH_RULES: list[tuple[str, list[str]]] = [
    ("web", ["xss", "sqli", "csrf", "ssrf", "web app", "http", "browser", "javascript"]),
    ("network", ["dns", "vpn", "firewall", "router", "tcp", "lateral movement", "smb"]),
    ("malware", ["malware", "ransomware", "trojan", "botnet", "loader", "backdoor"]),
    ("cloud", ["aws", "azure", "gcp", "kubernetes", "container", "cloud"]),
    ("identity", ["oauth", "sso", "active directory", "kerberos", "auth", "mfa", "iam"]),
    ("mobile", ["android", "ios", "mobile app", "apk"]),
    ("hardware", ["firmware", "uefi", "bios", "chip", "hardware", "iot"]),
]


def _text_blob(*parts: str | None) -> str:
    return " ".join(p for p in parts if p).lower()


def is_legislation(title: str, summary: str | None = None) -> bool:
    text = _text_blob(title, summary)
    return any(re.search(p, text, re.I) for p in LEGISLATION_PATTERNS)


def classify_direction(title: str, summary: str | None = None) -> str:
    text = _text_blob(title, summary)
    off = sum(1 for k in OFFENSIVE_KEYWORDS if k in text)
    deff = sum(1 for k in DEFENSIVE_KEYWORDS if k in text)
    if off and deff:
        return "both"
    if off:
        return "offensive"
    if deff:
        return "defensive"
    return "both"


def classify_content_type(title: str, summary: str | None = None) -> str:
    text = _text_blob(title, summary)
    for ctype, keys in CONTENT_TYPE_RULES:
        if any(k in text for k in keys):
            return ctype
    return "news"


def classify_technologies(title: str, summary: str | None = None) -> list[str]:
    text = _text_blob(title, summary)
    found = [name for name, keys in TECH_RULES if any(k in text for k in keys)]
    return found


def classify(
    title: str,
    summary: str | None = None,
    *,
    prefer_type: str | None = None,
) -> dict:
    return {
        "is_legislation": is_legislation(title, summary),
        "direction": classify_direction(title, summary),
        "content_type": prefer_type or classify_content_type(title, summary),
        "technologies": classify_technologies(title, summary),
    }
