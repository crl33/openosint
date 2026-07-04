-- OpenOSINT Cloud — database schema
-- Run once against your Heroku Postgres instance:
--   psql $DATABASE_URL -f db/init.sql

CREATE TABLE IF NOT EXISTS customers (
    api_key           TEXT        PRIMARY KEY,
    polar_customer_id TEXT,
    credits           INT         NOT NULL DEFAULT 0,
    plan              TEXT        NOT NULL DEFAULT 'payg',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Unique index lets us look customers up by Polar customer id.
CREATE UNIQUE INDEX IF NOT EXISTS customers_polar_id_idx
    ON customers (polar_customer_id)
    WHERE polar_customer_id IS NOT NULL;

-- Idempotency table — prevents double-credit on retried webhook deliveries.
CREATE TABLE IF NOT EXISTS processed_events (
    event_id    TEXT        PRIMARY KEY,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Customer BYOK keys, encrypted at rest with Fernet (CONFIG_ENCRYPTION_KEY).
-- Cascade delete removes keys when the customer row is deleted.
CREATE TABLE IF NOT EXISTS customer_keys (
    api_key          TEXT        NOT NULL REFERENCES customers(api_key) ON DELETE CASCADE ON UPDATE CASCADE,
    provider         TEXT        NOT NULL,
    secret_encrypted TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (api_key, provider)
);

-- OAuth login identities (GitHub / Google). Purely a web-dashboard login
-- layer on top of the api_key model — X-API-Key / MCP bearer auth never
-- reads this table. One OAuth identity links to at most one customer key
-- and vice versa (partial unique index below).
CREATE TABLE IF NOT EXISTS users (
    id                SERIAL      PRIMARY KEY,
    provider          TEXT        NOT NULL,
    provider_user_id  TEXT        NOT NULL,
    email             TEXT,
    -- Rendezvous key: written by the checkout.updated webhook so the
    -- benefit_grant.created webhook (which creates/updates `customers`)
    -- can complete the link below regardless of which event arrives first.
    polar_customer_id TEXT,
    customer_api_key  TEXT        REFERENCES customers(api_key) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, provider_user_id)
);

-- Enforces strict 1:0-or-1: a customer key can be linked to at most one user.
CREATE UNIQUE INDEX IF NOT EXISTS users_customer_api_key_idx
    ON users (customer_api_key)
    WHERE customer_api_key IS NOT NULL;
