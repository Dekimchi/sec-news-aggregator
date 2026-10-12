from app.cluster import cluster_key, extract_cves, normalize_title


def test_extract_cves():
    assert extract_cves("Exploit for CVE-2024-1234 and cve-2024-9999") == [
        "CVE-2024-1234",
        "CVE-2024-9999",
    ]


def test_same_cve_shares_cluster():
    a = cluster_key("Critical bug CVE-2024-1111 in VPN", "details")
    b = cluster_key("VPN vendors patch CVE-2024-1111", "other wording")
    assert a == b


def test_normalize_strips_noise():
    assert "breaking" not in normalize_title("Breaking: Security Advisory Update")
