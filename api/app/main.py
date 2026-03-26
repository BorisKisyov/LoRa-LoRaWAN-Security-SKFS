import base64
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import paho.mqtt.client as mqtt
import psycopg
from fastapi import FastAPI, HTTPException, Query
from psycopg.rows import dict_row
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.raw_lora_secure_demo import run_demo

app = FastAPI(title="SKFS LoRaWAN Security API", version="1.0.0")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@vb-db:5432/visionbyte",
)
CHIRPSTACK_MQTT_ENABLED = os.environ.get("CHIRPSTACK_MQTT_ENABLED", "false").lower() == "true"
CHIRPSTACK_MQTT_HOST = os.environ.get("CHIRPSTACK_MQTT_HOST", "chirpstack-mosquitto")
CHIRPSTACK_MQTT_PORT = int(os.environ.get("CHIRPSTACK_MQTT_PORT", "1883"))
CHIRPSTACK_MQTT_TOPIC = os.environ.get("CHIRPSTACK_MQTT_TOPIC", "application/+/device/+/event/+")
DEFAULT_SITE_NAME = os.environ.get("DEFAULT_SITE_NAME", "ChirpStack Lab")

MQTT_THREAD_STARTED = False


class MeasurementIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    device_eui: str = Field(..., min_length=1)
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    co2_ppm: int = Field(..., ge=0)
    temp_c: Optional[float] = Field(default=None, validation_alias=AliasChoices("temp_c", "temperature_c"))
    rh: Optional[float] = Field(default=None, validation_alias=AliasChoices("rh", "humidity_rh"))
    battery_v: Optional[float] = None
    rssi: Optional[int] = Field(default=None, validation_alias=AliasChoices("rssi", "rssi_dbm"))
    snr: Optional[float] = Field(default=None, validation_alias=AliasChoices("snr", "snr_db"))
    firmware_version: Optional[str] = None
    gateway_eui: Optional[str] = None
    gateway_name: Optional[str] = None
    organization_name: str = "SKFS Demo"
    site_name: str = "Main Site"
    room_name: str = "Unassigned"
    device_name: Optional[str] = None
    battery_type: Optional[str] = None
    target_co2_ppm: Optional[int] = Field(default=1000, ge=400)

    @model_validator(mode="after")
    def normalize_timestamp(self):
        if self.ts.tzinfo is None:
            self.ts = self.ts.replace(tzinfo=timezone.utc)
        return self


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS organizations (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sites (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    address TEXT,
    timezone TEXT NOT NULL DEFAULT 'Europe/Sofia',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, name)
);

CREATE TABLE IF NOT EXISTS rooms (
    id BIGSERIAL PRIMARY KEY,
    site_id BIGINT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    floor TEXT,
    room_type TEXT,
    target_co2_ppm INTEGER NOT NULL DEFAULT 1000,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (site_id, name)
);

CREATE TABLE IF NOT EXISTS gateways (
    id BIGSERIAL PRIMARY KEY,
    gateway_eui TEXT NOT NULL UNIQUE,
    name TEXT,
    site_id BIGINT REFERENCES sites(id) ON DELETE SET NULL,
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS devices (
    id BIGSERIAL PRIMARY KEY,
    device_eui TEXT NOT NULL UNIQUE,
    name TEXT,
    organization_id BIGINT REFERENCES organizations(id) ON DELETE SET NULL,
    site_id BIGINT REFERENCES sites(id) ON DELETE SET NULL,
    room_id BIGINT REFERENCES rooms(id) ON DELETE SET NULL,
    gateway_id BIGINT REFERENCES gateways(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'provisioning',
    firmware_version TEXT,
    battery_type TEXT,
    install_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS measurements (
    time TIMESTAMPTZ NOT NULL,
    device_id BIGINT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    gateway_id BIGINT REFERENCES gateways(id) ON DELETE SET NULL,
    co2_ppm INTEGER NOT NULL,
    temp_c REAL,
    rh REAL,
    battery_v REAL,
    rssi INTEGER,
    snr REAL,
    PRIMARY KEY (time, device_id)
);

CREATE TABLE IF NOT EXISTS device_last_state (
    device_id BIGINT PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    gateway_id BIGINT REFERENCES gateways(id) ON DELETE SET NULL,
    last_measurement_at TIMESTAMPTZ NOT NULL,
    co2_ppm INTEGER NOT NULL,
    temp_c REAL,
    rh REAL,
    battery_v REAL,
    rssi INTEGER,
    snr REAL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alerts (
    id BIGSERIAL PRIMARY KEY,
    device_id BIGINT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    room_id BIGINT REFERENCES rooms(id) ON DELETE SET NULL,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    threshold_value REAL,
    measured_value REAL,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    cleared_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS security_events (
    id BIGSERIAL PRIMARY KEY,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source TEXT NOT NULL DEFAULT 'chirpstack',
    event_type TEXT NOT NULL,
    tenant_id TEXT,
    tenant_name TEXT,
    application_id TEXT,
    application_name TEXT,
    device_profile_id TEXT,
    device_profile_name TEXT,
    device_name TEXT,
    dev_eui TEXT,
    gateway_id TEXT,
    deduplication_id TEXT,
    code TEXT,
    description TEXT,
    event_level TEXT,
    failure_class TEXT,
    dev_addr TEXT,
    battery_level REAL,
    margin INTEGER,
    acknowledged BOOLEAN,
    f_cnt_down BIGINT,
    f_port INTEGER,
    dr INTEGER,
    rssi INTEGER,
    snr REAL,
    replay_suspected BOOLEAN NOT NULL DEFAULT FALSE,
    mic_status TEXT NOT NULL DEFAULT 'unknown',
    raw_event JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS device_security_state (
    dev_eui TEXT PRIMARY KEY,
    device_name TEXT,
    tenant_name TEXT,
    application_name TEXT,
    last_join_at TIMESTAMPTZ,
    last_up_at TIMESTAMPTZ,
    last_log_at TIMESTAMPTZ,
    last_status_at TIMESTAMPTZ,
    last_ack_at TIMESTAMPTZ,
    last_txack_at TIMESTAMPTZ,
    join_count INTEGER NOT NULL DEFAULT 0,
    up_count INTEGER NOT NULL DEFAULT 0,
    ack_count INTEGER NOT NULL DEFAULT 0,
    txack_count INTEGER NOT NULL DEFAULT 0,
    status_count INTEGER NOT NULL DEFAULT 0,
    log_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    mic_error_count INTEGER NOT NULL DEFAULT 0,
    replay_suspected_count INTEGER NOT NULL DEFAULT 0,
    last_battery_level REAL,
    last_margin INTEGER,
    last_rssi INTEGER,
    last_snr REAL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);


ALTER TABLE security_events ADD COLUMN IF NOT EXISTS event_level TEXT;
ALTER TABLE security_events ADD COLUMN IF NOT EXISTS failure_class TEXT;
ALTER TABLE security_events ADD COLUMN IF NOT EXISTS dev_addr TEXT;
ALTER TABLE security_events ADD COLUMN IF NOT EXISTS battery_level REAL;
ALTER TABLE security_events ADD COLUMN IF NOT EXISTS margin INTEGER;

ALTER TABLE device_security_state ADD COLUMN IF NOT EXISTS last_status_at TIMESTAMPTZ;
ALTER TABLE device_security_state ADD COLUMN IF NOT EXISTS last_ack_at TIMESTAMPTZ;
ALTER TABLE device_security_state ADD COLUMN IF NOT EXISTS last_txack_at TIMESTAMPTZ;
ALTER TABLE device_security_state ADD COLUMN IF NOT EXISTS txack_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE device_security_state ADD COLUMN IF NOT EXISTS status_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE device_security_state ADD COLUMN IF NOT EXISTS error_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE device_security_state ADD COLUMN IF NOT EXISTS warning_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE device_security_state ADD COLUMN IF NOT EXISTS last_battery_level REAL;
ALTER TABLE device_security_state ADD COLUMN IF NOT EXISTS last_margin INTEGER;

CREATE INDEX IF NOT EXISTS idx_devices_room_id ON devices(room_id);
CREATE INDEX IF NOT EXISTS idx_devices_site_id ON devices(site_id);
CREATE INDEX IF NOT EXISTS idx_measurements_device_time_desc ON measurements(device_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_measurements_time_desc ON measurements(time DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_active_triggered_at ON alerts(is_active, triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_events_dev_eui_time_desc ON security_events(dev_eui, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_events_event_type_time_desc ON security_events(event_type, observed_at DESC);
"""


def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
            cur.execute("SELECT create_hypertable('measurements', 'time', if_not_exists => TRUE);")
        conn.commit()


def ensure_org_site_room_gateway_device(cur, m: MeasurementIn):
    cur.execute(
        """
        INSERT INTO organizations (name)
        VALUES (%s)
        ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
        RETURNING id;
        """,
        (m.organization_name,),
    )
    organization_id = cur.fetchone()["id"]

    cur.execute(
        """
        INSERT INTO sites (organization_id, name)
        VALUES (%s, %s)
        ON CONFLICT (organization_id, name) DO UPDATE SET name = EXCLUDED.name
        RETURNING id;
        """,
        (organization_id, m.site_name),
    )
    site_id = cur.fetchone()["id"]

    cur.execute(
        """
        INSERT INTO rooms (site_id, name, target_co2_ppm)
        VALUES (%s, %s, %s)
        ON CONFLICT (site_id, name)
        DO UPDATE SET target_co2_ppm = COALESCE(EXCLUDED.target_co2_ppm, rooms.target_co2_ppm)
        RETURNING id, target_co2_ppm;
        """,
        (site_id, m.room_name, m.target_co2_ppm or 1000),
    )
    room_row = cur.fetchone()
    room_id = room_row["id"]
    threshold = room_row["target_co2_ppm"]

    gateway_id = None
    if m.gateway_eui:
        cur.execute(
            """
            INSERT INTO gateways (gateway_eui, name, site_id, last_seen_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (gateway_eui)
            DO UPDATE SET
                name = COALESCE(EXCLUDED.name, gateways.name),
                site_id = COALESCE(EXCLUDED.site_id, gateways.site_id),
                last_seen_at = EXCLUDED.last_seen_at
            RETURNING id;
            """,
            (m.gateway_eui, m.gateway_name, site_id, m.ts),
        )
        gateway_id = cur.fetchone()["id"]

    cur.execute(
        """
        INSERT INTO devices (
            device_eui, name, organization_id, site_id, room_id, gateway_id,
            firmware_version, battery_type, status, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'online', now())
        ON CONFLICT (device_eui)
        DO UPDATE SET
            name = COALESCE(EXCLUDED.name, devices.name),
            organization_id = EXCLUDED.organization_id,
            site_id = EXCLUDED.site_id,
            room_id = EXCLUDED.room_id,
            gateway_id = COALESCE(EXCLUDED.gateway_id, devices.gateway_id),
            firmware_version = COALESCE(EXCLUDED.firmware_version, devices.firmware_version),
            battery_type = COALESCE(EXCLUDED.battery_type, devices.battery_type),
            status = 'online',
            updated_at = now()
        RETURNING id;
        """,
        (
            m.device_eui,
            m.device_name,
            organization_id,
            site_id,
            room_id,
            gateway_id,
            m.firmware_version,
            m.battery_type,
        ),
    )
    device_id = cur.fetchone()["id"]

    return {
        "organization_id": organization_id,
        "site_id": site_id,
        "room_id": room_id,
        "gateway_id": gateway_id,
        "device_id": device_id,
        "threshold": threshold,
    }



def sync_co2_alert(cur, device_id: int, room_id: int, measured_value: int, threshold: int, ts: datetime):
    cur.execute(
        """
        SELECT id
        FROM alerts
        WHERE device_id = %s
          AND alert_type = 'co2_high'
          AND is_active = TRUE
        ORDER BY triggered_at DESC
        LIMIT 1;
        """,
        (device_id,),
    )
    active_alert = cur.fetchone()

    if measured_value > threshold:
        if active_alert is None:
            severity = 'critical' if measured_value >= threshold + 400 else 'warning'
            cur.execute(
                """
                INSERT INTO alerts (
                    device_id, room_id, alert_type, severity, message,
                    threshold_value, measured_value, triggered_at, is_active
                )
                VALUES (%s, %s, 'co2_high', %s, %s, %s, %s, %s, TRUE);
                """,
                (
                    device_id,
                    room_id,
                    severity,
                    f'CO₂ exceeded threshold ({measured_value} ppm > {threshold} ppm).',
                    threshold,
                    measured_value,
                    ts,
                ),
            )
    elif active_alert is not None:
        cur.execute(
            """
            UPDATE alerts
            SET is_active = FALSE,
                cleared_at = %s,
                measured_value = %s,
                message = %s
            WHERE id = %s;
            """,
            (
                ts,
                measured_value,
                f'CO₂ returned below threshold ({measured_value} ppm <= {threshold} ppm).',
                active_alert["id"],
            ),
        )



def store_measurement(cur, m: MeasurementIn):
    ids = ensure_org_site_room_gateway_device(cur, m)

    cur.execute(
        """
        INSERT INTO measurements (
            time, device_id, gateway_id, co2_ppm, temp_c, rh, battery_v, rssi, snr
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (time, device_id) DO UPDATE SET
            gateway_id = EXCLUDED.gateway_id,
            co2_ppm = EXCLUDED.co2_ppm,
            temp_c = EXCLUDED.temp_c,
            rh = EXCLUDED.rh,
            battery_v = EXCLUDED.battery_v,
            rssi = EXCLUDED.rssi,
            snr = EXCLUDED.snr;
        """,
        (
            m.ts,
            ids["device_id"],
            ids["gateway_id"],
            m.co2_ppm,
            m.temp_c,
            m.rh,
            m.battery_v,
            m.rssi,
            m.snr,
        ),
    )

    cur.execute(
        """
        INSERT INTO device_last_state (
            device_id, gateway_id, last_measurement_at, co2_ppm, temp_c, rh, battery_v, rssi, snr, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (device_id) DO UPDATE SET
            gateway_id = EXCLUDED.gateway_id,
            last_measurement_at = EXCLUDED.last_measurement_at,
            co2_ppm = EXCLUDED.co2_ppm,
            temp_c = EXCLUDED.temp_c,
            rh = EXCLUDED.rh,
            battery_v = EXCLUDED.battery_v,
            rssi = EXCLUDED.rssi,
            snr = EXCLUDED.snr,
            updated_at = now();
        """,
        (
            ids["device_id"],
            ids["gateway_id"],
            m.ts,
            m.co2_ppm,
            m.temp_c,
            m.rh,
            m.battery_v,
            m.rssi,
            m.snr,
        ),
    )

    sync_co2_alert(
        cur,
        device_id=ids["device_id"],
        room_id=ids["room_id"],
        measured_value=m.co2_ppm,
        threshold=ids["threshold"],
        ts=m.ts,
    )



def decode_lab_payload(payload_b64: str) -> Optional[dict[str, Any]]:
    try:
        payload = base64.b64decode(payload_b64)
    except Exception:
        return None
    if len(payload) < 7:
        return None
    co2 = int.from_bytes(payload[0:2], "big")
    temp_raw = int.from_bytes(payload[2:4], "big", signed=False)
    rh = payload[4]
    batt_mv = int.from_bytes(payload[5:7], "big")
    return {
        "co2_ppm": co2,
        "temp_c": round(temp_raw / 100.0, 2),
        "rh": float(rh),
        "battery_v": round(batt_mv / 1000.0, 3),
    }



def parse_observed_at(payload: dict[str, Any]) -> datetime:
    value = payload.get("time")
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)



def extract_deduplication_id(payload: dict[str, Any]) -> Optional[str]:
    if payload.get("deduplicationId"):
        return payload.get("deduplicationId")
    context = payload.get("context") or {}
    if isinstance(context, dict) and context.get("deduplication_id"):
        return context.get("deduplication_id")
    return None



def classify_security_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    level = payload.get("level")
    code = payload.get("code")
    description = payload.get("description")
    ack = payload.get("acknowledged")
    text = " ".join([str(code or ""), str(description or ""), str(level or "")]).upper()

    mic_status = "unknown"
    failure_class = None
    replay_hint = False

    if "MIC" in text:
        mic_status = "invalid"
        failure_class = "mic"

    replay_terms = [
        "REPLAY", "DUPLICATE", "FCNT", "FRAME COUNTER", "FRAME-COUNTER", "NONCE", "COUNTER RESET",
    ]
    if any(term in text for term in replay_terms):
        replay_hint = True
        if failure_class is None:
            failure_class = "replay"

    if event_type == "ack" and ack is False and failure_class is None:
        failure_class = "downlink_nack"

    if event_type == "log" and failure_class is None:
        if str(level or "").upper() == "ERROR":
            failure_class = "error"
        elif str(level or "").upper() == "WARNING":
            failure_class = "warning"

    return {
        "event_level": level,
        "code": code,
        "description": description,
        "mic_status": mic_status,
        "failure_class": failure_class,
        "replay_hint": replay_hint,
    }



def store_security_event(topic: str, payload: dict[str, Any]):
    parts = topic.split("/")
    event_type = parts[-1] if parts else "unknown"
    device_info = payload.get("deviceInfo") or {}
    observed_at = parse_observed_at(payload)
    rx_info = (payload.get("rxInfo") or [None])[0] or {}
    gateway_id = payload.get("gatewayId") or rx_info.get("gatewayId")
    rssi = rx_info.get("rssi")
    snr = rx_info.get("snr")
    deduplication_id = extract_deduplication_id(payload)
    classification = classify_security_event(event_type, payload)
    battery_level = payload.get("batteryLevel")
    margin = payload.get("margin")
    dev_addr = payload.get("devAddr")

    with get_conn() as conn:
        with conn.cursor() as cur:
            replay_suspected = classification["replay_hint"]
            if deduplication_id:
                cur.execute(
                    """
                    SELECT 1
                    FROM security_events
                    WHERE deduplication_id = %s AND event_type = %s AND COALESCE(dev_eui, '') = COALESCE(%s, '')
                    LIMIT 1;
                    """,
                    (deduplication_id, event_type, device_info.get("devEui")),
                )
                replay_suspected = replay_suspected or (cur.fetchone() is not None)

            cur.execute(
                """
                INSERT INTO security_events (
                    observed_at, source, event_type, tenant_id, tenant_name,
                    application_id, application_name, device_profile_id, device_profile_name,
                    device_name, dev_eui, gateway_id, deduplication_id, code, description,
                    event_level, failure_class, dev_addr, battery_level, margin,
                    acknowledged, f_cnt_down, f_port, dr, rssi, snr,
                    replay_suspected, mic_status, raw_event
                )
                VALUES (
                    %s, 'chirpstack', %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s::jsonb
                );
                """,
                (
                    observed_at,
                    event_type,
                    device_info.get("tenantId"),
                    device_info.get("tenantName"),
                    device_info.get("applicationId"),
                    device_info.get("applicationName"),
                    device_info.get("deviceProfileId"),
                    device_info.get("deviceProfileName"),
                    device_info.get("deviceName"),
                    device_info.get("devEui"),
                    gateway_id,
                    deduplication_id,
                    classification["code"],
                    classification["description"],
                    classification["event_level"],
                    classification["failure_class"],
                    dev_addr,
                    battery_level,
                    margin,
                    payload.get("acknowledged"),
                    payload.get("fCntDown"),
                    payload.get("fPort"),
                    payload.get("dr"),
                    rssi,
                    snr,
                    replay_suspected,
                    classification["mic_status"],
                    json.dumps(payload),
                ),
            )

            dev_eui = device_info.get("devEui")
            if dev_eui:
                cur.execute(
                    """
                    INSERT INTO device_security_state (
                        dev_eui, device_name, tenant_name, application_name,
                        last_join_at, last_up_at, last_log_at, last_status_at, last_ack_at, last_txack_at,
                        join_count, up_count, ack_count, txack_count, status_count, log_count,
                        error_count, warning_count, mic_error_count, replay_suspected_count,
                        last_battery_level, last_margin, last_rssi, last_snr, updated_at
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, now()
                    )
                    ON CONFLICT (dev_eui) DO UPDATE SET
                        device_name = COALESCE(EXCLUDED.device_name, device_security_state.device_name),
                        tenant_name = COALESCE(EXCLUDED.tenant_name, device_security_state.tenant_name),
                        application_name = COALESCE(EXCLUDED.application_name, device_security_state.application_name),
                        last_join_at = COALESCE(EXCLUDED.last_join_at, device_security_state.last_join_at),
                        last_up_at = COALESCE(EXCLUDED.last_up_at, device_security_state.last_up_at),
                        last_log_at = COALESCE(EXCLUDED.last_log_at, device_security_state.last_log_at),
                        last_status_at = COALESCE(EXCLUDED.last_status_at, device_security_state.last_status_at),
                        last_ack_at = COALESCE(EXCLUDED.last_ack_at, device_security_state.last_ack_at),
                        last_txack_at = COALESCE(EXCLUDED.last_txack_at, device_security_state.last_txack_at),
                        join_count = device_security_state.join_count + EXCLUDED.join_count,
                        up_count = device_security_state.up_count + EXCLUDED.up_count,
                        ack_count = device_security_state.ack_count + EXCLUDED.ack_count,
                        txack_count = device_security_state.txack_count + EXCLUDED.txack_count,
                        status_count = device_security_state.status_count + EXCLUDED.status_count,
                        log_count = device_security_state.log_count + EXCLUDED.log_count,
                        error_count = device_security_state.error_count + EXCLUDED.error_count,
                        warning_count = device_security_state.warning_count + EXCLUDED.warning_count,
                        mic_error_count = device_security_state.mic_error_count + EXCLUDED.mic_error_count,
                        replay_suspected_count = device_security_state.replay_suspected_count + EXCLUDED.replay_suspected_count,
                        last_battery_level = COALESCE(EXCLUDED.last_battery_level, device_security_state.last_battery_level),
                        last_margin = COALESCE(EXCLUDED.last_margin, device_security_state.last_margin),
                        last_rssi = COALESCE(EXCLUDED.last_rssi, device_security_state.last_rssi),
                        last_snr = COALESCE(EXCLUDED.last_snr, device_security_state.last_snr),
                        updated_at = now();
                    """,
                    (
                        dev_eui,
                        device_info.get("deviceName"),
                        device_info.get("tenantName"),
                        device_info.get("applicationName"),
                        observed_at if event_type == "join" else None,
                        observed_at if event_type == "up" else None,
                        observed_at if event_type == "log" else None,
                        observed_at if event_type == "status" else None,
                        observed_at if event_type == "ack" else None,
                        observed_at if event_type == "txack" else None,
                        1 if event_type == "join" else 0,
                        1 if event_type == "up" else 0,
                        1 if event_type == "ack" else 0,
                        1 if event_type == "txack" else 0,
                        1 if event_type == "status" else 0,
                        1 if event_type == "log" else 0,
                        1 if str(classification["event_level"] or "").upper() == "ERROR" else 0,
                        1 if str(classification["event_level"] or "").upper() == "WARNING" else 0,
                        1 if classification["mic_status"] == "invalid" else 0,
                        1 if replay_suspected else 0,
                        battery_level,
                        margin,
                        rssi,
                        snr,
                    ),
                )

            if event_type == "up":
                measurement = decode_lab_payload(payload.get("data", ""))
                if measurement:
                    m = MeasurementIn(
                        device_eui=device_info.get("devEui") or "unknown",
                        device_name=device_info.get("deviceName"),
                        organization_name=device_info.get("tenantName") or "ChirpStack",
                        site_name=DEFAULT_SITE_NAME,
                        room_name=device_info.get("applicationName") or "ChirpStack Simulation",
                        gateway_eui=gateway_id,
                        gateway_name=gateway_id,
                        ts=observed_at,
                        rssi=rssi,
                        snr=snr,
                        **measurement,
                    )
                    store_measurement(cur, m)

        conn.commit()


def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    client.subscribe(CHIRPSTACK_MQTT_TOPIC, qos=0)



def on_mqtt_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception:
        return
    try:
        store_security_event(msg.topic, payload)
    except Exception as exc:
        print(f"[mqtt-bridge] failed to store event from {msg.topic}: {exc}")



def start_mqtt_bridge():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_mqtt_connect
    client.on_message = on_mqtt_message
    client.connect(CHIRPSTACK_MQTT_HOST, CHIRPSTACK_MQTT_PORT, 60)
    client.loop_forever()


@app.on_event("startup")
def on_startup():
    global MQTT_THREAD_STARTED
    init_db()
    if CHIRPSTACK_MQTT_ENABLED and not MQTT_THREAD_STARTED:
        thread = threading.Thread(target=start_mqtt_bridge, daemon=True)
        thread.start()
        MQTT_THREAD_STARTED = True


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "vb-api",
        "version": app.version,
        "chirpstack_mqtt_enabled": CHIRPSTACK_MQTT_ENABLED,
    }


@app.get("/db-check")
def db_check():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT now() AS db_time;")
            row = cur.fetchone()
    return {"db_ok": True, "db_time": row["db_time"].isoformat()}


@app.post("/ingest")
def ingest(m: MeasurementIn):
    with get_conn() as conn:
        with conn.cursor() as cur:
            store_measurement(cur, m)
        conn.commit()
    return {
        "stored": True,
        "device_eui": m.device_eui,
        "room": m.room_name,
        "site": m.site_name,
        "organization": m.organization_name,
    }


@app.get("/organizations")
def list_organizations():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT o.id, o.name, o.created_at, COUNT(d.id) AS device_count
                FROM organizations o
                LEFT JOIN devices d ON d.organization_id = o.id
                GROUP BY o.id
                ORDER BY o.name;
                """
            )
            return cur.fetchall()


@app.get("/devices")
def list_devices():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.device_eui, d.name, d.status, d.firmware_version, d.battery_type,
                       o.name AS organization_name, s.name AS site_name, r.name AS room_name,
                       ls.last_measurement_at, ls.co2_ppm, ls.temp_c, ls.rh, ls.battery_v, ls.rssi, ls.snr
                FROM devices d
                LEFT JOIN organizations o ON o.id = d.organization_id
                LEFT JOIN sites s ON s.id = d.site_id
                LEFT JOIN rooms r ON r.id = d.room_id
                LEFT JOIN device_last_state ls ON ls.device_id = d.id
                ORDER BY o.name NULLS LAST, s.name NULLS LAST, r.name NULLS LAST, d.device_eui;
                """
            )
            return cur.fetchall()


@app.get("/latest")
def latest(limit: int = Query(default=50, ge=1, le=500)):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.device_eui, d.name AS device_name,
                       o.name AS organization_name, s.name AS site_name, r.name AS room_name,
                       ls.last_measurement_at AS time, ls.co2_ppm, ls.temp_c, ls.rh,
                       ls.battery_v, ls.rssi, ls.snr
                FROM device_last_state ls
                JOIN devices d ON d.id = ls.device_id
                LEFT JOIN organizations o ON o.id = d.organization_id
                LEFT JOIN sites s ON s.id = d.site_id
                LEFT JOIN rooms r ON r.id = d.room_id
                ORDER BY ls.last_measurement_at DESC
                LIMIT %s;
                """,
                (limit,),
            )
            rows = cur.fetchall()
    return [{**row, "time": row["time"].isoformat() if row["time"] else None} for row in rows]


@app.get("/devices/{device_eui}/latest")
def device_latest(device_eui: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.device_eui, d.name AS device_name,
                       o.name AS organization_name, s.name AS site_name, r.name AS room_name,
                       ls.last_measurement_at AS time, ls.co2_ppm, ls.temp_c, ls.rh,
                       ls.battery_v, ls.rssi, ls.snr
                FROM devices d
                LEFT JOIN organizations o ON o.id = d.organization_id
                LEFT JOIN sites s ON s.id = d.site_id
                LEFT JOIN rooms r ON r.id = d.room_id
                LEFT JOIN device_last_state ls ON ls.device_id = d.id
                WHERE d.device_eui = %s;
                """,
                (device_eui,),
            )
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if row["time"] is not None:
        row["time"] = row["time"].isoformat()
    return row



def get_history_bucket(hours: int):
    if hours <= 24:
        return None
    if hours <= 24 * 7:
        return "15 minutes"
    if hours <= 24 * 30:
        return "1 hour"
    if hours <= 24 * 90:
        return "6 hours"
    if hours <= 24 * 180:
        return "12 hours"
    return "1 day"


@app.get("/devices/{device_eui}/history")
def device_history(
    device_eui: str,
    hours: int = Query(default=24, ge=1, le=24 * 365),
    limit: int = Query(default=1000, ge=1, le=5000),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    bucket = get_history_bucket(hours)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM devices WHERE device_eui = %s;", (device_eui,))
            device = cur.fetchone()
            if device is None:
                raise HTTPException(status_code=404, detail="Device not found")

            if bucket is None:
                cur.execute(
                    """
                    SELECT time, co2_ppm, temp_c, rh, battery_v, rssi, snr
                    FROM measurements
                    WHERE device_id = %s
                      AND time >= %s
                    ORDER BY time DESC
                    LIMIT %s;
                    """,
                    (device["id"], since, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        time_bucket(%s::interval, time) AS time,
                        ROUND(AVG(co2_ppm))::int AS co2_ppm,
                        AVG(temp_c)::real AS temp_c,
                        AVG(rh)::real AS rh,
                        AVG(battery_v)::real AS battery_v,
                        ROUND(AVG(rssi))::int AS rssi,
                        AVG(snr)::real AS snr
                    FROM measurements
                    WHERE device_id = %s
                      AND time >= %s
                    GROUP BY 1
                    ORDER BY 1 DESC
                    LIMIT %s;
                    """,
                    (bucket, device["id"], since, limit),
                )
            rows = cur.fetchall()
    return [{**row, "time": row["time"].isoformat()} for row in rows]


@app.get("/alerts")
def list_alerts(active_only: bool = True, limit: int = Query(default=100, ge=1, le=1000)):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a.alert_type, a.severity, a.message,
                       a.threshold_value, a.measured_value,
                       a.triggered_at, a.cleared_at, a.is_active,
                       d.device_eui, r.name AS room_name
                FROM alerts a
                JOIN devices d ON d.id = a.device_id
                LEFT JOIN rooms r ON r.id = a.room_id
                WHERE (%s = FALSE OR a.is_active = TRUE)
                ORDER BY a.triggered_at DESC
                LIMIT %s;
                """,
                (active_only, limit),
            )
            rows = cur.fetchall()
    for row in rows:
        row["triggered_at"] = row["triggered_at"].isoformat() if row["triggered_at"] else None
        row["cleared_at"] = row["cleared_at"].isoformat() if row["cleared_at"] else None
    return rows


@app.get("/security/events")
def security_events(limit: int = Query(default=100, ge=1, le=1000), event_type: Optional[str] = None):
    query = """
        SELECT id, observed_at, source, event_type, tenant_name, application_name,
               device_name, dev_eui, gateway_id, deduplication_id, code, description,
               event_level, failure_class, acknowledged, f_cnt_down, f_port, dr,
               battery_level, margin, rssi, snr, replay_suspected, mic_status
        FROM security_events
    """
    params: list[Any] = []
    if event_type:
        query += " WHERE event_type = %s"
        params.append(event_type)
    query += " ORDER BY observed_at DESC LIMIT %s;"
    params.append(limit)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
    for row in rows:
        row["observed_at"] = row["observed_at"].isoformat() if row["observed_at"] else None
    return rows


@app.get("/devices/{device_eui}/security")
def device_security(device_eui: str, limit: int = Query(default=50, ge=1, le=500)):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT dev_eui, device_name, tenant_name, application_name,
                       last_join_at, last_up_at, last_log_at, last_status_at, last_ack_at, last_txack_at,
                       join_count, up_count, ack_count, txack_count, status_count, log_count,
                       error_count, warning_count, mic_error_count, replay_suspected_count,
                       last_battery_level, last_margin, last_rssi, last_snr, updated_at
                FROM device_security_state
                WHERE dev_eui = %s;
                """,
                (device_eui,),
            )
            state = cur.fetchone()
            cur.execute(
                """
                SELECT id, observed_at, event_type, gateway_id, deduplication_id, code, description,
                       event_level, failure_class, replay_suspected, mic_status,
                       battery_level, margin, rssi, snr
                FROM security_events
                WHERE dev_eui = %s
                ORDER BY observed_at DESC
                LIMIT %s;
                """,
                (device_eui, limit),
            )
            events = cur.fetchall()
    if state is None:
        raise HTTPException(status_code=404, detail="Device security state not found")
    for key in ("last_join_at", "last_up_at", "last_log_at", "last_status_at", "last_ack_at", "last_txack_at", "updated_at"):
        if state.get(key):
            state[key] = state[key].isoformat()
    for row in events:
        row["observed_at"] = row["observed_at"].isoformat()
    return {"state": state, "events": events}


@app.get("/security/summary")
def security_summary():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_events,
                    COUNT(*) FILTER (WHERE event_type = 'join') AS join_events,
                    COUNT(*) FILTER (WHERE event_type = 'up') AS up_events,
                    COUNT(*) FILTER (WHERE event_type = 'log') AS log_events,
                    COUNT(*) FILTER (WHERE event_type = 'status') AS status_events,
                    COUNT(*) FILTER (WHERE event_type = 'ack') AS ack_events,
                    COUNT(*) FILTER (WHERE event_type = 'txack') AS txack_events,
                    COUNT(*) FILTER (WHERE mic_status = 'invalid') AS mic_failures,
                    COUNT(*) FILTER (WHERE replay_suspected = TRUE) AS replay_flags,
                    COUNT(*) FILTER (WHERE event_level = 'ERROR') AS error_events,
                    COUNT(*) FILTER (WHERE event_level = 'WARNING') AS warning_events,
                    COUNT(DISTINCT dev_eui) FILTER (WHERE dev_eui IS NOT NULL) AS devices_seen
                FROM security_events;
                """
            )
            summary = cur.fetchone()
            cur.execute(
                """
                SELECT dev_eui, device_name, tenant_name, application_name,
                       join_count, up_count, ack_count, txack_count, status_count, log_count,
                       error_count, warning_count, mic_error_count, replay_suspected_count,
                       last_battery_level, last_margin, last_rssi, last_snr, updated_at
                FROM device_security_state
                ORDER BY updated_at DESC
                LIMIT 20;
                """
            )
            devices = cur.fetchall()
    for row in devices:
        row["updated_at"] = row["updated_at"].isoformat()
    return {"summary": summary, "devices": devices}


@app.get("/security/raw-demo")
def security_raw_demo():
    return {"results": run_demo()}
