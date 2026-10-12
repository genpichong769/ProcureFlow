# Phase 4 failure analysis

## Original failure

`P4-L002`, `P4-L008`, and `P4-L014` used “钱别超过金额，60 天内送到” without a currency unit after the amount. Qwen concatenated the amount with the adjacent delivery value and returned `4034400.0`, `1383263.0`, and `5248300.0`. All three incorrect requirements reached `READY_FOR_APPROVAL` in the original run.

## Resolution

The extraction prompt now explicitly separates punctuation and delivery values from money. More importantly, a deterministic validator aligns `max_total_amount` and `max_unit_price` with labelled source evidence before the requirement can be dispatched.

Clear exact evidence can correct a model mismatch. Ranges, vague amounts, conflicting values, unsupported precision, or unclear total/unit meaning clear both budget fields and return `NEED_MORE_INFORMATION`. Quantity, dimensions, and delivery-day numbers are never accepted as money evidence.

The post-fix run passed all three original IDs and all 30 fixed real-Qwen cases. New tests also prove that ambiguous amounts cause zero downstream transport calls.

Historical pre-fix evidence remains in the local `reports/final_bugfix/before-failures.json`; raw model payloads are excluded from public staging. Current aggregate evidence is in `reports/PHASE4_METRICS.json` and `reports/FINAL_BUGFIX_REPORT.md`.
