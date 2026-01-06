# -*- coding: utf-8 -*-
"""
Created on Wed Nov 19 15:29:02 2025

@author: mater
"""


# %%
import serial.tools.list_ports
ports = serial.tools.list_ports.comports()

for port, desc, hwid in sorted(ports):
    print("{}: {} [{}]".format(port, desc, hwid))

# %% Open connection
import serial
import time

qubot = serial.Serial("/dev/ttyACM1", 9600, dsrdtr=True)
qubot.flush()

time.sleep(1)

# %% Home all axes

# Home sequence: Z, A, XY
qubot.write(bytes("G28\r", "utf-8"))
time.sleep(2)
print(qubot.read_all())
qubot.flush()

# %% Home one axis

# Home Z axis
qubot.write(bytes("G28 Z\r", "utf-8"))
print(qubot.readline())
qubot.flush()

# %% Query machine information

qubot.write(bytes("M115\r", "utf-8"))
print(qubot.readline())
qubot.flush()

# %% Query current position

qubot.write(bytes("M114\r", "utf-8"))
print(qubot.readline())
qubot.flush()

# %% Go to absolute position

# Set absolute coordinates G90
qubot.write(bytes("G90\r", "utf-8"))

# G1: Move at a certain speed
# XYZA: Which axis to move
# F: Feed speed - between 1000 - 3000
qubot.write(bytes("G1 Z-100 F1000\r", "utf-8"))
print(qubot.readline())
qubot.flush()

# %% Go to relative position

# Set relative coordinates G91
qubot.write(bytes("G91\r", "utf-8"))

# G1: Move at a certain speed
# XYZA: Which axis to move
# F: Feed speed - between 1000 - 3000
qubot.write(bytes("G1 Y-10 F3000\r", "utf-8"))
print(qubot.readline())
qubot.flush()

# %%
pip = serial.Serial("/dev/ttyUSB0", 9600)

# Initialize pipette
pip.write(bytes("\x011RZº\r", "utf-8"))

# %% Pipette eject tip precaution

pip.write(bytes("\x011RE30º\r", "utf-8"))

# %%
# Aspirate from vial 20 uL (40 steps)

pip.write(bytes("\x011RI40º\r", "utf-8"))

# %%
# Dispense 20 uL

pip.write(bytes("\x011RO40º\r", "utf-8"))
