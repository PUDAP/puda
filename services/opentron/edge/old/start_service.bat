@echo off
cd /d "C:\Users\T8Plus\Desktop\opentron_edge"
python opentron_edge.py --broker 192.168.50.131 --ca-cert "C:\Program Files\mosquitto\certs\ca.crt" --robot-ip 192.168.50.64
pause
