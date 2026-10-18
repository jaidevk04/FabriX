import pytest

from scripts import bootstrap


def test_first_launch_creates_settings_and_repeat_preserves_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    (tmp_path / ".env.example").write_text("GOOGLE_API_KEY=\n", encoding="utf-8")
    bootstrap.preserve_settings()
    settings = tmp_path / ".env"
    assert settings.read_text(encoding="utf-8") == "GOOGLE_API_KEY=\n"
    settings.write_text("GOOGLE_API_KEY=example-test-value\n", encoding="utf-8")
    bootstrap.preserve_settings()
    assert settings.read_text(encoding="utf-8") == "GOOGLE_API_KEY=example-test-value\n"


def test_only_avenor_health_is_accepted(monkeypatch):
    from io import BytesIO

    monkeypatch.setattr(
        bootstrap.urllib.request, "urlopen", lambda *a, **k: BytesIO(b'{"status":"ok"}')
    )
    assert not bootstrap.healthy("http://127.0.0.1:8000")
    monkeypatch.setattr(
        bootstrap.urllib.request,
        "urlopen",
        lambda *a, **k: BytesIO(b'{"application":"avenor","status":"ok"}'),
    )
    assert bootstrap.healthy("http://127.0.0.1:8000")


def test_environment_outside_project_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(bootstrap, "ROOT", root)
    with pytest.raises(RuntimeError, match="inside the application"):
        bootstrap.ensure_environment(tmp_path / "outside", None, False)


def test_incompatible_environment_is_preserved_on_install_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    old = tmp_path / ".venv"
    old.mkdir()
    (old / "pyvenv.cfg").write_text("home = other-platform\n", encoding="utf-8")
    (old / "original.txt").write_text("preserve", encoding="utf-8")

    def unavailable(*args):
        raise RuntimeError("download unavailable")

    monkeypatch.setattr(bootstrap, "run", unavailable)
    with pytest.raises(RuntimeError, match="download unavailable"):
        bootstrap.ensure_environment(old, None, False)
    backups = list((tmp_path / ".runtime" / "backups").iterdir())
    assert len(backups) == 1
    assert (backups[0] / "original.txt").read_text(encoding="utf-8") == "preserve"
