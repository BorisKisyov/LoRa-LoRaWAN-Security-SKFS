import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.main import (
    ensure_org_site_room_gateway_device,
    get_conn,
    sync_co2_alert,
)
from app.seed_demo import DEVICES, build_measurement

SOFIA_TZ = ZoneInfo("Europe/Sofia")


def minute_index(ts: datetime) -> int:
    local_ts = ts.astimezone(SOFIA_TZ)
    return local_ts.hour * 60 + local_ts.minute


def insert_one_tick(ts: datetime):
    idx = minute_index(ts)

    with get_conn() as conn:
        with conn.cursor() as cur:
            inserted = 0

            for device in DEVICES:
                m = build_measurement(device, ts, idx)
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

                inserted += 1

        conn.commit()

    print(f"[{ts.isoformat()}] inserted {inserted} measurements")


def wait_until_next_minute():
    now = datetime.now(timezone.utc)
    sleep_seconds = 60 - now.second - (now.microsecond / 1_000_000)
    if sleep_seconds < 0.01:
        sleep_seconds = 0.01
    time.sleep(sleep_seconds)


def main():
    print("Live simulator started. Press Ctrl+C to stop.")

    try:
        while True:
            ts = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            insert_one_tick(ts)
            wait_until_next_minute()
    except KeyboardInterrupt:
        print("Live simulator stopped.")


if __name__ == "__main__":
    main()