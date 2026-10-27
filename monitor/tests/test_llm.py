import json
from datetime import datetime, timezone

import httpx
import pytest

from mail_monitor.classify import LLMClassifier
from mail_monitor.config import load_settings
from mail_monitor.llm import LLMClient, LLMError, parse_json_object
from mail_monitor.models import MessageHeader


def test_parse_json_object_tolerates_fences_and_prose():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('结果如下：{"a": {"b": 2}} 以上。') == {"a": {"b": 2}}
    with pytest.raises(LLMError):
        parse_json_object("没有 json")
    with pytest.raises(LLMError):
        parse_json_object("[1, 2]")


def _client(handler, **kwargs) -> LLMClient:
    return LLMClient(
        api_key="k", base_url="https://api.deepseek.com", model="deepseek-flash", transport=httpx.MockTransport(handler), **kwargs
    )


async def test_chat_json_posts_openai_compatible_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["Authorization"] == "Bearer k"
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"} and payload["model"] == "deepseek-flash"
        assert "thinking" not in payload
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"needs_action": "yes"}'}}]})

    assert await _client(handler).chat_json("sys", "user") == {"needs_action": "yes"}


async def test_chat_json_merges_extra_body():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["thinking"] == {"type": "disabled"} and payload["max_tokens"] == 800
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"needs_action": "no"}'}}]})

    client = _client(handler, extra_body={"thinking": {"type": "disabled"}})
    assert await client.chat_json("sys", "user") == {"needs_action": "no"}


def test_settings_turn_off_deepseek_thinking_unless_overridden(tmp_path, monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_MODEL", "LLM_EXTRA_BODY"):
        monkeypatch.delenv(name, raising=False)
    missing = tmp_path / "missing.env"

    settings = load_settings(missing)
    assert settings.llm_model == "deepseek-flash"
    assert settings.resolved_llm_extra_body == {"thinking": {"type": "disabled"}}

    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    assert load_settings(missing).resolved_llm_extra_body == {}

    monkeypatch.setenv("LLM_EXTRA_BODY", '{"enable_thinking": false}')
    assert load_settings(missing).resolved_llm_extra_body == {"enable_thinking": False}

    monkeypatch.delenv("LLM_BASE_URL")
    monkeypatch.setenv("LLM_EXTRA_BODY", "{}")
    assert load_settings(missing).resolved_llm_extra_body == {}  # 显式写 {} 就什么都不加

    monkeypatch.setenv("LLM_EXTRA_BODY", "[1]")
    with pytest.raises(ValueError, match="LLM_EXTRA_BODY"):
        load_settings(missing)


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


async def test_llm_prompt_carries_profile_and_memory_and_relation():
    from mail_monitor.memory import Memory, SenderMemo

    def handler(request: httpx.Request) -> httpx.Response:
        messages = json.loads(request.content)["messages"]
        assert "收件人的情况：MBZUAI 在读硕士，找 AI Agent 方向的工作" in messages[0]["content"]
        assert "relation:" in messages[0]["content"] and "导师、课题组同事" in messages[0]["content"]
        user = messages[1]["content"]
        assert "记忆（我们之前的记录，仅供参考）：\n- 发件人 hr@quantfirm.example：身份=HR/招聘方（模型判断）；之前 2 封，其中 1 封需要处理" in user
        assert user.index("记忆") < user.index("正文开始")
        verdict = {"who": "量化公司 HR", "relation": " HR/招聘方 ", "what": "面试改到周三", "needs_action": "yes", "confidence": 0.8}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(verdict, ensure_ascii=False)}}]})

    memory = Memory(sender=SenderMemo(email="hr@quantfirm.example", name="Talent Team", relation="HR/招聘方", relation_source="llm", total=2, needs_action=1))
    classifier = LLMClassifier(_client(handler), timezone="Asia/Dubai", profile="MBZUAI 在读硕士，找 AI Agent 方向的工作")
    decision = await classifier.classify(header(), "Rescheduled to Wednesday", None, memory)
    assert decision.relation == "HR/招聘方" and decision.who == "量化公司 HR"


async def test_fallback_uses_memory_for_who():
    from mail_monitor.classify import FallbackClassifier
    from mail_monitor.memory import Memory, SenderMemo

    memory = Memory(sender=SenderMemo(email="hr@quantfirm.example", name=None, relation="HR/招聘方", relation_source="llm", total=1, needs_action=0))
    decision = await FallbackClassifier().classify(header(), None, None, memory)
    assert decision.who == "HR/招聘方 Talent Team" and decision.relation == "HR/招聘方" and decision.needs_action == "unsure"
    hinted = await FallbackClassifier().classify(header(), None, {"who": "规则说的"}, memory)
    assert hinted.who == "规则说的"
