import io
import json
import urllib.error

import pytest

from apply_and_sort.company import (
    AIError,
    CompanyClassifier,
    LLMSettings,
    load_classifier,
    parse_info,
    validate_base_url,
)
from apply_and_sort.config import default_config


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def chat_response(content):
    return FakeResponse(json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8"))


class FakeOpener:
    def __init__(self, *results):
        self.results = list(results)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "error", {}, io.BytesIO(b""))


def classifier(opener, **settings):
    base = {"base_url": "https://api.example.com/v1/", "model": "test-model", "api_key": "secret"}
    return CompanyClassifier(LLMSettings(**{**base, **settings}), opener=opener, sleep=lambda s: None)


def test_parse_info_takes_last_json_object():
    text = '{"size": "중소기업"} 이라고 생각했지만\n{"size": "중견기업", "industry": "교육", "reason": "중견기업 확인서"}'

    info = parse_info(text)

    assert (info.size, info.industry, info.reason) == ("중견기업", "교육", "중견기업 확인서")


def test_parse_info_unknown_when_missing_or_invalid():
    assert parse_info("잘 모르겠어요").size == "알수없음"
    assert parse_info('{"size": "스타트업"}').size == "알수없음"
    assert parse_info('{"size": 중견기업}').size == "알수없음"


def test_classify_sends_openai_compatible_request():
    opener = FakeOpener(chat_response('{"size": "대기업", "industry": "IT"}'))

    info = classifier(opener).classify("가나다랩", "콘텐츠 마케터")

    assert info.size == "대기업"
    request = opener.requests[0]
    assert request.full_url == "https://api.example.com/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer secret"
    body = json.loads(request.data)
    assert body["model"] == "test-model"
    assert "가나다랩" in body["messages"][1]["content"] and "콘텐츠 마케터" in body["messages"][1]["content"]
    assert "합격" not in body["messages"][1]["content"]  # 회사명·직무 외 정보는 보내지 않음


def test_classify_retries_rate_limit_then_succeeds():
    opener = FakeOpener(http_error(429), chat_response('{"size": "중소기업"}'))

    assert classifier(opener).classify("가나다랩").size == "중소기업"
    assert len(opener.requests) == 2


@pytest.mark.parametrize("code, text", [(401, "API 키"), (404, "모델 이름")])
def test_classify_explains_http_errors(code, text):
    with pytest.raises(AIError, match=text):
        classifier(FakeOpener(http_error(code))).classify("가나다랩")


def test_classify_hints_local_gateway_when_unreachable():
    opener = FakeOpener(*[urllib.error.URLError("refused")] * 3)

    with pytest.raises(AIError, match="게이트웨이"):
        classifier(opener, base_url="http://127.0.0.1:31415/v1").classify("가나다랩")


def test_classify_rejects_non_openai_response():
    with pytest.raises(AIError, match="OpenAI 호환"):
        classifier(FakeOpener(FakeResponse(b'{"result": "ok"}'))).classify("가나다랩")


def test_validate_base_url_allows_https_and_localhost_only():
    assert validate_base_url("https://api.openai.com/v1/chat/completions") == "https://api.openai.com/v1"
    assert validate_base_url("http://127.0.0.1:31415/v1") == "http://127.0.0.1:31415/v1"
    with pytest.raises(ValueError):
        validate_base_url("http://example.com/v1")


def test_load_classifier_needs_url_model_and_key(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = default_config()

    assert load_classifier(config, config_path) is None  # 아무것도 없음
    config["llm"].update({"base_url": "http://127.0.0.1:31415/v1", "model": "auto"})
    assert load_classifier(config, config_path) is None  # 키 없음
    (tmp_path / "llm_api_key.txt").write_text("secret", encoding="utf-8")
    assert load_classifier(config, config_path) is not None
