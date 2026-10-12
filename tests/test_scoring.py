from datetime import datetime, timezone

from app.scoring import HOT_THRESHOLD, compute_interest_score, interest_tier


def test_incident_cve_outranks_plain_news():
    now = datetime.now(timezone.utc).isoformat()
    hot = compute_interest_score(
        title="Critical RCE: CVE-2024-12345 actively exploited",
        summary="Remote code execution in enterprise VPN",
        content_type="incident_report",
        technologies=["network", "cloud"],
        published_at=now,
        translated=True,
    )
    plain = compute_interest_score(
        title="Weekly security newsletter roundup",
        summary="Assorted industry links",
        content_type="news",
        technologies=[],
        published_at=now,
        translated=False,
    )
    assert hot > plain
    assert hot >= HOT_THRESHOLD
    assert interest_tier(hot) in {"hot", "strong"}
    assert interest_tier(plain) is None


def test_score_clamped_to_100():
    now = datetime.now(timezone.utc).isoformat()
    score = compute_interest_score(
        title="CVE-2024-1 zero-day RCE ransomware APT critical actively exploited privilege escalation wormable",
        summary="exploit auth bypass supply-chain",
        content_type="incident_report",
        technologies=["web", "network", "malware", "cloud", "identity"],
        published_at=now,
        translated=True,
    )
    assert 0 <= score <= 100
