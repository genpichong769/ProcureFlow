# Phase 4 evaluation

Result: **PASS**. The fixed seed is `20261012`; Phase 4 added 96 independent cases.

| Evaluation set | Cases | Result |
|---|---:|---:|
| Deterministic proposals and fault injection | 60 | 60/60 |
| Real Qwen integration | 30 | 30/30 |
| LangGraph write-through workflows | 6 | 6/6 |

The real-Qwen run `P4LLM-7e53cc7203` used `qwen-plus-latest` once after the fix. It made 118 calls: 30 extraction, 68 tool-selection, and 20 explanation calls.

| Metric | Deterministic | Real Qwen |
|---|---:|---:|
| Requirement parsing | N/A | 30/30 |
| Budget decision | 43/43 | 23/23 |
| Supplier filtering | 39/39 | 20/20 |
| Compliance | 34/34 | 20/20 |
| Recommendation validity | 20/20 | 20/20 |

A2A success was 95/98 and MCP success was 1002/1005 in the Qwen run because the denominator includes expected negative and unavailable-entity paths. Those structured failures are safe outcomes, not hidden fallbacks.

Workflow acceptance verified exact approval roles, persistent checkpoint recovery, MySQL writes, budget reserve/release/commit consistency, PO re-read integrity, and idempotency. Test cleanup restored the frozen database byte-for-byte at the logical table and schema evidence level.

The 30/30 result measures the fixed acceptance set. It must not be presented as universal model accuracy. Performance is a local low-concurrency observation, and the gateway does not retain token usage metadata.
