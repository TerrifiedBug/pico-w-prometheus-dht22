import os
import sys
import json
from pathlib import Path
import importlib

# Add firmware directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
import device_config


def reload_module():
    return importlib.reload(device_config)


def test_load_device_config_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reload_module()
    config = device_config.load_device_config()
    assert config == device_config.DEFAULT_CONFIG


def test_load_device_config_partial(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    partial = {"device": {"location": "lab"}}
    (tmp_path / "device_config.json").write_text(json.dumps(partial))
    reload_module()
    config = device_config.load_device_config()
    assert config["device"]["location"] == "lab"
    assert config["device"]["name"] == device_config.DEFAULT_CONFIG["device"]["name"]
    assert "ota" in config and "last_updated" in config


def test_load_device_config_corrupted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "device_config.json").write_text("{bad json")
    reload_module()
    config = device_config.load_device_config()
    assert config == device_config.DEFAULT_CONFIG
