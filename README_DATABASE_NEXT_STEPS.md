# SKFS database MVP v1

This stack now includes a real MVP data model for:
- organizations
- sites
- rooms
- gateways
- devices
- measurements (Timescale hypertable)
- device_last_state
- alerts

## Main API endpoints
- `POST /ingest`
- `GET /latest`
- `GET /organizations`
- `GET /sites`
- `GET /rooms`
- `GET /devices`
- `GET /devices/{device_eui}/latest`
- `GET /devices/{device_eui}/history`
- `GET /alerts`

## Example ingest payload
```json
{
  "device_eui": "VB-001",
  "device_name": "Classroom Sensor 1",
  "ts": "2026-03-14T10:30:00Z",
  "co2_ppm": 1180,
  "temp_c": 23.4,
  "rh": 41.2,
  "battery_v": 3.58,
  "rssi": -92,
  "snr": 5.5,
  "firmware_version": "0.1.0",
  "gateway_eui": "GW-001",
  "gateway_name": "School Gateway",
  "organization_name": "SKFS Demo",
  "site_name": "TU Sofia Building A",
  "room_name": "Room 214",
  "battery_type": "2xAA",
  "target_co2_ppm": 1000
}
```

## Run
```bash
docker compose up --build
```

## Open
- API docs: `http://localhost:8000/docs`
- Website: `http://localhost:8081`
- pgAdmin: `http://localhost:5050`

## Notes
The API initializes the schema at startup for fast local development. Later, this should move to real migrations.
