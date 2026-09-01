# Chrony NTP server

Site NTP server for PUDA hosts. Run this on the same computer as NATS.

The container syncs to public (or campus) NTP, disciplines this host's clock,
and serves NTP on UDP 123 so edge PCs can lock to the same time.

Edge Docker containers do not run Chrony. They inherit the edge host clock.

```text
public/campus NTP  →  chrony container on NATS host  →  chronyd/timesyncd on each edge host
```

## Host conflict

Only one process can bind UDP 123 or set the system clock. On this machine,
stop any host NTP daemon before starting the container:

```bash
sudo timedatectl set-ntp false
sudo systemctl disable --now chrony chronyd systemd-timesyncd 2>/dev/null || true
```

## Start

```bash
cp .env.example .env
# Set HOST_IP to this machine's Tailscale/LAN address (for edge client config).
docker compose up -d --build
```

The container uses host networking so NTP is served on UDP 123 of every
interface (LAN and Tailscale). Docker bridge port publish rewrites the
reply source port; chronyd clients then drop the packet.

Open UDP 123 on the host firewall if one is enabled:

```bash
sudo ufw allow 123/udp
```

## Verify

```bash
docker compose ps
docker exec chrony chronyc tracking
docker exec chrony chronyc sources -v
```

`Leap status : Normal` means this server is locked to upstream. From another
host (or this one):

```bash
# Replace with HOST_IP from .env
chronyd -Q "server 100.118.119.115 iburst"
```

## Edge hosts

On each edge **host** (not in the edge container), point Chrony at `HOST_IP`.
See `test-edge/chrony/README.md`. Manual Debian/Ubuntu steps:

```bash
sudo timedatectl set-ntp false
sudo apt update && sudo apt install -y chrony
```

`/etc/chrony/chrony.conf` on the edge — comment out any `pool` lines:

```conf
server 100.118.119.115 iburst
makestep 1.0 3
rtcsync
```

```bash
sudo systemctl enable --now chrony
sudo systemctl restart chrony
chronyc tracking
chronyc sources -v
```

The edge should show `100.118.119.115` as the selected source.

## Config

Edit [`chrony.conf`](./chrony.conf) and recreate the container:

```bash
docker compose up -d --force-recreate
```

To use campus NTP, replace the `pool ntp.ubuntu.com` line with:

```conf
server ntp.example.edu iburst
```
