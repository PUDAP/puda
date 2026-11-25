"""Guard the single-source, locked uv container build."""

from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_server_pins_verified_latest_stable_image():
    compose = (ROOT.parent / "server/compose.yml").read_text()
    assert "clickhouse/clickhouse-server:26.10.2.103@sha256:b2bfa4d8399ee9973868cc5c1754cb506a6f4b86fbddc41010cc090beb55c85e" in compose


def test_additive_split_schema_keeps_legacy_initialization():
    schema = ROOT.parent / "server/initdb/002-split-events.sql"
    assert schema.is_file(), "Add the two-table schema without replacing legacy events"
    text = schema.read_text()
    assert "puda.command_logs" in text and "puda.telemetry" in text
    assert "data String" in text
    assert "DROP" not in text.upper()
    assert "CREATE TABLE IF NOT EXISTS puda.events" in (schema.parent / "001-events.sql").read_text()


def test_container_uses_locked_uv_project():
    assert (ROOT / "uv.lock").is_file(), "Generate the uv lockfile"
    assert not (ROOT / "requirements.txt").exists(), "Use pyproject.toml only"
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "uv sync --locked --no-dev --no-install-project" in dockerfile
    assert "COPY pyproject.toml uv.lock" in dockerfile
    assert "pip install" not in dockerfile
    assert 'USER 10001:10001' in dockerfile
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    names = {package["name"] for package in lock["package"]}
    assert {"puda", "nats-py"} <= names
