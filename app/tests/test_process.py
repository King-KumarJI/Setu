from app.utils import process


def test_run_executes_echo_and_captures_stdout():
    result = process.run(["echo", "hello"])
    assert result.ok
    assert "hello" in result.stdout


def test_run_never_uses_shell_true(monkeypatch):
    captured = {}

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["shell"] = kwargs.get("shell")
        return _Completed()

    monkeypatch.setattr(process.subprocess, "run", fake_run)
    process.run(["echo", "hi"])

    assert captured["shell"] is False
    assert isinstance(captured["args"], list)
