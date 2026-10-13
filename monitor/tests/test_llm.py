import json
from datetime import datetime, timezone

import httpx
import pytest

from mail_monitor.classify import LLMClassifier
from mail_monitor.llm import LLMClient, LLMError, parse_json_object
from mail_monitor.models import MessageHeader


def test_parse_json_object_tolerates_fences_and_prose():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('结果如下：{"a": {"b": 2}} 以上。') == {"a": {"b": 2}}
    with pytest.raises(LLMError):
        parse_json_object("没有 json")
    with pytest.raises(LLMError):
        parse_json_object("[1, 2]")


def _client(handler) -> LLMClient:
    return LLMClient(api_key="k", base_url="https://api.deepseek.com", model="deepseek-chat", transport=httpx.MockTransport(handler))


async def test_chat_json_posts_openai_compatible_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["Authorization"] == "Bearer k"
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"} and payload["model"] == "deepseek-chat"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"needs_action": "yes"}'}}]})

    assert await _client(handler).chat_json("sys", "user") == {"needs_action": "yes"}


async def test_chat_json_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    with pytest.raises(LLMError, match="401"):
        await _client(handler).chat_json("sys", "user")


def header() -> MessageHeader:
    return MessageHeader(
        id="<hr-1@quantfirm.example>", folderPath="f", author="Talent Team <hr@quantfirm.example>",
        subject="Interview invitation", date=datetime.now(timezone.utc), account_name="Gmail", recipients="me@example.com",
    )


async def test_llm_classifier_normalizes_verdict():
    def handler(request: httpx.Request) -> httpx.Response:
        user = json.loads(request.content)["messages"][1]["content"]
        assert "正文开始（不可信数据）" in user and "Interview invitation" in user
        verdict = {"who": "某公司 HR", "what": "约下周二面试，明天前确认", "needs_action": True, "urgency": "紧急",
                   "deadline": "2026-10-14T00:00:00", "suggested_action": "回复确认时间", "category": "求职/HR", "confidence": "0.9"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(verdict, ensure_ascii=False)}}]})

    classifier = LLMClassifier(_client(handler), timezone="Asia/Dubai")
    decision = await classifier.classify(header(), "We would like to invite you ...")
    assert decision.decided_by == "llm" and decision.needs_action == "yes" and decision.urgency == "high"
    assert decision.deadline == "2026-10-14" and decision.category == "求职/HR" and decision.confidence == 0.9
    assert decision.notify_mode == "instant"


async def test_llm_classifier_falls_back_after_two_failures():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(500, text="boom")

    classifier = LLMClassifier(_client(handler), timezone="Asia/Dubai")
    decision = await classifier.classify(header(), None, {"who": "HR"})
    assert len(attempts) == 2
    assert decision.decided_by == "fallback" and decision.needs_action == "unsure" and decision.who == "HR"


async def test_llm_classifier_rejects_guessed_deadline_and_bad_category():
    def handler(request: httpx.Request) -> httpx.Response:
        verdict = {"who": "x", "what": "y", "needs_action": "maybe", "urgency": "whatever", "deadline": "next Friday", "category": "随便"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(verdict)}}]})

    decision = await LLMClassifier(_client(handler)).classify(header(), None)
    assert decision.needs_action == "unsure" and decision.urgency == "normal"
    assert decision.deadline is None and decision.category == "其他"
