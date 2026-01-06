# NATS Cluster setup

1. Copy the template: cp .env.example .env

2. Edit .env and fill in the real values specific to that machine.

3. `docker compose up -d`


# todo add setup script to compose file

```
services:
  nats:
    image: nats:latest
    ports:
      - "4222:4222"
      - "8222:8222"
  
  # This "configurator" container runs the script and dies
  nats-setup:
    image: natsio/nats-box
    depends_on:
      - nats
    volumes:
      - ./setup_streams.sh:/setup_streams.sh
    environment:
      - NATS_URL=nats://nats:4222
    command: ["sh", "/setup_streams.sh"]
```
