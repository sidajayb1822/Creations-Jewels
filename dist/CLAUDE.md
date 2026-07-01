# EMR Reporter — Setup Checklist for Claude

This folder contains the EMR Reporter desktop app (`EMR Reporter.exe`).
When a user asks for help setting this up or reports that it isn't working,
check the following in order:

## 1. ODBC Driver for SQL Server
The app connects to a Microsoft SQL Server database and requires the ODBC driver.

Check if it's installed:
- Open **ODBC Data Sources** (search in Start menu, pick the 64-bit version)
- Click the **Drivers** tab
- Look for `ODBC Driver 17 for SQL Server` or `ODBC Driver 18 for SQL Server`

If missing, download and install from Microsoft:
https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server

## 2. Network access to SQL Server
The app connects to an Emperor ERP SQL Server instance.

Check:
- The PC is on the same network as the SQL Server (or VPN'd in)
- The SQL Server instance name and port are reachable
- Typical instance: `<server-ip>\EMRSQL` on port 1433

Test connectivity: open Command Prompt and run:
```
telnet <server-ip> 1433
```
If it hangs or errors, the firewall is blocking the connection.

## 3. First launch — configure connection
On first run, click **Settings** in the app and fill in:
- **Server**: IP or hostname of the Emperor SQL Server (e.g. `192.168.1.10\EMRSQL`)
- **Database**: Emperor database name (e.g. `EmrDaily`)
- **Auth**: SQL Server Authentication
- **Username / Password**: read-only SQL login credentials
- Click **Test Connection** to verify before saving

## 4. Verify the app works
- Click **Test Connection** in Settings — should show a green success message
- Drop an Emperor BOM Excel file (`.xlsx`) into the app
- The comparison table should populate with colour-coded rows
- The info bar at the top should show the order number and auto-detected company code

## What the app does
EMR Reporter parses Emperor Software ERP quotation Excel files and compares
the BOM pricing against master rates stored in the Emperor SQL Server database.
It highlights discrepancies using colour coding (green/yellow/red).

## Tech stack (for troubleshooting)
- Python 3.13 + PySide6 6.11 bundled via PyInstaller
- Connects to SQL Server via pyodbc
- Reads `.xlsx` files via openpyxl
- Config stored at `%USERPROFILE%\.emr_reporter\config.json`
