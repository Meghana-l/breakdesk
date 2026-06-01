"""
BreakDesk — Layer 3: AI Exception Classification Engine
For each unclassified exception in the DB, calls Claude to:
  - Classify the root cause
  - Recommend an action
  - Score confidence
  - Suggest priority escalation path
"""

import sqlite3
import json
import time
import anthropic

DB_PATH  = "breakdesk.db"
MODEL    = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are an expert trade operations analyst at a global hedge fund.
You receive trade exception details from a reconciliation system and must classify each one.

Respond ONLY with a valid JSON object — no preamble, no markdown, no extra text.

Required fields:
{
  "root_cause": "one sentence — the likely technical or operational reason for this break",
  "recommended_action": "one sentence — what the ops team should do right now",
  "escalate": true/false,
  "confidence": integer 60-99,
  "tags": ["TAG1", "TAG2"]   // 2-4 uppercase tags, e.g. PRICE_FEED, PARTIAL_FILL, T+2
}

Guidelines:
- Be specific to the asset class and break type
- confidence above 90 = clear-cut case with high certainty
- confidence 75-89 = probable cause but verify
- confidence 60-74 = uncertain, needs human investigation
- escalate=true only for critical severity or wallet/settlement breaks
- tags should be terse operational labels (max 4 chars preferred)
"""

def build_user_prompt(exc):
    return f"""Trade exception details:

Trade ID:        {exc['trade_id']}
Asset class:     {exc['asset_class']}
Instrument:      {exc['instrument']}
Break type:      {exc['break_type']}
Severity:        {exc['severity']}
Internal value:  {exc['internal_value']}
Counterparty val:{exc['counterparty_value']}
Break amount:    ${exc['break_amount']:,.2f}

Classify this exception and return the JSON response."""


def classify_exception(client, exc):
    """Call Claude and parse the JSON response."""
    try:
        resp = client.messages.create(
            model      = MODEL,
            max_tokens = 300,
            system     = SYSTEM_PROMPT,
            messages   = [{"role": "user", "content": build_user_prompt(exc)}],
        )
        raw = resp.content[0].text.strip()
        # Strip markdown fences if model adds them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)

        # Validate required keys
        for key in ["root_cause", "recommended_action", "escalate", "confidence", "tags"]:
            if key not in result:
                raise ValueError(f"Missing key: {key}")

        return result

    except Exception as e:
        # Graceful fallback — never block the pipeline
        return {
            "root_cause":         "Classification failed — manual review required",
            "recommended_action": "Escalate to senior ops analyst for manual triage",
            "escalate":           True,
            "confidence":         60,
            "tags":               ["MANUAL", "REVIEW"],
            "_error":             str(e),
        }


def run_ai_classification(limit=None):
    """
    Fetch all unclassified exceptions, call Claude for each,
    and write results back to the DB.
    """
    conn   = sqlite3.connect(DB_PATH)
    client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY from env

    sql = "SELECT id, trade_id, asset_class, instrument, break_type, severity, internal_value, counterparty_value, break_amount FROM exceptions WHERE ai_classification IS NULL"
    if limit:
        sql += f" LIMIT {limit}"

    rows = conn.execute(sql).fetchall()
    cols = ["id","trade_id","asset_class","instrument","break_type","severity","internal_value","counterparty_value","break_amount"]
    exceptions = [dict(zip(cols, r)) for r in rows]

    if not exceptions:
        print("No unclassified exceptions found.")
        conn.close()
        return []

    print(f"Classifying {len(exceptions)} exceptions with Claude...\n")
    results = []

    for i, exc in enumerate(exceptions, 1):
        print(f"  [{i:>2}/{len(exceptions)}] {exc['trade_id']} | {exc['break_type']:<22} | ${exc['break_amount']:>12,.2f} | {exc['severity']}", end=" ... ", flush=True)

        result = classify_exception(client, exc)

        # Format for storage
        ai_classification = result["root_cause"]
        ai_action         = result["recommended_action"]
        confidence        = result["confidence"]
        tags_str          = ",".join(result.get("tags", []))

        # Append tags to action for display
        ai_action_full = ai_action
        if tags_str:
            ai_action_full = f"[{tags_str}] {ai_action}"

        conn.execute("""
            UPDATE exceptions
            SET ai_classification = ?,
                ai_action         = ?,
                confidence        = ?
            WHERE id = ?
        """, (ai_classification, ai_action_full, confidence, exc["id"]))
        conn.commit()

        print(f"confidence={confidence}%")
        results.append({**exc, **result})

        # Respect rate limits — small delay between calls
        if i < len(exceptions):
            time.sleep(0.3)

    conn.close()
    print(f"\n✓ AI classification complete — {len(results)} exceptions classified")
    return results


def print_classified_report():
    """Print a final human-readable report of all classified exceptions."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT trade_id, asset_class, instrument, break_type, severity,
               break_amount, confidence, ai_classification, ai_action, status
        FROM exceptions
        ORDER BY
          CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
          break_amount DESC
    """).fetchall()
    conn.close()

    print(f"\n{'='*80}")
    print(f"  BREAKDESK — AI-CLASSIFIED EXCEPTION REPORT")
    print(f"{'='*80}")
    for r in rows:
        tid, ac, inst, bt, sev, amt, conf, cls, action, status = r
        print(f"\n  {'🔴' if sev=='critical' else '🟠' if sev=='high' else '🟡' if sev=='medium' else '🟢'} "
              f"{tid} | {inst:<10} | {bt:<22} | ${amt:>12,.2f} | {sev.upper()}")
        print(f"     Root cause:  {cls}")
        print(f"     Action:      {action}")
        print(f"     Confidence:  {conf}% | Status: {status}")
    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    run_ai_classification()
    print_classified_report()
