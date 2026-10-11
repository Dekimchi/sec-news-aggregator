from app.classifier import classify, is_legislation
from app.ingest import clean_text


def test_incident_report_classification():
    result = classify(
        "DFIR Report: Conti ransomware intrusion",
        "Full incident investigation walkthrough",
    )
    assert result["content_type"] == "incident_report"
    assert result["is_legislation"] is False


def test_legislation_detected():
    assert is_legislation("New GDPR privacy law update from lawmakers", "Senate bill")


def test_clean_text_decodes_nbsp():
    text = clean_text("не&nbsp;про&nbsp;торговлю")
    assert "&nbsp;" not in text
    assert text == "не про торговлю"
