import base64
import hashlib
import hmac
import json

import httpx
import pytest

from mail_monitor.notify import LarkAppNotifier, LarkWebhookNotifier, NotifyError, build_notifier, lark_webhook_sign
from mail_monitor.config import Settings


def test_webhook_signature_matches_lark_algorithm():
    expected = base64.b64encode(hmac.new(b"1700000000\nsecret", b"", hashlib.sha256).digest()).decode()
    assert lark_webhook_sign("secret", 1700000000) == expected


async def test_webhook_sends_text_with_signature():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    notifier = LarkWebhookNotifier("https://open.larksuite.com/open-apis/bot/v2/hook/abc", "secret", transport=httpx.MockTransport(handler))
    await notifier.send("你好")
    body = json.loads(seen[0].content)
    assert body["msg_type"] == "text" and body["content"] == {"text": "你好"}
    assert body["sign"] == lark_webhook_sign("secret", int(body["timestamp"]))


async def test_webhook_error_code_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 19021, "msg": "sign match fail"})

    notifier = LarkWebhookNotifier("https://example.invalid/hook", transport=httpx.MockTransport(handler))
    with pytest.raises(NotifyError, match="19021"):
        await notifier.send("x")


async def test_app_notifier_fetches_token_then_sends():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/tenant_access_token/internal"):
            assert json.loads(request.content) == {"app_id": "cli_x", "app_secret": "s"}
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t-1", "expire": 7200})
        assert request.headers["Authorization"] == "Bearer t-1"
        assert request.url.params["receive_id_type"] == "open_id"
        body = json.loads(request.content)
        assert body["receive_id"] == "ou_me" and json.loads(body["content"]) == {"text": "hi"}
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "om_1"}})

    notifier = LarkAppNotifier(domain="https://open.larksuite.com", app_id="cli_x", app_secret="s", receive_id="ou_me", transport=httpx.MockTransport(handler))
    await notifier.send("hi")
    await notifier.send("hi")
    paths = [c.url.path for c in calls]
    assert paths.count("/open-apis/auth/v3/tenant_access_token/internal") == 1  # token 有缓存
    assert paths.count("/open-apis/im/v1/messages") == 2


async def test_app_notifier_lists_chats_and_looks_up_open_id():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t-1", "expire": 7200})
        if path == "/open-apis/im/v1/chats":
            if request.url.params.get("page_token") == "p2":
                return httpx.Response(200, json={"code": 0, "data": {"items": [{"chat_id": "oc_2", "name": "第二群"}], "has_more": False}})
            return httpx.Response(200, json={"code": 0, "data": {"items": [{"chat_id": "oc_1", "name": "邮件雷达"}], "has_more": True, "page_token": "p2"}})
        if path == "/open-apis/contact/v3/users/batch_get_id":
            assert request.url.params["user_id_type"] == "open_id"
            assert json.loads(request.content) == {"emails": ["me@example.com"]}
            return httpx.Response(200, json={"code": 0, "data": {"user_list": [{"user_id": "ou_me", "email": "me@example.com"}]}})
        raise AssertionError(path)

    notifier = LarkAppNotifier(domain="https://open.larksuite.com", app_id="cli_x", app_secret="s", receive_id="", transport=httpx.MockTransport(handler))
    assert await notifier.list_chats() == [{"chat_id": "oc_1", "name": "邮件雷达"}, {"chat_id": "oc_2", "name": "第二群"}]
    assert await notifier.lookup_open_id("me@example.com") == "ou_me"
    with pytest.raises(NotifyError, match="LARK_RECEIVE_ID"):
        await notifier.send("x")


def test_build_notifier_validates_config():
    assert build_notifier(Settings()).name == "console"
    with pytest.raises(NotifyError, match="LARK_WEBHOOK_URL"):
        build_notifier(Settings(notify_backend="lark_webhook"))
    with pytest.raises(NotifyError, match="LARK_APP_ID"):
        build_notifier(Settings(notify_backend="lark_app"))
    assert build_notifier(Settings(notify_backend="lark_webhook", lark_webhook_url="https://x.example/hook")).name == "lark_webhook"
