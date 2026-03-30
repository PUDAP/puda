"""Command-line interface for the balance driver.

Installed as the ``balance`` command when the package is installed.

Usage
-----
.. code-block:: text

    balance connect   COM8 [--baudrate 115200] [--mode arduino|commercial]
    balance disconnect COM8
    balance read      COM8 [--retries 3] [--continuous] [--interval 1.0]
    balance tare      COM8 [--wait 5.0] [--tare-command t]
    balance status    COM8
    balance calibrate COM8 [--set --slope 17450 --intercept 0]
                          [--enable | --disable]
                          [--get]
                          [--test --raw 1744626]
    balance monitor   COM8 [--duration 10]
    balance diagnose  COM8

Prerequisites
-------------
The Balance Bridge must be running on the host::

    pip install pyserial fastapi uvicorn
    python balance_bridge.py
"""

from __future__ import annotations

import argparse
import sys
import time

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _ok(msg: str) -> None:
    print(f"OK   {msg}")


def _err(msg: str) -> None:
    print(f"ERR  {msg}", file=sys.stderr)


def _info(label: str, value: object) -> None:
    print(f"     {label:<30} {value}")


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------


def _cmd_connect(args: argparse.Namespace) -> int:
    from balance_driver.controllers.reading import connect_balance
    from balance_driver.core.http_client import BalanceBridgeClient

    client = BalanceBridgeClient(host=args.bridge_host, port=args.bridge_port)
    if not client.is_connected():
        _err(f"Balance Bridge not reachable at {client.base_url}")
        _err("Start it with: python balance_bridge.py")
        return 1
    try:
        result = connect_balance(
            client,
            port=args.port,
            baudrate=args.baudrate,
            mode=args.mode,
        )
        status = result.get("status", "unknown")
        if status == "already_connected":
            _ok(f"Already connected to {args.port} ({result.get('baudrate')} baud)")
        else:
            _ok(
                f"Connected to {args.port} at {result.get('baudrate')} baud "
                f"[{result.get('mode', args.mode)} mode]"
            )
        cal = result.get("calibration", {})
        if cal:
            _info("calibration slope", cal.get("slope"))
            _info("calibration enabled", cal.get("enabled"))
        return 0
    except RuntimeError as exc:
        _err(str(exc))
        return 1


def _cmd_disconnect(args: argparse.Namespace) -> int:
    from balance_driver.controllers.reading import disconnect_balance
    from balance_driver.core.http_client import BalanceBridgeClient

    client = BalanceBridgeClient(host=args.bridge_host, port=args.bridge_port)
    try:
        result = disconnect_balance(client, port=args.port)
        _ok(result.get("message", f"Disconnected from {args.port}"))
        return 0
    except RuntimeError as exc:
        _err(str(exc))
        return 1


def _cmd_read(args: argparse.Namespace) -> int:
    from balance_driver.controllers.reading import get_latest_reading
    from balance_driver.core.http_client import BalanceBridgeClient

    client = BalanceBridgeClient(host=args.bridge_host, port=args.bridge_port)

    def _single_read() -> bool:
        for attempt in range(args.retries):
            try:
                data = get_latest_reading(client, port=args.port)
                if data.get("status") == "success" and data.get("mass_g") is not None:
                    mass_g = data["mass_g"]
                    mass_mg = data.get("mass_mg", mass_g * 1000)
                    age = data.get("age_seconds", 0)
                    fresh = data.get("fresh", True)
                    calibrated = data.get("calibrated", False)
                    print(
                        f"  {mass_g:>14.6f} g    {mass_mg:>14.4f} mg"
                        f"    age={age:.1f}s  fresh={str(fresh):<5}  calibrated={calibrated}"
                    )
                    return True
                else:
                    msg = data.get("message", "no data")
                    if attempt < args.retries - 1:
                        print(f"     waiting... ({msg})", end="\r")
                        time.sleep(1.0)
            except RuntimeError as exc:
                _err(str(exc))
                return False
        print(f"     no reading after {args.retries} attempt(s)")
        return False

    if args.continuous:
        print(f"Streaming from {args.port} — Ctrl+C to stop\n")
        print(f"  {'mass (g)':>14}    {'mass (mg)':>14}    age    fresh  calibrated")
        print("  " + "-" * 65)
        try:
            while True:
                _single_read()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
        return 0
    else:
        print(f"Reading from {args.port}...")
        ok = _single_read()
        if not ok:
            _err("No reading received. Try:")
            _err(f"  balance connect {args.port}")
            _err(f"  balance status  {args.port}")
            _err(f"  balance diagnose {args.port}")
            return 1
        return 0


def _cmd_tare(args: argparse.Namespace) -> int:
    from balance_driver.controllers.reading import get_latest_reading, tare_balance
    from balance_driver.core.http_client import BalanceBridgeClient

    client = BalanceBridgeClient(host=args.bridge_host, port=args.bridge_port)
    try:
        # Before
        data = get_latest_reading(client, port=args.port)
        before = data.get("mass_g")
        if before is not None:
            _info("before tare", f"{before:.6f} g")

        print(f"     Taring {args.port} (wait={args.wait}s)...")
        tare_balance(
            client,
            port=args.port,
            wait=args.wait,
            tare_command=args.tare_command,
        )

        # After
        data = get_latest_reading(client, port=args.port)
        after = data.get("mass_g")
        if after is not None:
            _info("after tare", f"{after:.6f} g")

        _ok(f"Tare complete on {args.port}")
        return 0
    except RuntimeError as exc:
        _err(str(exc))
        return 1


def _cmd_status(args: argparse.Namespace) -> int:
    from balance_driver.controllers.reading import get_balance_status
    from balance_driver.core.http_client import BalanceBridgeClient

    client = BalanceBridgeClient(host=args.bridge_host, port=args.bridge_port)
    try:
        s = get_balance_status(client, port=args.port)
        connected = s.get("connected", False)
        tag = "OK  " if connected else "DISC"
        print(f"[{tag}] {args.port}")
        _info("connected",              s.get("connected"))
        _info("background reader active", s.get("background_reader_active"))
        _info("has data",               s.get("has_data"))
        if s.get("baudrate"):
            _info("baudrate",           s.get("baudrate"))
        if s.get("latest_mass_g") is not None:
            _info("latest mass (g)",    f"{s['latest_mass_g']:.6f}")
        if s.get("data_age_seconds") is not None:
            _info("data age (s)",       s.get("data_age_seconds"))
        return 0 if connected else 1
    except RuntimeError as exc:
        _err(str(exc))
        return 1


def _cmd_calibrate(args: argparse.Namespace) -> int:
    import balance_driver.controllers.calibration as cal_ctrl
    from balance_driver.core.http_client import BalanceBridgeClient

    client = BalanceBridgeClient(host=args.bridge_host, port=args.bridge_port)

    try:
        # --get
        if args.get:
            cal = cal_ctrl.get_calibration(client, port=args.port)
            _ok(f"Calibration for {args.port}")
            _info("slope (counts/g)",   cal.get("slope"))
            _info("intercept",          cal.get("intercept"))
            _info("enabled",            cal.get("enabled") if "enabled" in cal else cal.get("calibrated"))
            _info("source",             cal.get("source"))
            _info("formula",            cal.get("formula"))
            return 0

        # --test --raw <value>
        if args.test:
            if args.raw is None:
                _err("--test requires --raw <adc_value>")
                return 1
            result = cal_ctrl.test_calibration(client, port=args.port, raw_value=args.raw)
            _ok(f"Calibration test for {args.port}")
            _info("raw ADC value",  result.get("raw_value"))
            _info("mass (g)",       f"{result['mass_g']:.6f}" if result.get("mass_g") is not None else "N/A")
            _info("mass (mg)",      f"{result.get('mass_mg', 0):.4f}")
            cal = result.get("calibration", {})
            _info("slope used",     cal.get("slope"))
            _info("intercept used", cal.get("intercept"))
            return 0

        # --enable / --disable
        if args.enable:
            result = cal_ctrl.enable_calibration(client, port=args.port, enabled=True)
            _ok(f"Calibration ENABLED on {args.port}")
            return 0
        if args.disable:
            result = cal_ctrl.enable_calibration(client, port=args.port, enabled=False)
            _ok(f"Calibration DISABLED on {args.port} (raw ADC mode)")
            return 0

        # --set --slope <value> [--intercept <value>]
        if args.set:
            if args.slope is None:
                _err("--set requires --slope <value>")
                return 1
            result = cal_ctrl.set_calibration(
                client,
                port=args.port,
                slope=args.slope,
                intercept=args.intercept,
            )
            _ok(f"Calibration set on {args.port}")
            _info("slope (counts/g)", result.get("slope"))
            _info("intercept",        result.get("intercept"))
            _info("enabled",          result.get("enabled"))
            return 0

        # Default: load bundled 100g CSV calibration
        slope, intercept = cal_ctrl.get_bundled_calibration()
        _info("bundled CSV slope",      f"{slope:.4f} counts/g")
        _info("bundled CSV intercept",  f"{intercept:.4f}")
        result = cal_ctrl.load_default_calibration(client, port=args.port)
        _ok(f"Default calibration loaded and enabled on {args.port}")
        _info("slope (counts/g)", result.get("slope"))
        _info("intercept",        result.get("intercept"))
        _info("enabled",          result.get("enabled"))
        return 0

    except RuntimeError as exc:
        _err(str(exc))
        return 1


def _cmd_monitor(args: argparse.Namespace) -> int:
    from balance_driver.controllers.reading import monitor_balance
    from balance_driver.core.http_client import BalanceBridgeClient

    client = BalanceBridgeClient(host=args.bridge_host, port=args.bridge_port)
    print(f"Monitoring {args.port} for {args.duration}s at {args.baudrate} baud...")
    try:
        result = monitor_balance(
            client,
            port=args.port,
            duration=args.duration,
            baudrate=args.baudrate,
        )
        messages = result.get("data_received", [])
        for msg in messages:
            ts = msg.get("timestamp", 0)
            text = msg.get("text", "")
            readable = msg.get("readable", False)
            tag = "OK" if readable else "--"
            print(f"  [{ts:6.2f}s] [{tag}] {text!r}")
        print()
        _info("total messages",    result.get("total_messages"))
        _info("readable messages", result.get("readable_messages"))
        _info("diagnosis",         result.get("diagnosis"))
        return 0
    except RuntimeError as exc:
        _err(str(exc))
        return 1


def _cmd_diagnose(args: argparse.Namespace) -> int:
    from balance_driver.controllers.reading import diagnose_balance
    from balance_driver.core.http_client import BalanceBridgeClient

    client = BalanceBridgeClient(host=args.bridge_host, port=args.bridge_port)
    print(f"Diagnosing {args.port} — testing baud rates (takes ~15 s)...")
    try:
        result = diagnose_balance(client, port=args.port)
        print()
        for r in result.get("results", []):
            if r.get("error"):
                print(f"  {r['baudrate']:>7} baud  ERROR: {r['error']}")
                continue
            tag = " <-- BEST" if r.get("best") else (" <-- OK" if r.get("recommended") else "")
            mass_str = f"  mass={r['mass_found']:.4f}g" if r.get("mass_found") is not None else ""
            print(
                f"  {r['baudrate']:>7} baud"
                f"  readable={r.get('readable_count', 0):>3}"
                f"{mass_str}{tag}"
            )
            for line in r.get("readable_lines", [])[:2]:
                print(f"           sample: {line!r}")
        print()
        _ok(result.get("summary", "Done"))
        best = result.get("best_baudrate")
        if best:
            print(f"\n  Recommended:")
            print(f"    balance connect {args.port} --baudrate {best}")
        return 0
    except RuntimeError as exc:
        _err(str(exc))
        return 1


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="balance",
        description="Balance driver CLI — control a mass balance via the Balance Bridge.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  balance connect   COM8
  balance connect   COM8 --baudrate 9600 --mode commercial
  balance read      COM8
  balance read      COM8 --continuous --interval 0.5
  balance tare      COM8 --wait 3.0
  balance status    COM8
  balance calibrate COM8
  balance calibrate COM8 --get
  balance calibrate COM8 --set --slope 17450.3 --intercept -446.6
  balance calibrate COM8 --test --raw 1744626
  balance calibrate COM8 --enable
  balance calibrate COM8 --disable
  balance monitor   COM8 --duration 5
  balance diagnose  COM8
  balance disconnect COM8
""",
    )

    # Global options
    parser.add_argument(
        "--bridge-host",
        default="localhost",
        metavar="HOST",
        help="Balance Bridge hostname (default: localhost)",
    )
    parser.add_argument(
        "--bridge-port",
        type=int,
        default=9000,
        metavar="PORT",
        help="Balance Bridge HTTP port (default: 9000)",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # ---- connect ----
    p = sub.add_parser("connect", help="Connect to a balance on a COM port")
    p.add_argument("port", help="COM port, e.g. COM8")
    p.add_argument("--baudrate", type=int, default=115200, help="Baud rate (default: 115200)")
    p.add_argument(
        "--mode",
        default="arduino",
        choices=["arduino", "commercial"],
        help="Connection mode (default: arduino)",
    )

    # ---- disconnect ----
    p = sub.add_parser("disconnect", help="Disconnect from a balance")
    p.add_argument("port", help="COM port")

    # ---- read ----
    p = sub.add_parser("read", help="Read mass from a connected balance")
    p.add_argument("port", help="COM port")
    p.add_argument("--retries", type=int, default=3, help="Read retries (default: 3)")
    p.add_argument("--continuous", action="store_true", help="Stream readings until Ctrl+C")
    p.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds between readings in continuous mode (default: 1.0)",
    )

    # ---- tare ----
    p = sub.add_parser("tare", help="Tare (zero) the balance")
    p.add_argument("port", help="COM port")
    p.add_argument("--wait", type=float, default=5.0, help="Stabilisation wait in seconds (default: 5.0)")
    p.add_argument("--tare-command", default="t", help="Arduino tare character (default: t)")

    # ---- status ----
    p = sub.add_parser("status", help="Show connection status and latest reading")
    p.add_argument("port", help="COM port")

    # ---- calibrate ----
    p = sub.add_parser(
        "calibrate",
        help="Manage calibration (default: load bundled 100g CSV)",
    )
    p.add_argument("port", help="COM port")
    p.add_argument("--get", action="store_true", help="Print current calibration")
    p.add_argument("--set", action="store_true", help="Set manual calibration (requires --slope)")
    p.add_argument("--slope", type=float, help="ADC counts per gram")
    p.add_argument("--intercept", type=float, default=0.0, help="ADC offset at zero grams (default: 0.0)")
    p.add_argument("--enable", action="store_true", help="Enable calibration")
    p.add_argument("--disable", action="store_true", help="Disable calibration (raw ADC mode)")
    p.add_argument("--test", action="store_true", help="Test calibration against a raw ADC value")
    p.add_argument("--raw", type=float, metavar="ADC", help="Raw ADC value to convert (used with --test)")

    # ---- monitor ----
    p = sub.add_parser("monitor", help="Capture raw serial data for debugging")
    p.add_argument("port", help="COM port")
    p.add_argument("--duration", type=int, default=10, help="Monitoring duration in seconds (default: 10)")
    p.add_argument("--baudrate", type=int, default=9600, help="Baud rate for temporary connection (default: 9600)")

    # ---- diagnose ----
    p = sub.add_parser("diagnose", help="Find correct baud rate by testing all common values")
    p.add_argument("port", help="COM port")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "connect":    _cmd_connect,
        "disconnect": _cmd_disconnect,
        "read":       _cmd_read,
        "tare":       _cmd_tare,
        "status":     _cmd_status,
        "calibrate":  _cmd_calibrate,
        "monitor":    _cmd_monitor,
        "diagnose":   _cmd_diagnose,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(handler(args))


if __name__ == "__main__":
    main()
