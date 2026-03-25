import json
import os
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@vb-db:5432/visionbyte")
MQTT_HOST = os.environ.get("CHIRPSTACK_MQTT_HOST", "chirpstack-mosquitto")
MQTT_PORT = int(os.environ.get("CHIRPSTACK_MQTT_PORT", "1883"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def get_latest_up_event():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT raw_event, application_id, dev_eui
                FROM security_events
                WHERE event_type = 'up' AND application_id IS NOT NULL AND dev_eui IS NOT NULL
                ORDER BY observed_at DESC
                LIMIT 1;
                """
            )
            row = cur.fetchone()
    if not row:
        raise RuntimeError("No up event found. Wait for simulator uplinks first.")
    return row


def publish(topic: str, payload: dict):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    try:
        info = client.publish(topic, json.dumps(payload), qos=0)
        info.wait_for_publish()
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    latest = get_latest_up_event()
    up = latest["raw_event"]
    app_id = latest["application_id"]
    dev_eui = latest["dev_eui"]
    base_device_info = up.get("deviceInfo") or {}
    dedup_id = up.get("deduplicationId")

    duplicate_up = dict(up)
    duplicate_up["time"] = now_iso()
    # keep same deduplicationId on purpose to trigger replay detection in the bridge
    publish(f"application/{app_id}/device/{dev_eui}/event/up", duplicate_up)

    mic_log = {
        "time": now_iso(),
        "deviceInfo": base_device_info,
        "level": "ERROR",
        "code": "UPLINK_MIC",
        "description": "MIC of uplink frame is invalid, make sure keys are correct",
        "context": {"deduplication_id": dedup_id},
    }
    publish(f"application/{app_id}/device/{dev_eui}/event/log", mic_log)

    replay_log = {
        "time": now_iso(),
        "deviceInfo": base_device_info,
        "level": "WARNING",
        "code": "FCNT_REPLAY",
        "description": "Frame-counter or nonce replay suspected for uplink, duplicate / stale packet rejected",
        "context": {"deduplication_id": dedup_id},
    }
    publish(f"application/{app_id}/device/{dev_eui}/event/log", replay_log)

    status_event = {
        "time": now_iso(),
        "deviceInfo": base_device_info,
        "margin": 8,
        "batteryLevel": 87.5,
    }
    publish(f"application/{app_id}/device/{dev_eui}/event/status", status_event)

    ack_event = {
        "time": now_iso(),
        "deviceInfo": base_device_info,
        "queueItemId": "demo-queue-item",
        "acknowledged": False,
        "fCntDown": 4,
    }
    publish(f"application/{app_id}/device/{dev_eui}/event/ack", ack_event)

    print(
        json.dumps(
            {
                "published": True,
                "device": dev_eui,
                "application_id": app_id,
                "events": ["duplicate_up", "log_mic_invalid", "log_replay", "status", "ack_false"],
            },
            indent=2,
        )
    )
