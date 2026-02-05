import os
from dotenv import load_dotenv
import easy_biologic as ebl
import easy_biologic.base_programs as blp
from puda_drivers.machines import Biologic

# Load environment variables from .env file
load_dotenv()

# metadata
metadata = {
    "protocolName": "My BioLogic Protocol",
    "author": "Researcher",
    "description": "Electrochemical protocol for material characterization"
}

# Connect to the BioLogic device
device_ip = os.getenv("BIOLOGIC_IP")
if not device_ip:
    raise ValueError("BIOLOGIC_IP environment variable is not set. Please set it in your .env file or environment.")

# Initialize BiologicMachine
machine = Biologic(device_ip)

# --- Protocol Sequence ---

# Technique 1: CV
params_cv_0 = {
    'start': 0.0,
    'end': 0.5,
    'rate': 0.1,
    'step': 0.1,
    'E2': 0.0,
    'Ef': 0.0,
    'average': False,
} # End of params_cv_0

# Run CV test using BiologicMachine
data = machine.CV(
    params=params_cv_0,
    channels=[0]
)

print(data)

# --- End of Protocol Sequence ---
# Disconnect from the device
print('Protocol finished and device disconnected.')