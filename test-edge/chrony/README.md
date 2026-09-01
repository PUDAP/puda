# Edge Chrony client

Point this **edge host** at the site NTP server (`infra/chrony`). The edge
process does not talk NTP; it uses the host clock.

Do not run these scripts on the NATS/NTP machine. That host already runs the
`chrony` container, which sets its clock.

Pass the server address when you run the script. Use `HOST_IP` from
`infra/chrony/.env` (Tailscale IP, LAN IP, or Tailscale MagicDNS). Example: `100.118.119.115`, `bears`.

## Linux

```bash
sudo ./setup.sh 100.118.119.115
```

## Windows

Elevated PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -NtpServer 100.118.119.115
```

## Verify

The setup script prints status after about 2 seconds. Chrony often has not
selected a source yet (`Leap status : Not synchronised`, source state `?`).
Wait a minute or two, then check again.

Linux:

```bash
chronyc tracking
chronyc sources -v
```

Locked when:

- `Leap status : Normal`
- `*` next to the NTP server (not `?`)
- `Reach` climbing toward `377` (`1` → `3` → `7` → `17` → …)

`^?` with a non-zero Reach and a Last sample means packets arrived; wait for
more polls. `Reach 0` means replies are not getting back.

Windows:

```powershell
w32tm /query /status
w32tm /query /peers
```

Locked when Source is the NTP server and the Last Successful Sync Time is
recent, not `1/1/1901` or empty.
