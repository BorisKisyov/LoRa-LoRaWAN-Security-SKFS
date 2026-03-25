# VisionByte LoRaWAN Security Lab

This repository is prepared so a professor can download it directly from GitHub and start the demo with one command.

## Default plug-and-play demo

The default stack does **not** require ChirpStack credentials or manual Python scripts.

It starts automatically:
- VisionByte API
- VisionByte web dashboard
- PostgreSQL / TimescaleDB
- pgAdmin
- Mosquitto MQTT broker
- demo history seeding
- live telemetry publishing every 30 seconds
- automatic MIC / replay / ACK-failure injection events

## Start

```bash
docker compose up --build
```

Then open:
- Dashboard: `http://localhost:8081`
- API health: `http://localhost:8000/health`
- Security summary: `http://localhost:8000/security/summary`
- Raw LoRa AES/MIC/replay demo JSON: `http://localhost:8000/security/raw-demo`
- pgAdmin: `http://localhost:5050`

Default pgAdmin login:
- email: `admin@visionbyte.com`
- password: `admin`

## Fresh GitHub download

You can run the default demo directly after downloading the repository ZIP from GitHub.
No `.env` file is required for the default demo because Docker Compose provides defaults.

Optional: if you want to customize values, copy `.env.example` to `.env`.

## Optional full ChirpStack stack

If you also want the reference ChirpStack services, start them with:

```bash
docker compose --profile full-lorawan up --build
```

This additionally starts:
- ChirpStack
- ChirpStack REST API
- ChirpStack Gateway Bridge
- ChirpStack Postgres
- ChirpStack Redis
- ChirpStack Simulator container

Important for the optional full stack:
- the default demo works without ChirpStack bootstrap;
- the optional simulator still needs valid `CHIRPSTACK_API_KEY` and `CHIRPSTACK_TENANT_ID` in `.env`.

## What the automatic demo does

### Normal telemetry
- seeds demo history into the database first
- publishes join events for 5 demo devices
- publishes uplink data every 30 seconds
- stores measurements for the dashboard
- publishes periodic status and ACK events

### Security / attack simulation
Every few publish cycles it automatically injects:
- duplicate uplink event for replay detection
- `UPLINK_MIC` error log for MIC failure demonstration
- `FCNT_REPLAY` warning log for replay demonstration
- failed ACK event for downlink-failure demonstration

These appear in:
- `http://localhost:8081/security`
- `http://localhost:8000/security/events?limit=50`
- `http://localhost:8000/security/summary`

## Stop

```bash
docker compose down
```

Full reset:

```bash
docker compose down -v
```

## Logs

```bash
docker compose logs -f vb-api
docker compose logs -f demo-publisher
docker compose logs -f vb-web
```

## Notes for the report

This package demonstrates two security layers:
- event-driven LoRaWAN-style security monitoring in the VisionByte stack
- raw LoRa AES + MIC + replay logic at `GET /security/raw-demo`

It is a controlled lab simulation, not SDR/RF-layer testing.
