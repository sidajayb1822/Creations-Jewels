# EMR Reporter

Desktop analytics tool for **Emperor Software ERP** — jewellery manufacturing edition.

Parses Emperor quotation Excel files, queries master pricing from the Emperor SQL Server database, and shows a colour-coded comparison table flagging discrepancies before they reach the client.

---

## Download the App (Windows)

> **No Python installation needed** — the app ships as a single `.exe`.

1. Go to the [dist/](dist/) folder in this repository
2. Download **`EMR Reporter.exe`**
3. Double-click to run

Or clone the repo and grab it:

```
git clone https://github.com/sidajayb1822/Creations-Jewels.git
cd "Creations-Jewels/dist"
# Open "EMR Reporter.exe"
```

---

## Features

| Tab | What it does |
|-----|-------------|
| **BOM Comparison** | Drop an Emperor quotation or sales-order `.xlsx` — compares every metal, stone, and labour line against your master rates and highlights discrepancies in green / amber / red. **Multi-design files** (a sales order with several designs) show **one sub-tab per design**. **Double-click any line** to see exactly how its master value was calculated and edit the formula. **Export** writes every design into one Excel workbook (a sheet per design). |
| **Customer Rate Card** | Browse all material and labour rates on file for any customer in the Emperor database |
| **Order Pipeline** | Live view of open sales orders and quotations with delivery status (Open / Overdue / Delivered) |
| **Formulas** | View and edit the pricing formulas the comparison uses — per component, with per-customer overrides. Two editors (guided step builder + editable expression). Define **custom variables** that read any Emperor table, so new masters can be priced without a code change. See [Pricing Formulas](#pricing-formulas). |

---

## First-Launch Setup

### 1. Install the ODBC Driver for SQL Server

The app connects to Emperor's SQL Server backend using ODBC. You need **ODBC Driver 17 or 18 for SQL Server** installed on the Windows PC.

**Check if it's already installed:**
- Open **ODBC Data Sources** (search in Start → pick the 64-bit version)
- Click the **Drivers** tab
- Look for `ODBC Driver 17 for SQL Server` or `ODBC Driver 18 for SQL Server`

**If missing, download from Microsoft:**
https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server

Choose the Windows x64 installer and run it. No reboot required.

---

### 2. Make sure the PC can reach the SQL Server

The PC running EMR Reporter must be on the **same network** as the Emperor SQL Server (or connected via VPN).

Test connectivity — open Command Prompt and run:

```
telnet <server-ip> 1433
```

- **Blank screen** = connected ✓
- **Connection refused / timeout** = firewall is blocking port 1433 — ask your IT admin to open it

Common Emperor server addresses:
- `192.168.x.x\EMRSQL` (local network)
- `.\EMRSQL` (same machine — development only)

---

### 3. Configure the connection inside the app

1. Launch **EMR Reporter.exe**
2. Click **⚙ Database Settings** in the left sidebar
3. Fill in:

| Field | Value |
|-------|-------|
| **Server** | IP address or hostname of the Emperor SQL Server, e.g. `192.168.1.10\EMRSQL` |
| **Database** | Emperor database name — use the **Browse…** button to pick from a list |
| **Auth type** | SQL Server Authentication (recommended) |
| **Username** | SQL Server login — ask your Emperor admin for a read-only account |
| **Password** | SQL Server login password |
| **Timeout** | 10 seconds is fine for local networks; raise to 30 for VPN |
| **Company code** | *(optional)* Emperor customer code for rate lookups, e.g. `OM-LGD`. Leave blank to auto-detect from the BOM's customer name |
| **Metal loss %** | Wastage uplift on the fine metal rate (default 10%). Used as a fallback when Emperor has no loss value configured for the customer |

4. Click **Test Connection** — you should see a green success message
5. Click **OK** to save

Settings are stored at `%USERPROFILE%\.emr_reporter\config.json` (never committed to git — each machine has its own). Pricing formulas live alongside it in `formulas.json` and `custom_variables.json`, seeded automatically on first run.

---

### 4. Verify it's working

- DB status at the bottom of the sidebar should show **● EmrDaily** (green)
- Switch to **Customer Rate Card**, pick a customer, click **Load Rate Card** — rates should populate
- Switch to **Order Pipeline** — open orders should load automatically
- On **BOM Comparison**, drop a `.xlsx` Emperor quotation file — comparison table should fill in

---

## Pricing Formulas

The master value for every line comes from an **editable formula**, not hard-coded logic. You can see and change them in the **Formulas** tab — no coding, and the Emperor database is never modified (all formulas are stored locally).

### How a line is priced

Each line resolves the formula for its **component**, with an optional **per-customer override**:

| Component | Default formula |
|-----------|-----------------|
| Metal | `(lme / 31.1035) × RmMst.RmPurityRt × (1 + loss% / 100) × weight` |
| Diamond / Colour stone | `RmRt rate per carat × carat weight` |
| Labour (per piece) | `LabRt rate × qty` |
| Labour (per gram) | `LabRt rate × total metal weight` |
| CDW | `LabRt rate × total diamond weight` |
| Finding | `LabRt rate` (direct) |

The customer multiplier (`CustMst.CmMulBy`) is applied to the grand total.

### Viewing & editing

- **Double-click any comparison line** → see the step-by-step calculation (which table/column each value came from) and an **Edit formula** button.
- The editor has two interchangeable views over one formula:
  - **Guided builder** — pick a variable from a dropdown (grouped by BOM line / totals / database tables / settings / constants) or type a number, choose an operator, add/remove steps.
  - **Editable expression** — the raw formula text with a Validate button and a variable legend. Supports `+ - * / **` and `min`, `max`, `round`, `abs` (e.g. `max(metal_weight * LabRt_rate, 2.0)` for a minimum charge).
- Save as the **default** (all customers) or as a **per-customer override**.

### Custom variables (use any table)

If Emperor adds a new master/table, you don't need a new build. In the Formulas tab → **New variable**, pick a **table + value column + match keys** from dropdowns (populated live from the database), give it a name, and it becomes selectable in every formula. Table/column names are strictly validated, so these lookups are injection-safe.

### Where formulas are stored

Locally in `%USERPROFILE%\.emr_reporter\` — `formulas.json` and `custom_variables.json`. Built-in defaults are seeded on first run and reproduce Emperor's standard costing. **Nothing is written to the Emperor SQL Server.**

---

## Server-Side Setup (Emperor SQL Server)

> This section is for the person administering the Emperor SQL Server.

### Create a read-only SQL login for EMR Reporter

EMR Reporter only **reads** from the database — it never writes. Create a dedicated read-only login:

```sql
-- Run in SQL Server Management Studio (SSMS) connected as SA or sysadmin

-- 1. Create the login
CREATE LOGIN emr_reporter WITH PASSWORD = 'ChooseAStrongPassword!';

-- 2. Map it to the Emperor database
USE EmrDaily;
CREATE USER emr_reporter FOR LOGIN emr_reporter;

-- 3. Grant read-only access
ALTER ROLE db_datareader ADD MEMBER emr_reporter;
```

Then give users this credential to enter in Settings.

---

### Enable SQL Server Authentication

Emperor typically installs SQL Server in **Mixed Mode** (Windows + SQL auth), so this may already be enabled. To verify:

1. Open **SSMS**, connect to the instance
2. Right-click the server → **Properties** → **Security**
3. Confirm **SQL Server and Windows Authentication mode** is selected
4. If you change it, restart the SQL Server service

---

### Open port 1433 on the server firewall

If client PCs are on a different subnet or connecting over VPN:

**Windows Firewall (on the SQL Server machine):**

```
Windows Defender Firewall → Advanced Settings
→ Inbound Rules → New Rule
→ Port → TCP → 1433
→ Allow the connection → Name: "SQL Server 1433"
```

**SQL Server Browser service** (needed for named instances like `.\EMRSQL`):

```
Services → SQL Server Browser → set to Automatic → Start
```

Also open UDP 1434 for browser service discovery:
```
Inbound Rule → Port → UDP → 1434 → Allow
```

---

### Required Emperor tables (read access)

EMR Reporter queries these tables — all are standard Emperor tables, no custom schema changes required:

| Table | Used for |
|-------|----------|
| `RmMst` | Raw material / stone descriptions **and metal purity** (`RmPurityRt`) |
| `RmRt` | Material and stone rate lookup (incl. `CRP` purity factor) |
| `LabRt` | Labour rate lookup |
| `CustMst` | Customer list, company codes, multiplier (`CmMulBy`), loss lookup |
| `LossMst` | Metal loss % (when configured per customer) |
| `OrdMst` | Order pipeline |

Custom variables (Formulas tab) may read **any** additional table you point them at — read-only.

---

## Running from Source (Developers)

Requirements: **Python 3.11+**, Windows

```bash
# 1. Clone
git clone https://github.com/sidajayb1822/Creations-Jewels.git
cd "Creations-Jewels"

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
python main.py
```

### Building the EXE yourself

```bash
python -m PyInstaller "EMR Reporter.spec" --noconfirm
# Output: dist/EMR Reporter.exe
```

### Dependencies

```
PySide6       — UI framework
pyodbc        — SQL Server connectivity
openpyxl      — Emperor Excel file parsing
PyInstaller   — EXE packaging (dev only)
```

---

## Project Structure

```
emr-reporter/
├── main.py                          # Entry point
├── requirements.txt
├── EMR Reporter.spec                # PyInstaller build config
├── dist/
│   └── EMR Reporter.exe             # Distributable (Windows x64)
└── app/
    ├── models/bom.py                # BOM data model (multi-design aware)
    ├── core/
    │   ├── excel_parser.py          # Parses Emperor .xlsx (single + multi-design workbooks)
    │   ├── db.py                    # SQL Server connection + queries (locked, timeout-bounded)
    │   ├── comparator.py            # Formula-driven BOM vs master comparison
    │   ├── formula.py               # Formula model + safe evaluator + trace
    │   ├── formula_store.py         # Local formula storage (seeded defaults, CRUD)
    │   └── custom_var.py            # User-defined DB-lookup variables
    └── ui/
        ├── main_window.py           # Main window with sidebar navigation
        ├── settings_dialog.py       # DB connection + costing settings
        ├── bom_compare/             # BOM Comparison tab (per-design sub-tabs, line detail)
        ├── customer_rates/          # Customer Rate Card tab
        ├── order_pipeline/          # Order Pipeline tab
        └── formulas/                # Formulas tab: CRUD + dual editor + custom-variable dialog
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `● Not connected` in sidebar | Open Settings and click Test Connection — check server address and credentials |
| `Browse…` button shows no databases | The server address or credentials are wrong — test with SSMS first |
| Order Pipeline loads empty | Check that `OmTc` filter is set to **All** and the login has `db_datareader` on the correct database |
| BOM Comparison shows N/A for all lines | Company code not found — the customer name in the Excel file must partially match `CustMst.CmName` |
| App doesn't launch | Check that ODBC Driver 17/18 is installed (Step 1 above) |
| Slow startup of the EXE (~15-30 sec) | Normal for first launch — the EXE extracts itself to a temp folder. Subsequent launches from the same session are instant. |

---

## Support

Issues and feature requests: open a GitHub Issue on this repository.
