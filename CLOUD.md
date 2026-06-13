# OpenOSINT Cloud — Deploy & Polar Setup Guide

One-call, one-bill OSINT API.  Hosted on Heroku, billing via Polar.sh (Merchant of Record — handles international VAT automatically).

---

## 1. Prerequisites

- Heroku CLI installed and logged in (`heroku login`)
- Polar.sh account at https://polar.sh
- This repo cloned locally

---

## 2. Heroku deploy

```bash
# Create app
heroku create your-app-name

# Add Postgres (free hobby tier is sufficient to start)
heroku addons:create heroku-postgresql:essential-0

# Set required secrets
heroku config:set POLAR_TOKEN=pat_...
heroku config:set POLAR_WEBHOOK_SECRET=whsec_...   # set this after step 3

# Set upstream keys used by the v1 tool set
heroku config:set IP2LOCATION_API_KEY=...
heroku config:set ABUSEIPDB_API_KEY=...
heroku config:set GITHUB_TOKEN=...          # optional, raises GH rate limit
heroku config:set IPINFO_TOKEN=...          # optional, raises ipinfo rate limit

# Deploy
git push heroku main

# Initialise the database schema (run once)
heroku run psql \$DATABASE_URL -f db/init.sql

# Confirm the web dyno is up
heroku open
heroku logs --tail
```

The server binds to `$PORT` (set by Heroku automatically).

---

## 3. Polar setup

### 3a. Create three products

In your Polar dashboard create three products:

| Product  | Type         | Price    | Credits |
|----------|--------------|----------|---------|
| payg     | One-time     | $10      | 100     |
| starter  | Subscription | $19 / mo | 1 000   |
| pro      | Subscription | $49 / mo | 5 000   |

### 3b. Add a License Key benefit to each product

1. Open each product → **Benefits** → **Add benefit** → **License Keys**
2. Name it (e.g. "OpenOSINT Cloud API Key")
3. Save.  Copy the **benefit ID** (`benefit_...`) for each product.

These License Keys are the customers' API keys.  Polar mints them on purchase and displays them in the customer portal — no email flow to build.

### 3c. Set benefit / product IDs as Heroku config vars

```bash
heroku config:set POLAR_BENEFIT_ID_PAYG=benefit_...
heroku config:set POLAR_BENEFIT_ID_STARTER=benefit_...
heroku config:set POLAR_BENEFIT_ID_PRO=benefit_...

heroku config:set POLAR_PRODUCT_ID_STARTER=prod_...
heroku config:set POLAR_PRODUCT_ID_PRO=prod_...
```

### 3d. Set checkout URLs

Copy the hosted checkout URL for each product from Polar and set:

```bash
heroku config:set POLAR_CHECKOUT_PAYG=https://polar.sh/...
heroku config:set POLAR_CHECKOUT_STARTER=https://polar.sh/...
heroku config:set POLAR_CHECKOUT_PRO=https://polar.sh/...
```

### 3e. Register the webhook endpoint

1. Polar dashboard → **Developer** → **Webhooks** → **Add endpoint**
2. URL: `https://your-app-name.herokuapp.com/v1/polar/webhook`
3. Subscribe to these events:
   - `benefit_grant.created`
   - `benefit_grant.updated`
   - `benefit_grant.revoked`
   - `subscription.updated`
4. Copy the **Signing Secret** (`whsec_...`) and set it:
   ```bash
   heroku config:set POLAR_WEBHOOK_SECRET=whsec_...
   ```
5. Send a **test event** for each type and verify the response is `{"status":"ok"}`.
   Use `heroku logs --tail` to see the handler output.

> ⚠️  **Verify event field paths against the live test-event payload.**
> The webhook handler reads the license key from
> `data.properties.license_key.key` with a `data.properties.display_key`
> fallback.  If neither field exists in the real payload, the handler logs an
> error and skips the upsert.  Check `heroku logs` after the first real purchase.

---

## 4. Running locally

```bash
# Install with cloud extras
pip install -e ".[dev]"
pip install fastapi uvicorn[standard] asyncpg httpx pydantic

# Copy and fill in secrets (DATABASE_URL optional — omit for in-memory backend)
cp .env.example .env

# Start the gateway
uvicorn cloud.main:app --reload --port 8000
```

---

## 5. Running the test suite

```bash
pytest tests/test_cloud.py -v
```

No network calls are made.  The tests run against the in-memory backend.

---

## 6. Syntax / import check

```bash
python -m py_compile cloud/main.py cloud/db.py cloud/polar.py cloud/tools.py \
  cloud/auth.py cloud/config.py \
  cloud/routes/enrich.py cloud/routes/usage.py \
  cloud/routes/checkout.py cloud/routes/webhook.py
```

---

## 7. curl examples

### Check your balance

```bash
curl -s https://your-app.herokuapp.com/v1/usage \
  -H "X-API-Key: YOUR_LICENSE_KEY" | jq .
# → {"plan":"starter","credits":999}
```

### Run an OSINT tool

```bash
curl -s -X POST https://your-app.herokuapp.com/v1/enrich \
  -H "X-API-Key: YOUR_LICENSE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tool":"search_ip","target":"8.8.8.8"}' | jq .
```

```json
{
  "tool": "search_ip",
  "target": "8.8.8.8",
  "timestamp": "2026-06-12T10:00:00+00:00",
  "results": [
    "IP intelligence for '8.8.8.8':",
    "[+] Ip: 8.8.8.8",
    "[+] Hostname: dns.google",
    "[+] Org: AS15169 Google LLC",
    "[+] City: Mountain View",
    "[+] Country: US"
  ],
  "error": null,
  "credits_left": 998
}
```

### Get a checkout URL (for 402 → top-up flow)

```bash
curl -s "https://your-app.herokuapp.com/v1/checkout?plan=starter" | jq .
# → {"plan":"starter","credits":1000,"url":"https://polar.sh/..."}
```

---

## 8. Polar event names wired (verify before going live)

| Event string          | Handler action                                 |
|-----------------------|------------------------------------------------|
| `benefit_grant.created` | Extract license key, upsert customer + credits |
| `benefit_grant.updated` | Same — handles key refresh                    |
| `benefit_grant.revoked` | Zero credits                                  |
| `subscription.updated`  | If status == "active": refill credits to plan amount |

> Use Polar's **Send test event** feature to confirm these string values match
> what Polar actually sends before processing real purchases.

---

## 9. Environment variable reference

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | Production | Heroku Postgres DSN (set by addon) |
| `POLAR_TOKEN` | Production | Polar API access token |
| `POLAR_WEBHOOK_SECRET` | Production | Webhook HMAC signing secret |
| `POLAR_CHECKOUT_*` | Production | Hosted checkout URLs per plan |
| `POLAR_BENEFIT_ID_*` | Production | Benefit IDs for plan mapping |
| `POLAR_PRODUCT_ID_*` | Production | Product IDs for renewal refill |
| `IP2LOCATION_API_KEY` | Recommended | search_ip2location tool |
| `ABUSEIPDB_API_KEY` | Recommended | search_abuseipdb tool |
| `GITHUB_TOKEN` | Optional | Raises GitHub rate limit 60→5000/h |
| `IPINFO_TOKEN` | Optional | Raises ipinfo.io rate limit |

---

## 10. v1 synchronous tool allow-list

| Tool | Upstream | Key source | Provider string | Typical latency |
|---|---|---|---|---|
| `search_ip` | ipinfo.io | **customer** (BYOK) | `ipinfo` | ~1 s |
| `search_whois` | python-whois | none | — | ~2–5 s |
| `search_github` | GitHub API | customer optional | `github` | ~2–5 s |
| `generate_dorks` | Pure Python | none | — | <100 ms |
| `search_paste` | psbdmp.ws | none | — | ~2–5 s |
| `search_dns` | dnspython | none | — | ~2–5 s |
| `search_abuseipdb` | AbuseIPDB | **customer** (BYOK) | `abuseipdb` | ~1–2 s |
| `search_ip2location` | IP2Location (sponsored) | server | — | ~1–2 s |

**Key source legend:**
- **customer** — customer must add their own key via `POST /v1/keys` before calling this tool; missing key returns 422.
- **customer optional** — works unauthenticated (lower rate limits); add a key to increase limits.
- **server** — key is provided by the operator; customers get it included at no extra step.
- **none** — no credential required.

Credits are **not** deducted when a tool returns an upstream error (`Scan error: ...`).

All tool calls are wrapped in a 25 s `asyncio.wait_for` (Heroku 30 s H12 limit - 5 s headroom).  A 504 is returned if the tool exceeds the budget.

---

## 11. BYOK key management

Customers store their own upstream API keys once; every `POST /v1/enrich` call resolves them automatically.  Keys are encrypted at rest with Fernet (`CONFIG_ENCRYPTION_KEY`).

### Add a key

```bash
# Add an ipinfo.io token
curl -s -X POST https://your-app.herokuapp.com/v1/keys \
  -H "X-API-Key: YOUR_LICENSE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"provider": "ipinfo", "secret": "your_ipinfo_token"}'
# -> HTTP 204 No Content

# Add an AbuseIPDB key
curl -s -X POST https://your-app.herokuapp.com/v1/keys \
  -H "X-API-Key: YOUR_LICENSE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"provider": "abuseipdb", "secret": "your_abuseipdb_key"}'

# Add a GitHub token (optional -- improves rate limits from 60 to 5000 req/h)
curl -s -X POST https://your-app.herokuapp.com/v1/keys \
  -H "X-API-Key: YOUR_LICENSE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"provider": "github", "secret": "ghp_..."}'
```

### List stored keys (masked)

```bash
curl -s https://your-app.herokuapp.com/v1/keys \
  -H "X-API-Key: YOUR_LICENSE_KEY" | jq .
# -> [{"provider":"ipinfo","masked":"****a1b2"},{"provider":"abuseipdb","masked":"****xy99"}]
```

### Remove a key

```bash
curl -s -X DELETE https://your-app.herokuapp.com/v1/keys/ipinfo \
  -H "X-API-Key: YOUR_LICENSE_KEY"
# -> HTTP 204 No Content
```

### End-to-end: store an ipinfo key then run search_ip

```bash
# 1. Store the key (once)
curl -s -X POST https://your-app.herokuapp.com/v1/keys \
  -H "X-API-Key: YOUR_LICENSE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"provider": "ipinfo", "secret": "your_ipinfo_token"}'

# 2. Run search_ip -- stored key is resolved automatically, no extra header needed
curl -s -X POST https://your-app.herokuapp.com/v1/enrich \
  -H "X-API-Key: YOUR_LICENSE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tool": "search_ip", "target": "8.8.8.8"}' | jq .
```

### Operator setup: CONFIG_ENCRYPTION_KEY

```bash
# Generate a Fernet key (do this once, store it safely)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Set it on Heroku before first deployment with DATABASE_URL
heroku config:set CONFIG_ENCRYPTION_KEY=<generated_key>
```

> **Warning:** Never rotate `CONFIG_ENCRYPTION_KEY` without first decrypting and
> re-encrypting all rows in `customer_keys`.  Rotating without migration makes all
> stored secrets unreadable.
