from app.notify import format_daily_digest


def test_format_daily_digest_with_links():
    text = format_daily_digest(
        [
            {
                "title_ru": "Тест XSS",
                "interest_score": 80,
                "source_name": "Lab",
                "url": "https://example.com/a",
                "brief_ru": "Кратко",
            }
        ]
    )
    assert "sec-news" in text
    assert "Тест XSS" in text
    assert 'href="https://example.com/a"' in text
    assert "читать →" in text
    assert "<b>" in text


def test_format_daily_digest_empty():
    text = format_daily_digest([])
    assert "интересных статей нет" in text
