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

SELECT create_hypertable('measurements', 'time', if_not_exists => TRUE);

ALTER TABLE devices ADD COLUMN IF NOT EXISTS organization_id BIGINT REFERENCES organizations(id) ON DELETE SET NULL;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS site_id BIGINT REFERENCES sites(id) ON DELETE SET NULL;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS room_id BIGINT REFERENCES rooms(id) ON DELETE SET NULL;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS gateway_id BIGINT REFERENCES gateways(id) ON DELETE SET NULL;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'provisioning';
ALTER TABLE devices ADD COLUMN IF NOT EXISTS firmware_version TEXT;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS battery_type TEXT;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS install_date DATE;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE measurements ADD COLUMN IF NOT EXISTS gateway_id BIGINT REFERENCES gateways(id) ON DELETE SET NULL;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS battery_v REAL;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS rssi INTEGER;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS snr REAL;

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

CREATE INDEX IF NOT EXISTS idx_devices_room_id ON devices(room_id);
CREATE INDEX IF NOT EXISTS idx_devices_site_id ON devices(site_id);
CREATE INDEX IF NOT EXISTS idx_measurements_device_time_desc ON measurements(device_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_measurements_time_desc ON measurements(time DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_active_triggered_at ON alerts(is_active, triggered_at DESC);
