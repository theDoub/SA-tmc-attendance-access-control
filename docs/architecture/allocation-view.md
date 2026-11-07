# Allocation View

**Owner:** Nguyen Tran Tuan Khai. *Template; content mirrors A1 §4.1 and Figure 5 (inspected as an image). No topology has been added.*

## Purpose
Show where software and data run (deployment), and who/what owns them.

## Elements (A1 Tables 19–22, Figure 5)

| Zone | Node | Software / data | Notes |
|---|---|---|---|
| Factory Gate Station (one per gate, at Binh Duong and Long An) | Kiosk Computer | Kiosk Application (validation, gate adapter, sync worker); Local Cache; Durable Queue | **This module's target** |
| | QR Scanner | Device | USB / serial / LAN (asterisk in Figure 5: unconfirmed) |
| | Turnstile Controller | Existing gate-control API | "Vendor API*": unspecified (OD-13) |
| | Backup Storage | Verified DB snapshots | SFTP / LAN |
| | Trusted Factory Time Service | NTP | |
| Central Server | Application Server | Backend (Modular Monolith, QR Issuance, APIs, Reporting, Payroll Integration) | Out of scope for A2 |
| | Database Server | TMC Database (attendance, users, audit) | Out of scope for A2 |
| User Device | Smartphone, computer | Mobile/web client; browser client | Out of scope for A2 |
| External | HR/Payroll | Existing integration API | Out of scope |

| Path | Interface (A1 Table 22) |
|---|---|
| Kiosk ↔ Application Server | HTTPS/API (WAN) |
| Kiosk ↔ Turnstile | Vendor API / LAN |
| Kiosk ↔ Backup storage | SFTP / LAN |
| Kiosk ↔ Time service | NTP / LAN |

## Relationship to Edge Gate Access Processing
The module corresponds to the Kiosk Application and its local artifacts. In this repository it runs as a Python process; packaging for a kiosk (service manager, installer) is **not specified** by A1 and not defined here.

## Open decisions
OD-10 (Edge authentication: mTLS vs HTTPS/API), OD-13 (vendor API). Deployment of the Python runtime to kiosks is undecided.
