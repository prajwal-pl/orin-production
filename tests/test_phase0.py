from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import main
from orchestration import agents, bot, nodes
from orchestration.schema import Classification, Verifier


@pytest.fixture
def telegram_update(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123")
    monkeypatch.setenv("ORIN_DATABASE_PATH", str(tmp_path / "tasks.db"))
    message = SimpleNamespace(text="Check GitHub", reply_text=AsyncMock())
    return SimpleNamespace(effective_user=SimpleNamespace(id=123), message=message)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,expected", [("github-task", "github"), ("gmail-task", "gmail"), ("other", "other")])
async def test_phase0_graph_routing(monkeypatch, kind, expected):
    calls = []

    async def fake_model(role, message):
        calls.append(role)
        if role == "classifier":
            return Classification(type=kind, intent="check", arguments={})
        return Verifier(status="pass", feedback="ok", verification_result={"checked": True}, final_response="Mock complete")

    monkeypatch.setattr(nodes, "invoke_structured", fake_model)
    result = await bot.graph.ainvoke({
        "user_id": "123", "message": "Check GitHub", "intent": "", "service": "other",
        "arguments": {}, "execution_result": {}, "execution_status": "pending",
        "verification_result": {}, "verification_status": "pending", "feedback": "",
        "retry_count": 0, "final_response": "",
    })
    if expected == "other":
        assert "read-only workflows" in result["final_response"]
        assert calls == ["classifier"]
    else:
        assert result["final_response"] == "Mock complete"
        assert calls == ["classifier", "verifier"]


@pytest.mark.asyncio
async def test_verification_retries_three_times_and_stops(monkeypatch, telegram_update):
    calls = []

    async def fake_model(role, message):
        calls.append(role)
        if role == "classifier":
            return Classification(type="github-task", intent="check", arguments={})
        return Verifier(status="retry", feedback="bad", verification_result={"reason": "bad"}, final_response=None)

    monkeypatch.setattr(nodes, "invoke_structured", fake_model)
    result = await bot.graph.ainvoke({
        "user_id": "123", "message": "Check GitHub", "intent": "", "service": "other",
        "arguments": {}, "execution_result": {}, "execution_status": "pending",
        "verification_result": {}, "verification_status": "pending", "feedback": "",
        "retry_count": 0, "final_response": "",
    })
    assert result["retry_count"] == 3
    assert result["execution_status"] == "failed"
    assert result["verification_result"] == {"reason": "bad"}
    assert calls == ["classifier", "verifier", "verifier", "verifier"]


@pytest.mark.asyncio
async def test_empty_verifier_reply_has_fallback(monkeypatch):
    async def fake_model(role, message):
        if role == "classifier":
            return Classification(type="gmail-task", intent="check", arguments={})
        return Verifier(status="pass", feedback="ok", verification_result={}, final_response=None)

    monkeypatch.setattr(nodes, "invoke_structured", fake_model)
    result = await bot.graph.ainvoke({
        "user_id": "123", "message": "Check GitHub", "intent": "", "service": "other",
        "arguments": {}, "execution_result": {}, "execution_status": "pending",
        "verification_result": {}, "verification_status": "pending", "feedback": "",
        "retry_count": 0, "final_response": "",
    })
    assert "mock task finished" in result["final_response"]


@pytest.mark.asyncio
async def test_unauthorized_user_never_calls_graph(monkeypatch, telegram_update):
    telegram_update.effective_user.id = 456
    mock_graph = SimpleNamespace(ainvoke=AsyncMock())
    monkeypatch.setattr(bot, "graph", mock_graph)
    await bot.telegram_bot_message(telegram_update, None)
    mock_graph.ainvoke.assert_not_awaited()
    assert telegram_update.message.reply_text.await_args.args == (bot.DENIED_REPLY,)
    await main.start(telegram_update, None)
    assert telegram_update.message.reply_text.await_count == 2


def test_configuration(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123, 456")
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder")
    assert main.validate_configuration() == "123:ABC"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        main.validate_configuration()
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "bad")
    with pytest.raises(ValueError, match="numeric"):
        main.validate_configuration()


@pytest.mark.asyncio
async def test_model_fallback_and_malformed_output(monkeypatch):
    monkeypatch.setenv("ORIN_MODEL", "first")
    monkeypatch.setenv("ORIN_FALLBACK_MODEL", "second")
    tried = []

    def fake_build(role, model):
        tried.append(model)
        if model == "first":
            return SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError("unavailable")))
        return SimpleNamespace(ainvoke=AsyncMock(return_value={"structured_response": {"type": "other", "intent": "test", "arguments": {}}}))

    monkeypatch.setattr(agents, "build_agent", fake_build)
    result = await agents.invoke_structured("classifier", "test")
    assert result.type == "other"
    assert tried == ["first", "second"]

    def malformed(role, model):
        return SimpleNamespace(ainvoke=AsyncMock(return_value={"structured_response": {"type": "invalid"}}))

    monkeypatch.setattr(agents, "build_agent", malformed)
    with pytest.raises(RuntimeError, match="model call failed"):
        await agents.invoke_structured("classifier", "test")

@pytest.mark.asyncio
async def test_failed_verification_recovers_on_retry(monkeypatch):
    attempts = 0

    async def fake_model(role, message):
        nonlocal attempts
        if role == "classifier":
            return Classification(type="github-task", intent="check", arguments={})
        attempts += 1
        return Verifier(
            status="retry" if attempts == 1 else "pass",
            feedback="checked",
            verification_result={"attempt": attempts},
            final_response="Verified mock task" if attempts == 2 else None,
        )

    monkeypatch.setattr(nodes, "invoke_structured", fake_model)
    result = await bot.graph.ainvoke({
        "user_id": "123", "message": "Check GitHub", "intent": "", "service": "other",
        "arguments": {}, "execution_result": {}, "execution_status": "pending",
        "verification_result": {}, "verification_status": "pending", "feedback": "",
        "retry_count": 0, "final_response": "",
    })
    assert attempts == 2
    assert result["final_response"] == "Verified mock task"


def test_application_registers_handlers(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123")
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder")
    application = main.build_application(main.validate_configuration())
    assert len(application.handlers[0]) == 5


@pytest.mark.asyncio
async def test_telegram_reply_failure_is_contained(monkeypatch, telegram_update):
    telegram_update.effective_user.id = 456
    telegram_update.message.reply_text.side_effect = RuntimeError("Telegram unavailable")
    await bot.telegram_bot_message(telegram_update, None)
    await main.start(telegram_update, None)
    assert telegram_update.message.reply_text.await_count == 2

@pytest.mark.asyncio
async def test_terminal_verification_failure_does_not_retry(monkeypatch):
    calls = []

    async def fake_model(role, message):
        calls.append(role)
        if role == "classifier":
            return Classification(type="github-task", intent="check", arguments={})
        return Verifier(status="fail", feedback="terminal", verification_result={}, final_response=None)

    monkeypatch.setattr(nodes, "invoke_structured", fake_model)
    result = await bot.graph.ainvoke({
        "user_id": "123", "message": "Check GitHub", "intent": "", "service": "other",
        "arguments": {}, "execution_result": {}, "execution_status": "pending",
        "verification_result": {}, "verification_status": "pending", "feedback": "",
        "retry_count": 0, "final_response": "",
    })
    assert calls == ["classifier", "verifier"]
    assert "could not verify" in result["final_response"]
