"""Offline legacy export conversion. No environment loading or network access."""
import argparse
import json
from pathlib import Path

from storage import to_row


def convert(rows):
    """Keep every exported row, including duplicates and original receipt times."""
    for source in rows:
        row = to_row(source["subject"], source["raw_json"].encode("utf-8"))
        for key in ("event_ns", "received_ns"):
            row[key] = int(source[key])
        row["event_id"] = source["event_id"]
        if row["msg_type"] in ("command", "response"):
            for key in ("machine_id", "run_id", "username", "user_id", "cmd_name", "cmd_version", "step_number", "status"):
                row[key] = source[key]
            table = "command_logs"
        else:
            table = "telemetry"
        yield table, row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("output", type=Path, help="new, private output directory")
    args = parser.parse_args()
    args.output.mkdir(mode=0o700)  # Refuse accidental reuse of an existing batch.
    counts = {"command_logs": 0, "telemetry": 0}
    try:
        with args.export.open(encoding="utf-8") as source, \
                (args.output / "command_logs.jsonl").open("x", encoding="utf-8") as commands, \
                (args.output / "telemetry.jsonl").open("x", encoding="utf-8") as telemetry:
            outputs = {"command_logs": commands, "telemetry": telemetry}
            for table, row in convert(json.loads(line) for line in source):
                outputs[table].write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                counts[table] += 1
    except Exception:
        # Do not expose row contents or mistake a partial conversion for success.
        for name in counts:
            (args.output / (name + ".jsonl")).unlink(missing_ok=True)
        raise SystemExit("Conversion failed; no insertable output retained") from None
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
