"""Guard the single-source, locked uv container build."""

from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_server_pins_verified_latest_stable_image():
    compose = (ROOT.parent / "server/compose.yml").read_text()
    assert "clickhouse/clickhouse-server:26.10.2.103@sha256:b2bfa4d8399ee9973868cc5c1754cb506a6f4b86fbddc41010cc090beb55c85e" in compose


def test_protocol_1_0_schema_is_fresh_split_tables_only():
    initdb = ROOT.parent / "server/initdb"
    assert sorted(p.name for p in initdb.glob("*.sql")) == ["002-split-events.sql"]
    text = (initdb / "002-split-events.sql").read_text()
    assert "puda.command_logs" in text and "puda.telemetry" in text
    assert "data String" in text and "protocol_version LowCardinality(String)" in text
    assert "cmd_version" not in text and "puda.events" not in text
    assert "DROP" not in text.upper()
    assert not (ROOT / "backfill.py").exists()


def test_pins_and_docs_target_edge_protocol_1_0():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert {"puda==0.1.0rc1", "nats-py==2.17.0"} <= set(project["dependencies"])
    for doc in (ROOT / "README.md", ROOT.parent / "README.md"):
        assert "Edge Protocol 1.0" in doc.read_text()
    for path in ROOT.glob("*.py"):
        text = path.read_text()
        assert "cmd_version" not in text and "header.version" not in text, path
    for path in [*ROOT.glob("*.md"), *ROOT.parent.glob("*/*.md")]:
        assert "backfill.py" not in path.read_text(), path


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
    versions = {package["name"]: package.get("version") for package in lock["package"]}
    assert versions["puda"] == "0.1.0rc1" and versions["nats-py"] == "2.17.0"
