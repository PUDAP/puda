import logging
import asyncio
from puda_drivers.transfer.liquid.sartorius import SartoriusController
from puda_drivers.core.logging import setup_logging

# Optional: finding ports
from puda_drivers.core.serialcontroller import list_serial_ports
print(list_serial_ports())

# --- LOGGING CONFIGURATION ---
# All loggers in imported modules (SerialController, SartoriusController) will inherit this setup.
setup_logging(
    enable_file_logging=False,
    log_level=logging.DEBUG,  # Use logging.DEBUG to see all (DEBUG, INFO, WARNING, ERROR, CRITICAL) logs
)

# OPTIONAL: If you only want specific loggers at specific level, you can specifically set it here
# logging.getLogger('puda_drivers.transfer.liquid.sartorius').setLevel(logging.INFO)


# --- CONFIGURATION ---
SARTORIUS_PORT = "/dev/ttyUSB0"

TRANSFER_VOLUME = 20  # uL
TIP_LENGTH = 70  # mm


# if there are 2 consecutive pipette commands, have to manually call time.sleep(5) if not the second will not run
def test_pipette_operations():
    """
    Tests the initialization and core liquid handling functions
    of the SartoriusController.
    """
    print("--- 🔬 Starting Pipette Controller Test ---")
    pipette = SartoriusController(port_name=SARTORIUS_PORT)

    try:
        # 1. Initialize and Connect
        print("[STEP 1] Connecting to pipette...")
        # SartoriusController connects automatically in __init__, no need to call connect()

        # Always start with initializing
        pipette.initialize()

        pipette.get_status()
        pipette.get_liquid_level()

        # 2. Set and get inward and outward speeds
        print("[STEP 2] Setting and getting inward and outward speeds...")
        pipette.set_inward_speed(3)
        pipette.get_inward_speed()

        pipette.set_outward_speed(3)
        pipette.get_outward_speed()
        pipette.run_to_position(100)
        asyncio.run(pipette.get_position())

        # 3. Eject Tip (if any)
        print("[STEP 3] Ejecting Tip (if any)...")
        pipette.eject_tip(return_position=30)
        print(f"[STEP 3] Aspirate {TRANSFER_VOLUME} uL...")
        pipette.aspirate(amount=TRANSFER_VOLUME)

        # 4. Dispense
        print(f"[STEP 4] Dispensing {TRANSFER_VOLUME} uL...")
        pipette.dispense(amount=TRANSFER_VOLUME)

        # # 5. Eject Tip
        # print("\n[STEP 5] Ejecting Tip...")
        # pipette.eject()
        # if not pipette.is_tip_on():
        #     print("✅ Tip check: Tip is ejected.")
        # else:
        #     raise Exception("Tip ejection failed.")
        #
        # print("\n--- 🎉 All Pipette operations passed! ---")

    except Exception as e:
        print(f"\n--- ❌ TEST FAILURE: {e} ---")

    finally:
        # 6. Disconnect
        if pipette and pipette.is_connected:
            print("\n[FINAL] Disconnecting...")
            pipette.disconnect()
        print("--- 🧪 Pipette Controller Test Complete ---")


if __name__ == "__main__":
    test_pipette_operations()
