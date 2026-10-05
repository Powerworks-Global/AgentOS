import json

from agentos_pilot.metrics import RunMetrics
from agentos_pilot.notify import TelegramConfig, format_run_result, notify_run_result, send_message


def _metrics(**overrides):
    base = dict(
        task="add input validation",
        branch_name="pilot/123",
        started_at=1.0,
        finished_at=2.0,
        exit_code=0,
        success=True,
        task_id="t-1",
        num_turns=4,
        total_cost_usd=0.0123,
        permission_denials=0,
    )
    base.update(overrides)
    return RunMetrics(**base)


def test_from_env_requires_both_vars(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert TelegramConfig.from_env() is None

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    assert TelegramConfig.from_env() is None  # chat id still missing

    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    config = TelegramConfig.from_env()
    assert config == TelegramConfig(bot_token="tok", chat_id="123")


def test_format_run_result_includes_success_and_cost():
    text = format_run_result(_metrics())
    assert "SUCCESS" in text
    assert "add input validation" in text
    assert "0.0123" in text


def test_format_run_result_includes_failure_and_denials():
    text = format_run_result(_metrics(success=False, permission_denials=2, exit_code=1))
    assert "FAILED" in text
    assert "permission denials: 2" in text


def test_notify_run_result_is_noop_without_config(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notify_run_result(_metrics()) is False


def test_notify_run_result_sends_when_configured(monkeypatch):
    sent = {}

    def fake_send(config, text):
        sent["config"] = config
        sent["text"] = text
        return True

    monkeypatch.setattr("agentos_pilot.notify.send_message", fake_send)
    config = TelegramConfig(bot_token="tok", chat_id="123")

    result = notify_run_result(_metrics(), config)

    assert result is True
    assert sent["config"] == config
    assert "SUCCESS" in sent["text"]


def test_send_message_posts_expected_body(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=10):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("agentos_pilot.notify.urllib.request.urlopen", fake_urlopen)

    config = TelegramConfig(bot_token="tok", chat_id="123")
    assert send_message(config, "hello") is True
    assert captured["url"] == "https://api.telegram.org/bottok/sendMessage"
    assert captured["body"] == {"chat_id": "123", "text": "hello"}


def test_send_message_returns_false_on_network_error(monkeypatch):
    import urllib.error

    def fake_urlopen(request, timeout=10):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr("agentos_pilot.notify.urllib.request.urlopen", fake_urlopen)

    config = TelegramConfig(bot_token="tok", chat_id="123")
    assert send_message(config, "hello") is False
