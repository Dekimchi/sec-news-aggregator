from app.security import is_http_url, safe_next_url


def test_safe_next_url_allows_relative_paths():
    assert safe_next_url("/updates") == "/updates"
    assert safe_next_url("/article/1?x=1") == "/article/1?x=1"


def test_safe_next_url_blocks_open_redirects():
    assert safe_next_url("//evil.com") == "/"
    assert safe_next_url("/\\evil.com") == "/"
    assert safe_next_url("https://evil.com") == "/"
    assert safe_next_url("http://evil.com/path") == "/"


def test_is_http_url():
    assert is_http_url("https://example.com/feed")
    assert is_http_url("http://example.com/feed")
    assert not is_http_url("file:///etc/passwd")
    assert not is_http_url("ftp://example.com/feed")
    assert not is_http_url("not-a-url")
