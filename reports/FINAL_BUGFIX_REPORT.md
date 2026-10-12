# ProcureFlow final bugfix report

Result: **PASS**.

## Defect and impact

Three Phase 4 prompts placed an amount without a currency unit immediately before “60 天”. Qwen returned `4034400.0`, `1383263.0`, and `5248300.0` instead of `403.44`, `13832.63`, and `524.83`. Those proposals incorrectly reached `READY_FOR_APPROVAL`, so the defect was a real high-risk extraction boundary rather than an evaluation-only mismatch.

## Fix

The LLM remains the structured extraction layer. Before constructing the procurement requirement, `ProcurementCoordinatorAgent` now runs deterministic source alignment for monetary fields:

- accepts clearly labelled total budget and unit price evidence;
- normalizes `元`, `万元`, comma-formatted Arabic values, and Chinese amounts;
- keeps total budget and unit price distinct;
- does not treat quantities, dimensions, or delivery days as money;
- corrects a model value only when one exact source amount is deterministically identified;
- clears budget fields for ranges, vague amounts, conflicting values, or unclear monetary meaning.

Cleared budget fields produce `NEED_MORE_INFORMATION` before A2A dispatch. The dedicated safety test confirms that ambiguous amounts make zero transport calls, so they cannot reach budget reservation, approval, or purchase-order writes.

## Verification

| Check | Result |
|---|---:|
| Original Phase 4 failure prompts | 3/3 corrected |
| New amount-safety tests | 18 passed |
| Phase 1 regression | 85 passed |
| Phase 2 regression | 52 passed |
| Phase 3 regression | 18 passed |
| Phase 4 regression | 12 passed |
| Deterministic/fault evaluation | 60/60 |
| Write-through workflow evaluation | 6/6 |
| Real Qwen rerun | 30/30 |

Only one post-fix real-Qwen round was executed: run `P4LLM-7e53cc7203`, model `qwen-plus-latest`, 30 scenarios, 118 calls. Requirement parsing was 30/30, budget checks 23/23, supplier filtering 20/20, compliance 20/20, and recommendation validity 20/20. The three original failure IDs `P4-L002`, `P4-L008`, and `P4-L014` all passed.

## Database protection

The final before/after snapshots contain 16 tables and 398,869 rows. Row counts, all per-table content SHA-256 values, and the schema digest are identical. The schema SHA-256 is `a3db37a667f444c9d646d5213e73f14c60331abf340ddf1a7884bacfeefbde4d`. Dataset integrity audit passed and no `P3TEST-` request remained.

## Portability and release preparation

`PROCUREFLOW_DATA_ROOT` now accepts a repository-relative or absolute host path. Docker Compose, MySQL mount verification, logs, generated data, and SQLite checkpoint paths derive from that setting. The private local environment continues to use `E:/ProcureFlowData`; public users can use the default `./.procureflow-data` on Windows, Linux, or macOS. No `P:` or `SUBST` dependency exists.

The publication audit found no redistributable SmartVoyage license, so all reference files remain excluded. Exact file and token-window scans found no copied SmartVoyage code. Runtime data, `.env`, keys, logs, checkpoints, database files, raw evaluation payloads, and partial reports are ignored and excluded from the public staging set.

## Remaining limits

The validator intentionally asks for clarification when monetary meaning is uncertain. The 30/30 result applies to the fixed acceptance set and does not establish universal natural-language accuracy. Token usage is unavailable from the current gateway, and performance results describe one local low-concurrency environment.
