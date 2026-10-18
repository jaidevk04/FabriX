import os

from cognition.config import environment_python, load_environment, worker_interpreter


def test_local_settings_load_without_overriding_process_environment(tmp_path, monkeypatch):
    settings = tmp_path / ".env"
    settings.write_text("GEMINI_MODEL=file-model\nCOGNITION_TIMEOUT=45\n", encoding="utf-8")
    monkeypatch.setenv("GEMINI_MODEL", "host-model")
    monkeypatch.delenv("COGNITION_TIMEOUT", raising=False)
    load_environment(settings)
    assert os.environ["GEMINI_MODEL"] == "host-model"
    assert os.environ["COGNITION_TIMEOUT"] == "45"


def test_loads_only_the_working_directory_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    (tmp_path / ".env").write_text("GEMINI_MODEL=local-model\n", encoding="utf-8")
    load_environment()
    assert os.environ["GEMINI_MODEL"] == "local-model"


def test_environment_layouts(tmp_path):
    assert environment_python(tmp_path, windows=True) == tmp_path / "Scripts" / "python.exe"
    assert environment_python(tmp_path, windows=False) == tmp_path / "bin" / "python"


def test_relative_environment_and_discovery(tmp_path, monkeypatch):
    executable = environment_python(tmp_path / ".venv-antigravity")
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv("COGNITION_ANTIGRAVITY_PYTHON", ".venv-antigravity")
    assert worker_interpreter("antigravity", tmp_path) == str(executable.resolve())
    monkeypatch.delenv("COGNITION_ANTIGRAVITY_PYTHON")
    # One virtual environment: a .venv-<name> directory is no longer discovered automatically.
    assert worker_interpreter("antigravity", tmp_path) is None


def test_explicit_interpreter_override(tmp_path, monkeypatch):
    custom = tmp_path / "custom-python"
    monkeypatch.setenv("COGNITION_ANTIGRAVITY_PYTHON", str(custom))
    assert worker_interpreter("antigravity", tmp_path) == str(custom.resolve())
