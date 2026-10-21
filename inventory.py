"""Durable inventory and notification outbox. All quantities use fixed precision."""
from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import closing
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

SCALE = 1000
MAX_SCALED = 10**12
UNITS = {"mL": ("mL", Decimal(1)), "L": ("mL", Decimal(1000)),
         "µL": ("mL", Decimal("0.001")), "g": ("g", Decimal(1)),
         "mg": ("g", Decimal("0.001")), "kg": ("g", Decimal(1000)),
         "each": ("each", Decimal(1))}


class InventoryError(ValueError):
    pass


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean(value, label, maximum=200):
    result = str(value).strip()
    if not result or len(result) > maximum or any(ord(c) < 32 for c in result):
        raise InventoryError(f"Enter a {label} between 1 and {maximum} characters.")
    return result


def scaled(value, unit, *, positive=False):
    if unit not in UNITS:
        raise InventoryError("Choose a supported unit.")
    try:
        amount = Decimal(str(value)) * UNITS[unit][1]
        result = amount * SCALE
        if not amount.is_finite() or amount < 0 or result > MAX_SCALED:
            raise InventoryError("Quantity must be finite, nonnegative, and no more than 1 billion base units.")
        if result != result.to_integral_value():
            raise InventoryError("Use a precision of 1 µL, 1 mg, or 1 whole item.")
        if UNITS[unit][0] == "each" and amount != amount.to_integral_value():
            raise InventoryError("Counted items must be whole numbers.")
        if positive and amount == 0:
            raise InventoryError("Enter a quantity greater than zero.")
        return int(result)
    except (InvalidOperation, TypeError, OverflowError):
        raise InventoryError("Enter a valid quantity.") from None


def quantity(value):
    return format(Decimal(value) / SCALE, ".3f").rstrip("0").rstrip(".") if value else "0"


def units_for(base):
    return [unit for unit, (family, _) in UNITS.items() if family == base]


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cabinets (
 id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
 location TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS items (
 id INTEGER PRIMARY KEY, cabinet_id TEXT NOT NULL REFERENCES cabinets(id),
 name TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', unit TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 0 AND 1000000000000),
 threshold INTEGER NOT NULL CHECK(threshold >= 0), target INTEGER NOT NULL CHECK(target > threshold),
 low_active INTEGER NOT NULL DEFAULT 0, cycle INTEGER NOT NULL DEFAULT 0,
 UNIQUE(cabinet_id, name, detail));
CREATE TABLE IF NOT EXISTS movements (
 id INTEGER PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
 item_id INTEGER NOT NULL REFERENCES items(id), kind TEXT NOT NULL,
 amount INTEGER NOT NULL CHECK(amount > 0), before_qty INTEGER NOT NULL,
 after_qty INTEGER NOT NULL CHECK(after_qty >= 0), actor TEXT NOT NULL,
 note TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recipients (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
 cabinet_id TEXT REFERENCES cabinets(id), active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS low_events (
 id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id),
 cycle INTEGER NOT NULL, quantity INTEGER NOT NULL, threshold INTEGER NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(item_id, cycle));
CREATE TABLE IF NOT EXISTS outbox (
 id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES low_events(id),
 recipient_id INTEGER NOT NULL REFERENCES recipients(id), status TEXT NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0, next_attempt TEXT NOT NULL,
 lease_until TEXT, claim_token TEXT, sent_at TEXT, last_error TEXT,
 UNIQUE(event_id, recipient_id));
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(status, next_attempt);
"""


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=20000")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def rows(self, sql, params=()):
        with self.connection() as db:
            return [dict(r) for r in db.execute(sql, params).fetchall()]

    def metadata(self, key, default=""):
        rows = self.rows("SELECT value FROM metadata WHERE key=?", (key,))
        return rows[0]["value"] if rows else default

    def seed_demo(self):
        with self.connection(write=True) as db:
            if db.execute("SELECT 1 FROM cabinets LIMIT 1").fetchone():
                return
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('demo','1')")
            db.executemany("INSERT INTO cabinets VALUES (?,?,?,?)", [
                ("cab-01", "Acid Storage 1", "Right side", "Acids"),
                ("cab-02", "Flammable 1", "Right side", "Flammable"),
                ("cab-03", "Acid Storage 2", "Left Side", "Acids"),
                ("cab-04", "Flammable 2", "Left Side", "Flammable"),
            ])
            for cabinet, name, detail, qty, threshold, target in [
                ("cab-01", "Tris hydrochloride", " ", 500, 50, 1000),
                ("cab-02", "Acetic Acid", "", 580, 100, 1000),
                ("cab-03", "Duratherm oil", "", 0.5, 0.1, 1),
                ("cab-04", "Sodium acetate", "", 500, 100, 1000),
            ]:
                cur = db.execute("INSERT INTO items(cabinet_id,name,detail,unit,quantity,threshold,target) VALUES (?,?,?,'mL',?,?,?)",
                                 (cabinet, name, detail, qty*SCALE, threshold*SCALE, target*SCALE))
                self._sync_low(db, cur.lastrowid)

    def cabinets(self):
        return self.rows("""SELECT c.*, COUNT(i.id) AS item_count,
          COALESCE(SUM(i.quantity <= i.threshold),0) AS low_count
          FROM cabinets c LEFT JOIN items i ON i.cabinet_id=c.id
          GROUP BY c.id ORDER BY c.name COLLATE NOCASE""")

    def add_cabinet(self, name, location, notes=""):
        name, location = clean(name, "cabinet name", 80), clean(location, "location", 150)
        if len(notes) > 500:
            raise InventoryError("Keep cabinet notes under 500 characters.")
        cabinet_id = uuid.uuid4().hex[:12]
        try:
            with self.connection(write=True) as db:
                db.execute("INSERT INTO cabinets VALUES (?,?,?,?)", (cabinet_id, name, location, notes.strip()))
        except sqlite3.IntegrityError:
            raise InventoryError("A cabinet with that name already exists.") from None
        return cabinet_id

    def items(self, cabinet_id=None):
        return self.rows("""SELECT i.*, c.name AS cabinet_name, c.location FROM items i
           JOIN cabinets c ON c.id=i.cabinet_id """ +
           ("WHERE i.cabinet_id=? " if cabinet_id else "") + "ORDER BY i.name COLLATE NOCASE",
           (cabinet_id,) if cabinet_id else ())

    def item(self, item_id):
        rows = self.rows("SELECT i.*, c.name AS cabinet_name FROM items i JOIN cabinets c ON c.id=i.cabinet_id WHERE i.id=?", (item_id,))
        if not rows:
            raise InventoryError("That item could not be found. Refresh the inventory.")
        return rows[0]

    def add_item(self, cabinet_id, name, detail, unit, initial, threshold, target, actor):
        name, actor = clean(name, "solution name", 100), clean(actor, "name", 100)
        if unit not in ("mL", "g", "each"):
            raise InventoryError("Choose mL, g, or each as the stock unit.")
        if len(detail) > 200:
            raise InventoryError("Keep the concentration / description under 200 characters.")
        qty, low, full = scaled(initial, unit), scaled(threshold, unit), scaled(target, unit, positive=True)
        if full <= low:
            raise InventoryError("The reference stock level must be greater than the low-stock threshold.")
        try:
            with self.connection(write=True) as db:
                cur = db.execute("INSERT INTO items(cabinet_id,name,detail,unit,quantity,threshold,target) VALUES (?,?,?,?,?,?,?)",
                                 (cabinet_id, name, detail.strip(), unit, qty, low, full))
                item_id = cur.lastrowid
                if qty:
                    db.execute("INSERT INTO movements(request_id,item_id,kind,amount,before_qty,after_qty,actor,note,created_at) VALUES (?,?,'add',?,0,?,?,?,?)",
                               (uuid.uuid4().hex, item_id, qty, qty, actor, "Opening stock", utcnow()))
                self._sync_low(db, item_id)
        except sqlite3.IntegrityError:
            raise InventoryError("Check the cabinet and use a unique solution name / description.") from None
        return item_id

    def update_threshold(self, item_id, threshold, target):
        with self.connection(write=True) as db:
            item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if not item:
                raise InventoryError("Item not found.")
            low, full = scaled(threshold, item["unit"]), scaled(target, item["unit"], positive=True)
            if full <= low:
                raise InventoryError("Reference stock must be greater than the low-stock threshold.")
            db.execute("UPDATE items SET threshold=?,target=? WHERE id=?", (low, full, item_id))
            self._sync_low(db, item_id)

    def record(self, item_id, kind, amount, unit, actor, note="", request_id=None):
        actor = clean(actor, "name", 100)
        if kind not in ("use", "add"):
            raise InventoryError("Choose Used or Added.")
        if len(note) > 500:
            raise InventoryError("Keep notes under 500 characters.")
        delta = scaled(amount, unit, positive=True)
        request_id = clean(request_id or uuid.uuid4().hex, "transaction reference", 100)
        with self.connection(write=True) as db:
            existing = db.execute("SELECT * FROM movements WHERE request_id=?", (request_id,)).fetchone()
            if existing:
                if (existing["item_id"], existing["kind"], existing["amount"], existing["actor"]) != (item_id, kind, delta, actor):
                    raise InventoryError("This transaction reference was already used. Refresh and try again.")
                return dict(existing)
            item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if not item or UNITS[unit][0] != item["unit"]:
                raise InventoryError("The quantity unit must match this item's stock unit.")
            before = item["quantity"]
            after = before + delta * (1 if kind == "add" else -1)
            if after < 0:
                raise InventoryError(f"Only {quantity(before)} {item['unit']} remains. Refresh and enter a smaller amount.")
            if after > MAX_SCALED:
                raise InventoryError("The resulting quantity is too large.")
            db.execute("UPDATE items SET quantity=? WHERE id=?", (after, item_id))
            cur = db.execute("""INSERT INTO movements(request_id,item_id,kind,amount,before_qty,after_qty,actor,note,created_at)
                               VALUES (?,?,?,?,?,?,?,?,?)""",
                             (request_id, item_id, kind, delta, before, after, actor, note.strip(), utcnow()))
            self._sync_low(db, item_id)
            return dict(db.execute("SELECT * FROM movements WHERE id=?", (cur.lastrowid,)).fetchone())

    def _sync_low(self, db, item_id):
        item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        low = item["quantity"] <= item["threshold"]
        if low and not item["low_active"]:
            cycle = item["cycle"] + 1
            db.execute("UPDATE items SET low_active=1,cycle=? WHERE id=?", (cycle, item_id))
            event_id = db.execute("INSERT INTO low_events(item_id,cycle,quantity,threshold,created_at) VALUES (?,?,?,?,?)",
                                  (item_id, cycle, item["quantity"], item["threshold"], utcnow())).lastrowid
            db.execute("""INSERT INTO outbox(event_id,recipient_id,next_attempt)
               SELECT ?,id,? FROM recipients WHERE active=1 AND (cabinet_id IS NULL OR cabinet_id=?)""",
                       (event_id, utcnow(), item["cabinet_id"]))
        elif not low and item["low_active"]:
            db.execute("UPDATE items SET low_active=0 WHERE id=?", (item_id,))
            db.execute("""UPDATE outbox SET status='cancelled' WHERE status='pending'
                          AND event_id IN (SELECT id FROM low_events WHERE item_id=?)""", (item_id,))

    def recipients(self):
        return self.rows("SELECT r.*,c.name AS cabinet_name FROM recipients r LEFT JOIN cabinets c ON c.id=r.cabinet_id ORDER BY r.name")

    def save_recipient(self, name, email, cabinet_id=None):
        name = clean(name, "recipient name", 100)
        email = email.strip().lower()
        if len(email) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}", email):
            raise InventoryError("Enter a valid email address.")
        with self.connection(write=True) as db:
            db.execute("""INSERT INTO recipients(name,email,cabinet_id) VALUES (?,?,?) ON CONFLICT(email)
                       DO UPDATE SET name=excluded.name,cabinet_id=excluded.cabinet_id,active=1""", (name, email, cabinet_id))
            recipient_id = db.execute("SELECT id FROM recipients WHERE email=?", (email,)).fetchone()["id"]
            # A new subscriber also receives currently active low-stock events.
            db.execute("""INSERT INTO outbox(event_id,recipient_id,next_attempt)
                SELECT e.id,?,? FROM low_events e JOIN items i ON i.id=e.item_id
                WHERE i.low_active=1 AND i.cycle=e.cycle AND (? IS NULL OR i.cabinet_id=?)
                ON CONFLICT(event_id,recipient_id) DO UPDATE SET status='pending',
                next_attempt=excluded.next_attempt,last_error=NULL WHERE outbox.status='cancelled'""",
                       (recipient_id, utcnow(), cabinet_id, cabinet_id))

    def disable_recipient(self, recipient_id):
        with self.connection(write=True) as db:
            db.execute("UPDATE recipients SET active=0 WHERE id=?", (recipient_id,))
            db.execute("UPDATE outbox SET status='cancelled' WHERE recipient_id=? AND status='pending'", (recipient_id,))

    def history(self, cabinet_id=None, limit=200):
        return self.rows("""SELECT m.*, i.name AS item_name,i.detail,i.unit,c.name AS cabinet_name
                 FROM movements m JOIN items i ON i.id=m.item_id JOIN cabinets c ON c.id=i.cabinet_id """ +
                 ("WHERE i.cabinet_id=? " if cabinet_id else "") + "ORDER BY m.id DESC LIMIT ?",
                 (cabinet_id, limit) if cabinet_id else (limit,))

    def alerts(self, limit=100):
        return self.rows("""SELECT o.*,r.email,i.name AS item_name,c.name AS cabinet_name,e.created_at
               FROM outbox o JOIN recipients r ON r.id=o.recipient_id
               JOIN low_events e ON e.id=o.event_id JOIN items i ON i.id=e.item_id
               JOIN cabinets c ON c.id=i.cabinet_id ORDER BY o.id DESC LIMIT ?""", (limit,))

    def claim_alert(self):
        now = utcnow()
        with self.connection(write=True) as db:
            db.execute("""UPDATE outbox SET status='pending',claim_token=NULL,lease_until=NULL
                          WHERE status='sending' AND lease_until < ?""", (now,))
            # Never send stale alerts after restock, unsubscribing, or scope changes.
            db.execute("""UPDATE outbox SET status='cancelled' WHERE status='pending' AND id IN (
                SELECT o.id FROM outbox o JOIN recipients r ON r.id=o.recipient_id
                JOIN low_events e ON e.id=o.event_id JOIN items i ON i.id=e.item_id
                WHERE r.active=0 OR i.low_active=0 OR e.cycle != i.cycle
                OR (r.cabinet_id IS NOT NULL AND r.cabinet_id != i.cabinet_id))""")
            row = db.execute("""SELECT o.id,r.email,r.name AS recipient_name,i.name AS item_name,i.detail,i.unit,
                  i.quantity AS current_quantity,i.threshold AS current_threshold,i.cabinet_id,
                  e.quantity AS event_quantity,e.created_at,c.name AS cabinet_name,c.location
                  FROM outbox o JOIN recipients r ON r.id=o.recipient_id
                  JOIN low_events e ON e.id=o.event_id JOIN items i ON i.id=e.item_id
                  JOIN cabinets c ON c.id=i.cabinet_id
                  WHERE o.status='pending' AND o.next_attempt <= ? ORDER BY o.id LIMIT 1""", (now,)).fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            lease = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(timespec="seconds")
            db.execute("UPDATE outbox SET status='sending',attempts=attempts+1,claim_token=?,lease_until=? WHERE id=?", (token, lease, row["id"]))
            return {**dict(row), "claim_token": token}

    def finish_alert(self, alert_id, claim_token, error=None):
        with self.connection(write=True) as db:
            row = db.execute("SELECT attempts FROM outbox WHERE id=? AND claim_token=? AND status='sending'", (alert_id, claim_token)).fetchone()
            if not row:
                return
            if error is None:
                db.execute("UPDATE outbox SET status='sent',sent_at=?,last_error=NULL,claim_token=NULL,lease_until=NULL WHERE id=?", (utcnow(), alert_id))
            else:
                delay = min(3600, 60 * 2 ** min(row["attempts"]-1, 6))
                retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec="seconds")
                db.execute("""UPDATE outbox SET status='pending',next_attempt=?,last_error=?,claim_token=NULL,lease_until=NULL WHERE id=?""",
                           (retry_at, str(error)[:300], alert_id))

    def backup(self):
        """SQLite's backup API includes committed WAL data consistently."""
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inventory.sqlite3"
            with self.connection() as source, closing(sqlite3.connect(path)) as destination:
                source.backup(destination)
            return path.read_bytes()
