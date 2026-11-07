# Architecture Overview

**Owner:** Nguyen Tran Tuan Khai. **Baseline:** `Assignment1_Group6.pdf` (A1). Details not in A1 are marked *pending*.

## Purpose
Orient the team: what is being built, which A1 architecture it implements, and how the three view documents relate.

## Selected architecture (A1 ADR-001..004)
- Distributed **Edge–Hub** topology; Edge nodes authorize and record locally; the Hub is the system of record for identity, policy and consolidated attendance.
- **Modular Monolith** for the Central Hub; **Layered** structure inside each component group (Presentation → Business → Persistence → Database), closed layers with controlled-open shared services (A1 §3.2–3.3).
- Dynamic signed QR credentials; offline-first Edge with local cache, **Transactional Outbox** and **Store-and-Forward** sync; idempotent Hub ingestion.

## Module under implementation
**Edge Gate Access Processing** only: QR validation, access policy evaluation, turnstile interaction, attendance recording, local persistence, asynchronous sync. Hub modules, policy distribution, HR/Payroll export and the mobile app are out of scope for A2.

## Views

| View | Document | Question it answers |
|---|---|---|
| Module | [module-view.md](module-view.md) | How is the code organized and who may depend on whom? |
| Component-and-Connector | [component-connector-view.md](component-connector-view.md) | What runs at the gate and how do the parts interact at runtime? |
| Allocation | [allocation-view.md](allocation-view.md) | Where do the parts run? |

Decisions and open questions: [decisions.md](decisions.md). Interface contracts: [../contracts/edge-access-contracts.md](../contracts/edge-access-contracts.md).

## Lifecycle at a glance
QR validation → access authorization → unlock acknowledgement → passage confirmation → attendance record → local persistence → central sync ack. Each is a separate concept; see the contracts document.

## Open decisions
Blocking and non-blocking items: [decisions.md](decisions.md#open-decisions).
