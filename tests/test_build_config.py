import importlib.util
import json
from pathlib import Path

import pytest


def build_tool():
    path = Path(__file__).resolve().parents[1] / "tools" / "prepare_cloud_config.py"
    spec = importlib.util.spec_from_file_location("prepare_config_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_build_configuration_contains_only_expected_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_URL", "https://example.com")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_public_example")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "must-never-be-copied")
    destination = tmp_path / "cloud.json"
    build_tool().prepare(destination)
    value = json.loads(destination.read_text())
    assert value == dict(
        supabase_url="https://example.com", publishable_key="sb_publishable_public_example"
    )
    assert "must-never-be-copied" not in destination.read_text()


def test_privileged_build_key_is_rejected_before_output(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_URL", "https://example.com")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_secret_rejected")
    destination = tmp_path / "cloud.json"
    with pytest.raises(ValueError):
        build_tool().prepare(destination)
    assert not destination.exists()


def test_explicit_local_build_clears_stale_cloud_config(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_URL", "https://example.com")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_public_example")
    destination = tmp_path / "cloud.json"
    build_tool().prepare(destination)
    build_tool().prepare(destination, local=True)
    assert json.loads(destination.read_text()) == dict(supabase_url="", publishable_key="")
