import json

import httpx
import pytest

from owd.llm import LLM, LLMError, Model, extract_json, models_from_settings

ENV = {"GEMINI_API_KEY": "G-SECRET", "OPENROUTER_API_KEY": "O-SECRET", "CLOUDFLARE_AI_TOKEN": "C-SECRET",
       "CLOUDFLARE_ACCOUNT_ID": "acc"}


def gemini_ok(text, finish="STOP"):
    parts = [{"text": "let me think", "thought": True}, {"text": text}]
    return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}, "finishReason": finish}]})


def chat_ok(text, finish="stop"):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}, "finish_reason": finish}]})


def make(handler, models, env=ENV):
    return LLM(models, http=httpx.Client(transport=httpx.MockTransport(handler)), env=env)


def test_extract_json_handles_fences_and_chatter():
    assert extract_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('noise {"a": {"b": 2}} trailing') == {"a": {"b": 2}}
    for bad in ("no json here", "[1, 2]"):
        with pytest.raises(ValueError):
            extract_json(bad)


def test_models_from_settings_keep_provider_order():
    settings = {"llm": {"openrouter": ["o1"], "gemini": ["g1", "g2"], "cloudflare": ["c1"]}}
    assert [m.label for m in models_from_settings(settings)] == ["gemini:g1", "gemini:g2", "openrouter:o1", "cloudflare:c1"]


def test_gemini_request_and_thinking_parts_are_skipped():
    seen = []

    def handler(request):
        seen.append(request)
        return gemini_ok('{"ok": true}')

    reply = make(handler, [Model("gemini", "gemini-x")]).complete_json("SYS", "USER")
    assert reply.data == {"ok": True} and reply.model.label == "gemini:gemini-x"
    request = seen[0]
    assert request.url.path.endswith("/models/gemini-x:generateContent")
    assert request.headers["x-goog-api-key"] == "G-SECRET"
    body = json.loads(request.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert body["contents"][0]["parts"][0]["text"] == "USER"
    assert body["generationConfig"]["responseMimeType"] == "application/json"


def test_falls_back_on_rate_limits_bad_json_and_failed_validation():
    def handler(request):
        if "googleapis" in str(request.url):
            return httpx.Response(429)
        model = json.loads(request.content)["model"]
        return chat_ok({"bad-json": "not json", "invalid": '{"n": 1}'}.get(model, '{"n": 3}'))

    def validate(data):
        if data["n"] != 3:
            raise ValueError("n must be 3")

    models = [Model("gemini", "g"), Model("openrouter", "bad-json"), Model("openrouter", "invalid"),
              Model("openrouter", "good")]
    reply = make(handler, models).complete_json("s", "u", validate=validate)
    assert reply.model.name == "good"
    assert len(reply.attempts) == 3
    assert "rate limited" in reply.attempts[0] and "n must be 3" in reply.attempts[2]


def test_an_auth_error_skips_the_provider_and_keys_never_leak():
    calls = []

    def handler(request):
        calls.append(request)
        if "openrouter" in str(request.url):
            return httpx.Response(401, text="invalid key O-SECRET")
        return chat_ok('{"ok": 1}')

    models = [Model("openrouter", "a"), Model("openrouter", "b"), Model("cloudflare", "@cf/x")]
    reply = make(handler, models).complete_json("s", "u")
    assert reply.model.provider == "cloudflare"
    assert sum("openrouter" in str(c.url) for c in calls) == 1  # model "b" was skipped
    cloudflare = calls[-1]
    assert cloudflare.url.path == "/client/v4/accounts/acc/ai/v1/chat/completions"
    assert cloudflare.headers["authorization"] == "Bearer C-SECRET"
    assert json.loads(cloudflare.content)["response_format"] == {"type": "json_object"}
    assert all("SECRET" not in attempt for attempt in reply.attempts)


def test_cut_off_answers_are_rejected_and_total_failure_raises():
    def handler(request):
        if "googleapis" in str(request.url):
            return gemini_ok('{"a": ', finish="MAX_TOKENS")
        return chat_ok('{"a": 1}', finish="length")

    with pytest.raises(LLMError) as error:
        make(handler, [Model("gemini", "g"), Model("openrouter", "o")]).complete_json("s", "u")
    assert "MAX_TOKENS" in str(error.value) and "length" in str(error.value)
    assert "SECRET" not in str(error.value)


def test_models_without_keys_are_dropped():
    llm = make(lambda request: chat_ok("{}"), [Model("gemini", "g"), Model("cloudflare", "c")],
               env={"GEMINI_API_KEY": " ", "CLOUDFLARE_AI_TOKEN": "t"})  # no account id: no Cloudflare
    with pytest.raises(LLMError, match="No language model"):
        llm.complete_json("s", "u")


def test_network_errors_fall_through_to_the_next_model():
    def handler(request):
        if "googleapis" in str(request.url):
            raise httpx.ConnectError("offline", request=request)
        return chat_ok('{"ok": 1}')

    reply = make(handler, [Model("gemini", "g"), Model("openrouter", "o")]).complete_json("s", "u")
    assert reply.model.provider == "openrouter" and "ConnectError" in reply.attempts[0]


def test_a_busy_model_is_retried_once_after_a_wait():
    responses = iter([httpx.Response(503, text="high demand"), gemini_ok('{"ok": 1}'),
                      httpx.Response(503), httpx.Response(503)])
    waits = []
    llm = LLM([Model("gemini", "g")], http=httpx.Client(transport=httpx.MockTransport(lambda r: next(responses))),
              env=ENV, sleep=waits.append)
    assert llm.complete_json("s", "u").data == {"ok": 1} and waits == [20.0]
    with pytest.raises(LLMError, match="HTTP 503"):
        llm.complete_json("s", "u")
    assert waits == [20.0, 20.0]
