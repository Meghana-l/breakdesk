"""
BreakDesk — Layer 2: SQL Matching & Reconciliation Engine
Reads internal + counterparty trades from SQLite,
runs field-level matching, scores each break, and
writes a structured reconciliation report.
"""

import sqlite3
import json
from datetime import datetime

DB_PATH = "breakdesk.db"

# ── Tolerance thresholds ───────────────────────────────────────────────────
# Breaks smaller than these are ignored (rounding, FX noise, etc.)
TOLERANCES = {
    "price":       0.001,   # 0.1% price tolerance
    "quantity":    0,        # zero tolerance on quantity
    "commission":  0.50,     # $0.50 commission tolerance
    "cash":        1.00,     # $1 nostro tolerance
}


def match_trades(conn):
    """
    Join internal and counterparty trades on trade_id.
    For each pair, check every material field and return breaks.
    """
    sql = """
    SELECT
        i.trade_id,
        i.asset_class,
        i.instrument,
        i.counterparty,
        i.price          AS i_price,
        c.price          AS c_price,
        i.quantity       AS i_qty,
        c.quantity       AS c_qty,
        i.commission     AS i_comm,
        c.commission     AS c_comm,
        i.cash_position  AS i_cash,
        c.cash_position  AS c_cash,
        i.settlement_status AS i_settle,
        c.settlement_status AS c_settle,
        i.wallet_address AS i_wallet,
        c.wallet_address AS c_wallet,
        i.notional       AS notional
    FROM internal_trades i
    JOIN counterparty_trades c ON i.trade_id = c.trade_id
    """
    rows = conn.execute(sql).fetchall()
    cols = [d[0] for d in conn.execute(sql).description]

    breaks = []
    for row in rows:
        r = dict(zip(cols, row))
        trade_breaks = check_fields(r)
        breaks.extend(trade_breaks)

    return breaks


def check_fields(r):
    """Check every field pair and return a list of break dicts."""
    found = []
    tid   = r["trade_id"]
    asset = r["asset_class"]
    inst  = r["instrument"]

    # 1. Price / rate
    price_delta = abs((r["i_price"] or 0) - (r["c_price"] or 0))
    price_pct   = price_delta / (r["i_price"] or 1)
    if price_pct > TOLERANCES["price"]:
        notional_impact = price_delta * (r["i_qty"] or 1)
        found.append(build_break(
            tid, asset, inst, r["counterparty"],
            break_type = "rate_discrepancy" if asset == "fx" else "price_mismatch",
            field       = "price",
            i_val       = r["i_price"],
            c_val       = r["c_price"],
            break_amount= round(notional_impact, 2),
        ))

    # 2. Quantity
    qty_delta = abs((r["i_qty"] or 0) - (r["c_qty"] or 0))
    if qty_delta > TOLERANCES["quantity"]:
        found.append(build_break(
            tid, asset, inst, r["counterparty"],
            break_type  = "quantity_break",
            field       = "quantity",
            i_val       = r["i_qty"],
            c_val       = r["c_qty"],
            break_amount= round(qty_delta * (r["i_price"] or 1), 2),
        ))

    # 3. Commission
    comm_delta = abs((r["i_comm"] or 0) - (r["c_comm"] or 0))
    if comm_delta > TOLERANCES["commission"]:
        found.append(build_break(
            tid, asset, inst, r["counterparty"],
            break_type  = "commission_error",
            field       = "commission",
            i_val       = r["i_comm"],
            c_val       = r["c_comm"],
            break_amount= round(comm_delta, 2),
        ))

    # 4. Cash / nostro
    cash_delta = abs((r["i_cash"] or 0) - (r["c_cash"] or 0))
    if cash_delta > TOLERANCES["cash"]:
        found.append(build_break(
            tid, asset, inst, r["counterparty"],
            break_type  = "nostro_break",
            field       = "cash_position",
            i_val       = r["i_cash"],
            c_val       = r["c_cash"],
            break_amount= round(cash_delta, 2),
        ))

    # 5. Settlement status
    if r["i_settle"] != r["c_settle"]:
        found.append(build_break(
            tid, asset, inst, r["counterparty"],
            break_type  = "settlement_fail",
            field       = "settlement_status",
            i_val       = r["i_settle"],
            c_val       = r["c_settle"],
            break_amount= round(r["notional"] or 0, 2),
        ))

    # 6. Wallet address (digital assets only)
    if asset == "digital" and r["i_wallet"] and r["c_wallet"]:
        if r["i_wallet"] != r["c_wallet"]:
            found.append(build_break(
                tid, asset, inst, r["counterparty"],
                break_type  = "wallet_mismatch",
                field       = "wallet_address",
                i_val       = r["i_wallet"],
                c_val       = r["c_wallet"],
                break_amount= round(r["notional"] or 0, 2),
            ))

    return found


def build_break(trade_id, asset_class, instrument, counterparty,
                break_type, field, i_val, c_val, break_amount):
    severity = (
        "critical" if break_amount > 500_000 else
        "high"     if break_amount > 100_000 else
        "medium"   if break_amount > 10_000  else
        "low"
    )
    return {
        "trade_id":          trade_id,
        "asset_class":       asset_class,
        "instrument":        instrument,
        "counterparty":      counterparty,
        "break_type":        break_type,
        "field":             field,
        "internal_value":    str(i_val),
        "counterparty_value":str(c_val),
        "break_amount":      break_amount,
        "severity":          severity,
        "status":            "open",
        "created_at":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def write_exceptions(conn, breaks):
    """Overwrite the exceptions table with freshly matched breaks."""
    conn.execute("DELETE FROM exceptions")
    sql = """
    INSERT INTO exceptions
        (trade_id, asset_class, instrument, break_type, severity,
         internal_value, counterparty_value, break_amount,
         ai_classification, ai_action, confidence, status, created_at)
    VALUES (?,?,?,?,?,?,?,?,NULL,NULL,NULL,?,?)
    """
    for b in breaks:
        conn.execute(sql, (
            b["trade_id"], b["asset_class"], b["instrument"],
            b["break_type"], b["severity"],
            b["internal_value"], b["counterparty_value"],
            b["break_amount"], b["status"], b["created_at"],
        ))
    conn.commit()


def summary_stats(conn, breaks):
    total_trades = conn.execute("SELECT COUNT(*) FROM internal_trades").fetchone()[0]
    unique_exc   = len({b["trade_id"] for b in breaks})
    matched      = total_trades - unique_exc
    match_rate   = round(matched / total_trades * 100, 1) if total_trades else 0

    by_severity  = {}
    by_asset     = {}
    by_type      = {}
    for b in breaks:
        by_severity[b["severity"]]   = by_severity.get(b["severity"], 0) + 1
        by_asset[b["asset_class"]]   = by_asset.get(b["asset_class"], 0) + 1
        by_type[b["break_type"]]     = by_type.get(b["break_type"], 0) + 1

    total_exposure = sum(b["break_amount"] for b in breaks)

    return {
        "total_trades":    total_trades,
        "matched":         matched,
        "exceptions":      len(breaks),
        "unique_exc_trades": unique_exc,
        "match_rate":      match_rate,
        "total_exposure":  round(total_exposure, 2),
        "by_severity":     by_severity,
        "by_asset":        by_asset,
        "by_type":         by_type,
    }


def run_matching():
    conn = sqlite3.connect(DB_PATH)

    print("Running SQL matching engine...")
    breaks = match_trades(conn)
    write_exceptions(conn, breaks)
    stats  = summary_stats(conn, breaks)
    conn.close()

    print(f"\n{'='*50}")
    print(f"  RECONCILIATION SUMMARY — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'='*50}")
    print(f"  Total trades:      {stats['total_trades']:>6}")
    print(f"  Matched (clean):   {stats['matched']:>6}  ({stats['match_rate']}%)")
    print(f"  Exceptions found:  {stats['exceptions']:>6}")
    print(f"  Total exposure:    ${stats['total_exposure']:>12,.2f}")
    print(f"\n  By severity:")
    for sev in ["critical","high","medium","low"]:
        n = stats["by_severity"].get(sev, 0)
        if n: print(f"    {sev:<10} {n:>3}")
    print(f"\n  By asset class:")
    for ac, n in sorted(stats["by_asset"].items()):
        print(f"    {ac:<12} {n:>3}")
    print(f"\n  By break type:")
    for bt, n in sorted(stats["by_type"].items()):
        print(f"    {bt:<22} {n:>3}")
    print(f"{'='*50}\n")

    return breaks, stats


if __name__ == "__main__":
    run_matching()
