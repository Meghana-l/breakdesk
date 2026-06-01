"""
BreakDesk — Layer 1: Synthetic Trade Data Generator
Generates realistic internal + counterparty trade records across
equities, FX, futures, and digital assets, with intentional breaks.
"""

import sqlite3
import random
import math
from datetime import datetime, timedelta

DB_PATH = "breakdesk.db"

# ── Master reference data ──────────────────────────────────────────────────
EQUITIES = [
    ("AAPL", 189.50), ("MSFT", 415.20), ("NVDA", 875.30),
    ("GS",   438.10), ("JPM",  198.40), ("BAC",   38.90),
]
FX_PAIRS = [
    ("EUR/USD", 1.0812), ("GBP/USD", 1.2740), ("USD/JPY", 156.80),
    ("AUD/USD", 0.6530), ("USD/CHF", 0.9015),
]
FUTURES = [
    ("ES",  5280.00),   # S&P 500 E-mini, multiplier 50
    ("NQ",  18450.00),  # Nasdaq E-mini,  multiplier 20
    ("CL",    82.40),   # Crude oil,       multiplier 1000
    ("GC",  2340.00),   # Gold,            multiplier 100
]
DIGITAL = [
    ("BTC/USD", 67500.00), ("ETH/USD", 3420.00),
    ("SOL/USD",   145.00), ("XRP/USD",    0.52),
]
COUNTERPARTIES = ["GS Prime", "JPM Clearing", "Citi Sec", "Morgan Sec", "Barclays"]

# ── Break types & their injection probabilities ───────────────────────────
# Each break type: (label, probability of occurring, how to mutate the trade)
BREAK_TYPES = {
    "price_mismatch":   0.06,   # counterparty price differs
    "quantity_break":   0.04,   # counterparty quantity differs
    "settlement_fail":  0.03,   # settlement status mismatch
    "commission_error": 0.03,   # commission overcharged
    "nostro_break":     0.02,   # cash position mismatch
    "wallet_mismatch":  0.05,   # digital asset wallet differs (DA only)
    "rate_discrepancy": 0.05,   # FX rate differs at settlement
}

# ── Helpers ───────────────────────────────────────────────────────────────
def rand_trade_id():
    return f"TRD-{random.randint(1000, 9999)}"

def rand_timestamp(base_date, window_hours=8):
    offset = timedelta(seconds=random.randint(0, window_hours * 3600))
    return (base_date + offset).strftime("%Y-%m-%d %H:%M:%S")

def inject_break(asset_class, internal):
    """
    Randomly decide whether to inject a break into the counterparty record.
    Returns (counterparty_record, break_type or None).
    """
    cp = dict(internal)  # start as a copy

    # wallet_mismatch only applies to digital assets
    eligible = {k: v for k, v in BREAK_TYPES.items()
                if not (k == "wallet_mismatch" and asset_class != "digital")
                and not (k == "rate_discrepancy" and asset_class != "fx")}

    for break_type, prob in eligible.items():
        if random.random() < prob:
            if break_type == "price_mismatch":
                delta_pct = random.uniform(0.005, 0.025) * random.choice([-1, 1])
                cp["price"] = round(internal["price"] * (1 + delta_pct), 4)
            elif break_type == "quantity_break":
                delta = random.randint(1, max(1, int(internal["quantity"] * 0.05)))
                cp["quantity"] = internal["quantity"] - delta
            elif break_type == "settlement_fail":
                cp["settlement_status"] = "FAIL"
            elif break_type == "commission_error":
                cp["commission"] = round(internal["commission"] * random.uniform(1.3, 1.8), 2)
            elif break_type == "nostro_break":
                cp["cash_position"] = round(internal["cash_position"] * random.uniform(0.85, 0.97), 2)
            elif break_type == "wallet_mismatch":
                w = internal.get("wallet_address", "0x000000000000")
                cp["wallet_address"] = w[:-3] + "".join(
                    random.choices("0123456789ABCDEF", k=3))
            elif break_type == "rate_discrepancy":
                cp["price"] = round(internal["price"] * random.uniform(0.9985, 0.9998), 5)
            return cp, break_type

    return cp, None  # clean match


def generate_equity_trade(trade_id, ts, base_date):
    ticker, base_price = random.choice(EQUITIES)
    price = round(base_price * random.uniform(0.995, 1.005), 2)
    qty   = random.randint(100, 5000)
    notional = round(price * qty, 2)
    commission = round(notional * random.uniform(0.0003, 0.0008), 2)
    internal = {
        "trade_id": trade_id, "asset_class": "equity",
        "instrument": ticker, "price": price,
        "quantity": qty, "notional": notional,
        "commission": commission, "cash_position": notional,
        "settlement_status": "PENDING",
        "settlement_date": (base_date + timedelta(days=2)).strftime("%Y-%m-%d"),
        "counterparty": random.choice(COUNTERPARTIES),
        "wallet_address": None, "timestamp": ts,
    }
    return internal


def generate_fx_trade(trade_id, ts, base_date):
    pair, rate = random.choice(FX_PAIRS)
    notional_usd = random.randint(100_000, 5_000_000)
    price = round(rate * random.uniform(0.9995, 1.0005), 5)
    qty   = notional_usd
    commission = round(notional_usd * 0.00002, 2)
    internal = {
        "trade_id": trade_id, "asset_class": "fx",
        "instrument": pair, "price": price,
        "quantity": qty, "notional": round(notional_usd * price, 2),
        "commission": commission, "cash_position": round(notional_usd * price, 2),
        "settlement_status": "PENDING",
        "settlement_date": (base_date + timedelta(days=2)).strftime("%Y-%m-%d"),
        "counterparty": random.choice(COUNTERPARTIES),
        "wallet_address": None, "timestamp": ts,
    }
    return internal


def generate_futures_trade(trade_id, ts, base_date):
    symbol, base_price = random.choice(FUTURES)
    price = round(base_price * random.uniform(0.998, 1.002), 2)
    qty   = random.randint(1, 200)
    notional = round(price * qty, 2)
    commission = round(qty * random.uniform(1.5, 4.0), 2)
    internal = {
        "trade_id": trade_id, "asset_class": "futures",
        "instrument": symbol, "price": price,
        "quantity": qty, "notional": notional,
        "commission": commission, "cash_position": notional,
        "settlement_status": "PENDING",
        "settlement_date": (base_date + timedelta(days=1)).strftime("%Y-%m-%d"),
        "counterparty": random.choice(COUNTERPARTIES),
        "wallet_address": None, "timestamp": ts,
    }
    return internal


def generate_digital_trade(trade_id, ts, base_date):
    pair, base_price = random.choice(DIGITAL)
    price = round(base_price * random.uniform(0.997, 1.003), 2)
    qty   = round(random.uniform(0.01, 10.0), 4)
    notional = round(price * qty, 2)
    commission = round(notional * random.uniform(0.001, 0.003), 2)
    wallet = "0x" + "".join(random.choices("0123456789ABCDEF", k=10))
    internal = {
        "trade_id": trade_id, "asset_class": "digital",
        "instrument": pair, "price": price,
        "quantity": qty, "notional": notional,
        "commission": commission, "cash_position": notional,
        "settlement_status": "PENDING",
        "settlement_date": base_date.strftime("%Y-%m-%d"),
        "counterparty": random.choice(COUNTERPARTIES),
        "wallet_address": wallet, "timestamp": ts,
    }
    return internal


GENERATORS = {
    "equity":  generate_equity_trade,
    "fx":      generate_fx_trade,
    "futures": generate_futures_trade,
    "digital": generate_digital_trade,
}

# ── DB setup ──────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS internal_trades (
    trade_id TEXT, asset_class TEXT, instrument TEXT,
    price REAL, quantity REAL, notional REAL, commission REAL,
    cash_position REAL, settlement_status TEXT, settlement_date TEXT,
    counterparty TEXT, wallet_address TEXT, timestamp TEXT
);
CREATE TABLE IF NOT EXISTS counterparty_trades (
    trade_id TEXT, asset_class TEXT, instrument TEXT,
    price REAL, quantity REAL, notional REAL, commission REAL,
    cash_position REAL, settlement_status TEXT, settlement_date TEXT,
    counterparty TEXT, wallet_address TEXT, timestamp TEXT
);
CREATE TABLE IF NOT EXISTS exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT, asset_class TEXT, instrument TEXT,
    break_type TEXT, severity TEXT,
    internal_value TEXT, counterparty_value TEXT,
    break_amount REAL, ai_classification TEXT, ai_action TEXT,
    confidence INTEGER, status TEXT DEFAULT 'open',
    created_at TEXT
);
"""

def setup_db(conn):
    conn.executescript(SCHEMA)
    conn.execute("DELETE FROM internal_trades")
    conn.execute("DELETE FROM counterparty_trades")
    conn.execute("DELETE FROM exceptions")
    conn.commit()


# ── Main generation loop ──────────────────────────────────────────────────
def generate(n_trades=200, seed=42):
    random.seed(seed)
    base_date = datetime(2026, 5, 22, 9, 0, 0)

    conn = sqlite3.connect(DB_PATH)
    setup_db(conn)

    asset_classes = ["equity", "equity", "equity", "fx", "fx", "futures", "futures", "digital"]
    internal_rows = []
    cp_rows = []
    exception_rows = []
    seen_ids = set()

    for _ in range(n_trades):
        # unique trade ID
        trade_id = rand_trade_id()
        while trade_id in seen_ids:
            trade_id = rand_trade_id()
        seen_ids.add(trade_id)

        asset = random.choice(asset_classes)
        ts = rand_timestamp(base_date)
        gen = GENERATORS[asset]
        internal = gen(trade_id, ts, base_date)
        cp, break_type = inject_break(asset, internal)

        internal_rows.append(tuple(internal.values()))
        cp_rows.append(tuple(cp.values()))

        if break_type:
            # compute break amount (notional difference)
            break_amount = 0.0
            internal_val = ""
            cp_val = ""

            if break_type == "price_mismatch" or break_type == "rate_discrepancy":
                break_amount = abs(internal["price"] - cp["price"]) * internal["quantity"]
                internal_val = str(internal["price"])
                cp_val = str(cp["price"])
            elif break_type == "quantity_break":
                break_amount = abs(internal["quantity"] - cp["quantity"]) * internal["price"]
                internal_val = str(internal["quantity"])
                cp_val = str(cp["quantity"])
            elif break_type == "commission_error":
                break_amount = abs(internal["commission"] - cp["commission"])
                internal_val = str(internal["commission"])
                cp_val = str(cp["commission"])
            elif break_type == "nostro_break":
                break_amount = abs(internal["cash_position"] - cp["cash_position"])
                internal_val = str(internal["cash_position"])
                cp_val = str(cp["cash_position"])
            elif break_type == "settlement_fail":
                break_amount = internal["notional"]
                internal_val = "PENDING"
                cp_val = "FAIL"
            elif break_type == "wallet_mismatch":
                break_amount = internal["notional"]
                internal_val = internal.get("wallet_address", "")
                cp_val = cp.get("wallet_address", "")

            severity = (
                "critical" if break_amount > 500_000 else
                "high"     if break_amount > 100_000 else
                "medium"   if break_amount > 10_000  else
                "low"
            )

            exception_rows.append((
                trade_id, asset, internal["instrument"],
                break_type, severity,
                internal_val, cp_val,
                round(break_amount, 2),
                None, None, None, "open",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))

    cols = "(trade_id,asset_class,instrument,price,quantity,notional,commission,cash_position,settlement_status,settlement_date,counterparty,wallet_address,timestamp)"
    conn.executemany(f"INSERT INTO internal_trades {cols} VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", internal_rows)
    conn.executemany(f"INSERT INTO counterparty_trades {cols} VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", cp_rows)

    exc_cols = "(trade_id,asset_class,instrument,break_type,severity,internal_value,counterparty_value,break_amount,ai_classification,ai_action,confidence,status,created_at)"
    conn.executemany(f"INSERT INTO exceptions {exc_cols} VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", exception_rows)
    conn.commit()

    total = len(internal_rows)
    exc   = len(exception_rows)
    match_rate = round((total - exc) / total * 100, 1)

    print(f"✓ Generated {total} trades → {exc} exceptions ({match_rate}% match rate)")
    print(f"  Breakdown: {sum(1 for r in exception_rows if r[4]=='critical')} critical, "
          f"{sum(1 for r in exception_rows if r[4]=='high')} high, "
          f"{sum(1 for r in exception_rows if r[4]=='medium')} medium, "
          f"{sum(1 for r in exception_rows if r[4]=='low')} low")
    conn.close()
    return exc


if __name__ == "__main__":
    generate(n_trades=200)
