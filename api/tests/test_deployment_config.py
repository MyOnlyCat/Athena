import re
from pathlib import Path


def test_file_api_proxy_streams_requests_and_responses_without_buffering() -> None:
    config = (
        Path(__file__).resolve().parents[2] / "deploy" / "nginx.conf"
    ).read_text(encoding="utf-8")
    match = re.search(
        r"location\s+\^~\s+/api/v1/files/\s*\{(?P<body>.*?)^\s*\}",
        config,
        flags=re.DOTALL | re.MULTILINE,
    )

    assert match is not None
    body = match.group("body")
    assert "proxy_request_buffering off;" in body
    assert "proxy_buffering off;" in body
    assert "proxy_set_header Authorization $http_authorization;" in body
    assert "proxy_pass http://api:8000;" in body
    assert "client_max_body_size 1024m;" in config
