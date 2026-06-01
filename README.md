# BreakDesk — Trade Reconciliation & Exception Management

**Live demo → [meghana-l.github.io/breakdesk](https://meghana-l.github.io/breakdesk)**

A working trade reconciliation and exception management tool built to mirror what an ops team at a global hedge fund deals with every day — multi-asset trade matching, break detection, exception triage, and reporting.

---

## What it does

BreakDesk runs a full reconciliation pipeline on every page load:

1. **Fetches real market prices** from Polygon.io (equities, FX, crypto)
2. **Generates synthetic trade positions** using those live prices across equities, FX, futures, and digital assets
3. **Runs a field-level matching engine** — compares internal bookings against counterparty confirmations on price, quantity, commission, cash position, settlement status, and wallet addresses
4. **Flags and classifies exceptions** — breaks are assigned severity (critical/high/medium/low), root cause, and recommended ops action
5. **Renders a live dashboard** — filterable exception queue, break detail panel, exposure stats, and break-type breakdown

Because it uses today's real closing prices, exception amounts and exposures change daily.

---

## Architecture

```
Polygon.io REST API      real closing prices (equities, FX, crypto)
        ↓
Trade Generator          synthetic positions built on live prices
        ↓
Matching Engine          field-level comparison with tolerance thresholds
        ↓
Exception Classifier     rule-based ops logic (browser) / Claude API (local)
        ↓
Dashboard                live, runs entirely in browser — no server needed
```

### Break types detected

| Break type | Detection logic |
|---|---|
| Price mismatch | > 0.1% delta between internal and counterparty price |
| Rate discrepancy | FX settlement rate differs |
| Quantity break | Unit count mismatch (zero tolerance) |
| Commission error | Invoiced commission > $0.50 over internal calc |
| Nostro break | Cash position delta > $1.00 |
| Settlement fail | Counterparty status = FAIL vs internal PENDING |
| Wallet mismatch | Digital asset wallet address differs |

---

## Running the full AI pipeline locally

The live site uses rule-based classification. For full Claude AI classification:

```bash
pip install anthropic

python3 generate_trades.py      # generates 200 synthetic trades into SQLite
python3 match_engine.py         # SQL matching, flags breaks

export ANTHROPIC_API_KEY=your_key_here
python3 ai_classifier.py        # Claude classifies each exception
```

Claude returns root cause, recommended action, confidence score, and escalation flag per exception — all written back to `breakdesk.db`.

---

## Setting up live prices

1. Sign up free at [polygon.io](https://polygon.io)
2. Copy your API key
3. Open `index.html`, find:
   ```js
   const POLYGON_KEY = 'YOUR_POLYGON_API_KEY';
   ```
4. Replace with your key and save

Without a key the dashboard falls back to realistic static prices and still runs the full pipeline.

---

## File structure

```
breakdesk/
├── index.html            ← Live dashboard (GitHub Pages)
├── generate_trades.py    ← Layer 1: synthetic trade generator
├── match_engine.py       ← Layer 2: SQL matching engine
├── ai_classifier.py      ← Layer 3: Claude API classifier
├── breakdesk.db          ← SQLite DB (generated locally)
└── README.md
```

---

## Built by

**Meghana Lakshminarayana Swamy**
MS Business Analytics · University of New Haven · GPA 3.81 · May 2026
ECBA Certified · [meghana-l.github.io](https://meghana-l.github.io) · meghana.drlnswamy@gmail.com
