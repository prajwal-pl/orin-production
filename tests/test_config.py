"""Environment discovery must not depend on the process working directory."""

import os

from orchestration import config


def test_loads_stable_config_from_gui_working_directory(monkeypatch, tmp_path):
    config_home = tmp_path / "home" / "config"
    config_home.mkdir(parents=True)
    (config_home / ".env").write_text("ORIN_CONFIG_TEST_KEY=from-config\n")
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    monkeypatch.setenv("ORIN_CONFIG_DIR", str(config_home))
    monkeypatch.delenv("ORIN_ENV_FILE", raising=False)
    monkeypatch.delenv("ORIN_CONFIG_TEST_KEY", raising=False)

    loaded = config.load_environment()

    assert loaded == (config_home / ".env").resolve()
    assert os.environ["ORIN_CONFIG_TEST_KEY"] == "from-config"
    monkeypatch.delenv("ORIN_CONFIG_TEST_KEY")


def test_current_directory_takes_precedence_over_stable_config(monkeypatch, tmp_path):
    config_home = tmp_path / "home" / "config"
    config_home.mkdir(parents=True)
    (config_home / ".env").write_text("ORIN_CONFIG_TEST_KEY=from-config\n")
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / ".env").write_text("ORIN_CONFIG_TEST_KEY=from-workdir\n")
    monkeypatch.chdir(workdir)
    monkeypatch.setenv("ORIN_CONFIG_DIR", str(config_home))
    monkeypatch.delenv("ORIN_ENV_FILE", raising=False)
    monkeypatch.delenv("ORIN_CONFIG_TEST_KEY", raising=False)

    assert config.load_environment() == (workdir / ".env").resolve()
    assert os.environ["ORIN_CONFIG_TEST_KEY"] == "from-workdir"
    monkeypatch.delenv("ORIN_CONFIG_TEST_KEY")


def test_explicit_env_file_wins_and_process_values_stay_authoritative(monkeypatch, tmp_path):
    explicit = tmp_path / "orin.env"
    explicit.write_text("ORIN_CONFIG_TEST_KEY=from-explicit\nORIN_CONFIG_TEST_KEEP=file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORIN_ENV_FILE", str(explicit))
    monkeypatch.setenv("ORIN_CONFIG_DIR", str(tmp_path / "missing"))
    monkeypatch.delenv("ORIN_CONFIG_TEST_KEY", raising=False)
    monkeypatch.setenv("ORIN_CONFIG_TEST_KEEP", "process")

    assert config.load_environment() == explicit.resolve()
    assert os.environ["ORIN_CONFIG_TEST_KEY"] == "from-explicit"
    assert os.environ["ORIN_CONFIG_TEST_KEEP"] == "process"
    monkeypatch.delenv("ORIN_CONFIG_TEST_KEY")


def test_missing_environment_file_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORIN_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setenv("ORIN_CONFIG_DIR", str(tmp_path / "absent-config"))
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path / "absent-project")

    assert config.load_environment() is None
