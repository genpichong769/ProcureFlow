# ProcureFlow resume project draft

## Project

ProcureFlow｜Enterprise Procurement Multi-Agent System

Built a four-Agent enterprise procurement workflow using Qwen, LangGraph, A2A, MCP, FastAPI, MySQL, and Docker Compose. The system turns natural-language needs into evidence-backed supplier recommendations, pauses for role-validated human approval, and writes budget and purchase-order transactions through idempotent service boundaries.

## Highlights

- Kept coordinator, budget, supplier, and compliance responsibilities behind real A2A and MCP boundaries; Agents and workflow code cannot access MySQL directly.
- Implemented LangGraph interrupts, multi-level approval, persistent SQLite checkpoints, reserve/release/commit budget accounting, fault recovery, and idempotent PO creation.
- Restricted the LLM to structured extraction, constrained tool selection, and explanation factors; used Decimal rules and transactions for financial and compliance decisions.
- Added source-aligned monetary validation that handles Arabic/Chinese amounts and total/unit price while forcing clarification for ambiguity before any write path.
- Built a reproducible 16-table, 398,869-row synthetic procurement dataset and independent SQL-oracle evaluation.

## Verified results

- 185 Pytest checks passed: Phase 1 `85`, Phase 2 `52`, Phase 3 `18`, Phase 4 `12`, and final bugfix `18`.
- Phase 4: deterministic/fault `60/60`, write-through workflow `6/6`, real Qwen fixed set `30/30`.
- PO integrity `5/5`, checkpoint reopen `1/1`, duplicate PO `0/5`.
- Final database row counts, per-table content hashes, and schema hash matched the frozen baseline.

## Honest scope

The data is synthetic, the evaluation set is fixed, and the deployment is a local acceptance environment. The project does not claim production authentication, TLS, distributed locking, payment, receiving, tax, returns, live supplier integration, or universal LLM accuracy.
