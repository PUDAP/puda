"""balance-driver — Python driver for mass balances via the Balance Bridge service.

The Balance Bridge (``balance_bridge.py``) must be running on the host machine
before using this package.  It handles the physical serial connection and
exposes a REST API on ``http://localhost:9000`` that this driver consumes.

Quick start::

    from balance_driver.machines import Balance
    import time

    with Balance(port="COM8", baudrate=115200, mode="arduino") as bal:
        time.sleep(2)   # wait for Arduino reset + first reading

        mass = bal.get_mass(retries=3, retry_delay=1.0)
        if mass is not None:
            print(f"{mass:.6f} g  ({mass * 1000:.4f} mg)")

Calibration::

    with Balance(port="COM8") as bal:
        bal.load_default_calibration()      # 100 g load cell defaults
        bal.tare(wait=5.0)
        print(bal.get_mass())
"""

from balance_driver.core.http_client import BalanceBridgeClient
from balance_driver.core.logging import setup_logging
from balance_driver.machines.balance import Balance

__version__ = "0.1.0"

__all__ = [
    "Balance",
    "BalanceBridgeClient",
    "setup_logging",
    "__version__",
]
