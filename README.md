# Lab Inventory

A phone-friendly Streamlit app for a shared laboratory inventory. Scan a QR label,
choose a cabinet, select a solution, and record what you used or added. The shared
balance updates immediately. Configurable email alerts tell the right colleagues
when a solution needs a refill.

## Try it locally

Tested with Python 3.13 and Streamlit 1.66.0. Use Python 3.11 or newer.

From this folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

Open **http://localhost:8501** on the server computer. On macOS or Linux, `./run.sh`
also creates the environment, installs the dependencies, and starts the app.

The app initially opens in **demo mode**, with three cabinets and seven sample
solutions. Sample quantities are labeled, demo administration is open, and no
email can be sent. Demo changes persist in `data/demo.sqlite3`; real inventory
uses a separate database.

## The phone workflow

1. In **QR labels**, enter the address that phones can reach. For example, use
   `http://192.168.1.25:8501` for a server on the lab Wi-Fi, or your deployed HTTPS
   address. `localhost` refers to the phone itself and cannot connect to the server.
2. Download a QR image or the printable label sheet. Open the downloaded HTML
   label sheet in a browser and print it.
3. Scan the **Lab entrance** QR code with the phone's normal Camera app. It opens
   Streamlit in the browser and asks which cabinet you are using. Cabinet-specific
   QR codes open that cabinet directly using `?cabinet=<id>`.
4. View the cabinet's stock and choose **Solution / item** under **What changed?**.
5. Choose **Used** or **Added**, enter an amount and unit, and enter your name.
   Tap **Save change**. For example, using 50 mL from 750 mL leaves 700 mL.
6. A confirmation shows the new balance. **Activity** records the name, amount,
   note, and timestamp. The low-stock threshold is checked in the same transaction.

On a phone, the layout stacks vertically; **Log a change ↓** jumps to the form.
The app is served by the computer, so no special QR scanning feature or camera
permission inside Streamlit is needed. Phones and a local server must be on the
same reachable network; Wi-Fi client isolation or a firewall can block access.
The computer must remain awake and the Streamlit process must keep running.

## Set up a real lab

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`, replace the
placeholders, and restart the app. Settings can also be supplied as environment
variables; environment variables take precedence. Both the app and worker read
the same settings file from the project directory.

| Setting | Purpose |
| --- | --- |
| `LAB_DEMO` | Set to `false` for real inventory. Starts empty. Default: `true`. |
| `LAB_ADMIN_PASSWORD` | Required in real mode; at least 12 characters. Protects Manage lab. |
| `LAB_ACCESS_CODE` | Optional shared code for viewing and updating inventory. Set for a private lab. |
| `LAB_PUBLIC_URL` | Phone-reachable app URL used in email links and as the QR address default. |
| `LAB_DB_PATH` | SQLite database path. Use a persistent local disk. Default: `data/inventory.sqlite3` in real mode. |
| `LAB_SMTP_HOST` | Your institution's or provider's SMTP server. |
| `LAB_SMTP_PORT` | `587` for STARTTLS or usually `465` for implicit TLS. |
| `LAB_SMTP_SECURITY` | `starttls` (default) or `ssl`. Certificate verification stays enabled. |
| `LAB_SMTP_FROM` | Sender address accepted by your provider. |
| `LAB_SMTP_USERNAME` | SMTP login name, if required. |
| `LAB_SMTP_PASSWORD` | SMTP password / app password. Required when username is set. |

In **Manage lab → Cabinets & items**, add cabinets and stock items. For each item,
set the opening stock, low threshold, and reference stock level. The reference
level controls the stock bar; it is not a capacity limit. Concentrations and
formulations are distinct stock items. Opening stock is recorded in the activity
history. Log corrections as a documented Added or Used transaction so the history
remains intact.

In **Email alerts**, define recipients. Each recipient can cover all cabinets or
one cabinet. Saving an existing email address updates its scope and name. Removing
a recipient disables delivery and cancels their pending alerts.

Names on stock updates are self-reported. The shared access code is basic team
access, not individual account authentication or cabinet-specific permissions.
For verified identities and access restrictions, place the app behind your
institution's authenticated gateway / SSO. Use HTTPS for access beyond a trusted
local network. Secrets and data files are excluded from the included Git and
Docker build configuration.

## Email delivery and retries

An item is low when its quantity is **at or below** its threshold, including zero.
The stock update, audit entry, low-stock event, and outgoing queue entries commit
together. Saving stock never depends on SMTP success.

- A new low-stock cycle queues one email for each matching active recipient.
- Further usage while low does not repeatedly email the team.
- Refill **above** the threshold to reset the cycle. Refill to exactly the
  threshold remains low. A later drop queues a fresh alert.
- Pending alerts are cancelled after restock. Adding a recipient queues alerts
  for items already low in their selected cabinets.
- Stock saves attempt immediate delivery of up to five queued alerts when SMTP
  is configured. Administrators can also use **Send pending alerts**.
- Failed delivery stays pending and retries with delays from one minute to one
  hour. Delivery status is visible in **Manage lab → Email alerts**.
- Missing SMTP configuration keeps messages queued. Demo mode blocks delivery.

Run this alongside Streamlit for unattended delivery, including while no one has
the app open:

```sh
source .venv/bin/activate
python worker.py
```

Or run `python worker.py --once` from your scheduler every minute. The worker uses
the same database and configuration. In a service or scheduled job, use an absolute
`LAB_DB_PATH`. The provided Docker Compose setup runs the worker automatically.

Workers claim queue entries with a lease to avoid concurrent sends. SMTP does
not offer exactly-once delivery: an interrupted connection after a provider accepts
an email can produce a duplicate on retry. Messages use a stable Message-ID.
The test suite uses a mocked SMTP server; real delivery requires your own provider
credentials and a provider-side test.

## Units and shared access

- Stock units: **mL**, **g**, or **each**.
- Volume entry: mL, L, µL. Mass entry: g, mg, kg. Counts: whole items.
- Quantities use integer fixed precision: 1 µL, 1 mg, or one whole item. Incompatible
  dimensions and finer precision are rejected; there is no silent rounding.
- Each save checks the latest database balance under a write transaction. Two
  phones cannot overwrite each other's changes or use more stock than remains.
- Request IDs prevent a repeated transaction request from applying twice.
- Stock on an already open screen is a snapshot. Save uses the latest balance;
  **Refresh inventory** updates the displayed snapshot.

## Host with Docker

The app needs a Python server; static website hosting cannot run Streamlit.
For a lab server with Docker Compose:

```sh
cp .env.example .env
# Edit .env with your real credentials and phone-reachable URL.
docker compose up --build -d
```

This starts the app on port 8501 and a separate email worker. Both share the
`inventory-data` volume at `/data`. A named volume survives container replacement.
Place an HTTPS reverse proxy in front of port 8501 for a hosted deployment and
enable WebSocket forwarding. The Docker configuration is supplied but was not
executed during development.

Run one app instance against this SQLite database on a persistent local disk;
multiple users and a separate worker are supported. Do not use a shared network
filesystem or multiple independent app replicas. For multiple application
replicas, migrate storage to a server database such as PostgreSQL.

Avoid ephemeral hosting for real inventory unless you attach persistent storage.
The default SQLite file must survive restarts and redeployments. Streamlit's
hosting guidance is linked below; confirm storage support for your chosen host.

## Backup and export

**Manage lab → Data & setup** provides an inventory CSV and a consistent SQLite
backup made using the database backup API, including committed WAL changes.
**Activity** exports the latest 500 changes; the database backup contains the
complete history. CSV exports neutralize formula-like user-entered text.

To restore: stop the app and worker, set `LAB_DB_PATH` to a fresh path, place the
backup at that path, and restart both processes. Retain the old database and its
WAL files until the restore is verified. Keep backups private because they include
staff names, recipient emails, and inventory history. Back up on a schedule suitable
for your lab.

## Verify

```sh
python -m unittest discover -s tests -v
```

Tests cover stock arithmetic and unit conversion, invalid entries, simultaneous
phones, transaction deduplication, threshold cycles, recipient scope, queued
email delivery and retries, safe backups, QR labels, and the actual Streamlit
screens via AppTest. No real email is sent by tests.

## Files

- `app.py`: responsive Streamlit interface and administration.
- `inventory.py`: SQLite schema, stock transactions, audit history, durable outbox.
- `notifications.py`: TLS-protected SMTP delivery.
- `worker.py`: unattended email delivery and retries.
- `qr_labels.py`: direct links, QR PNGs, and printable labels.
- `config.py`: configuration shared by the app and worker.
- `.streamlit/`: theme, server settings, example secrets.
- `tests/`: functional and end-to-end tests.

## Streamlit references

- [Query parameters](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.query_params)
- [App testing](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest)
- [Server configuration](https://docs.streamlit.io/develop/api-reference/configuration/config.toml)
- [Deploying Streamlit](https://docs.streamlit.io/deploy)
