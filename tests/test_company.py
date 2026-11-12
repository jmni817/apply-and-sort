from types import SimpleNamespace

from apply_and_sort.company import CompanyClassifier, parse_info


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def response(stop_reason, *blocks):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks))


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def fake_client(*responses):
    messages = FakeMessages(responses)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_parse_info_takes_last_json_line():
    text = '검색해 보니... {"size": "중소기업"} 이라고도 나오지만\n{"size": "중견기업", "industry": "교육", "reason": "사람인 기업형태"}'

    info = parse_info(text)

    assert (info.size, info.industry, info.reason) == ("중견기업", "교육", "사람인 기업형태")


def test_parse_info_unknown_when_missing_or_invalid():
    assert parse_info("결과를 찾지 못했어요").size == "알수없음"
    assert parse_info('{"size": "스타트업"}').size == "알수없음"
    assert parse_info('{"size": 중견기업}').size == "알수없음"


def test_classify_sends_company_and_role_with_web_search():
    client, messages = fake_client(response("end_turn", text_block('{"size": "대기업", "industry": "IT"}')))

    info = CompanyClassifier(client, model="claude-opus-5-5", max_searches=2).classify("가나다랩", "콘텐츠 마케터")

    assert info.size == "대기업"
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["tools"][0]["type"] == "web_search_20260209"
    assert call["tools"][0]["max_uses"] == 2
    assert call["fallbacks"] == "default"
    prompt = call["messages"][0]["content"]
    assert "가나다랩" in prompt and "콘텐츠 마케터" in prompt


def test_classify_continues_after_pause_turn():
    paused = response("pause_turn", text_block("검색 중"))
    client, messages = fake_client(paused, response("end_turn", text_block('{"size": "중소기업"}')))

    info = CompanyClassifier(client).classify("가나다랩")

    assert info.size == "중소기업"
    assert len(messages.calls) == 2
    assert messages.calls[1]["messages"][-1] == {"role": "assistant", "content": paused.content}


def test_classify_refusal_is_unknown():
    client, _ = fake_client(response("refusal"))

    assert CompanyClassifier(client).classify("가나다랩").size == "알수없음"
