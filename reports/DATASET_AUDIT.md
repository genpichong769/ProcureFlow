# 数据审计 PASS
MySQL 8.0.43 / procureflow / 固定数据观察日 2026-10-02

| 表 | 实际行数 |
|---|---:|
| departments | 30 |
| employees | 1,500 |
| department_budgets | 90 |
| products | 5,000 |
| suppliers | 800 |
| supplier_qualifications | 2,400 |
| supplier_quotes | 100,000 |
| supplier_performance | 20,000 |
| procurement_rules | 80 |
| approval_rules | 4 |
| purchase_requests | 30,000 |
| purchase_request_items | 60,000 |
| approval_records | 50,965 |
| purchase_orders | 25,000 |
| purchase_order_items | 50,000 |
| budget_transactions | 53,000 |

总行数：398,869

## 关键检查（异常行数，0表示通过）

- order_item_totals: 0
- request_item_totals: 0
- performance_arithmetic: 0
- budget_ledger_totals: 0
- budget_running_balances: 0
- request_reservations: 0
- commit_order_consistency: 0
- requester_department: 0
- order_request_state: 0
- order_item_request_match: 0
- order_missing_request_items: 0
- order_quote_match: 0
- transaction_department: 0
- duplicate_request_po: 0
- duplicate_request_number: 0
- duplicate_po_number: 0
- invalid_quote_amount_or_delivery: 0
- invalid_request_amounts: 0
- invalid_order_amounts: 0
- invalid_request_item_amounts: 0
- invalid_order_item_amounts: 0
- invalid_reference_price: 0
- invalid_transactions: 0
- invalid_supplier_rates: 0
- invalid_qualifications: 0
- invalid_approval_timestamp: 0
- profile_correlation: 0
- index_access_supplier_candidates: 0
- index_access_department_budget: 0
- index_access_purchase_order: 0
- manifest_count_mismatches: 0
- target_scale: 0

外键关系：20，孤儿总数：0

## 分布与画像

```json
{
  "distributions": {
    "suppliers": [
      {
        "status": "ACTIVE",
        "n": 700
      },
      {
        "status": "SUSPENDED",
        "n": 67
      },
      {
        "status": "BLACKLISTED",
        "n": 33
      }
    ],
    "supplier_qualifications": [
      {
        "status": "ACTIVE",
        "n": 2200
      },
      {
        "status": "EXPIRED",
        "n": 100
      },
      {
        "status": "REVOKED",
        "n": 100
      }
    ],
    "purchase_requests": [
      {
        "status": "DRAFT",
        "n": 1000
      },
      {
        "status": "PENDING_APPROVAL",
        "n": 1000
      },
      {
        "status": "APPROVED",
        "n": 1000
      },
      {
        "status": "REJECTED",
        "n": 1000
      },
      {
        "status": "ORDER_CREATED",
        "n": 23000
      },
      {
        "status": "CANCELLED",
        "n": 3000
      }
    ],
    "purchase_orders": [
      {
        "status": "CREATED",
        "n": 3000
      },
      {
        "status": "CONFIRMED",
        "n": 20000
      },
      {
        "status": "CANCELLED",
        "n": 2000
      }
    ],
    "quotes": [
      {
        "validity": "EXPIRED",
        "n": 15000
      },
      {
        "validity": "VALID",
        "n": 85000
      }
    ],
    "quote_edge_cases": {
      "low_stock": "10000",
      "slow_delivery": "10000"
    },
    "qualification_expiring": 200
  },
  "profiles": [
    {
      "profile": "A",
      "price_index": "1.1196464188",
      "delivery_days": "14.7996",
      "normal_quote_delivery_days": "3.4995",
      "on_time_rate": "0.985000000",
      "quality_rate": "0.995000000"
    },
    {
      "profile": "B",
      "price_index": "0.8801647000",
      "delivery_days": "15.5010",
      "normal_quote_delivery_days": "15.5010",
      "on_time_rate": "0.880000000",
      "quality_rate": "0.960000000"
    },
    {
      "profile": "C",
      "price_index": "0.9999853952",
      "delivery_days": "8.4932",
      "normal_quote_delivery_days": "8.4932",
      "on_time_rate": "0.910000000",
      "quality_rate": "0.870000000"
    },
    {
      "profile": "D",
      "price_index": "0.9399136405",
      "delivery_days": "21.9835",
      "normal_quote_delivery_days": "12.4794",
      "on_time_rate": "0.800000000",
      "quality_rate": "0.830000000"
    }
  ],
  "performance_profiles": [
    {
      "profile": "A",
      "observed_on_time_rate": "0.9838",
      "observed_quality_rate": "0.9923",
      "observed_delivery_days": "3.003692",
      "observed_price_index": "1.1200000"
    },
    {
      "profile": "B",
      "observed_on_time_rate": "0.8806",
      "observed_quality_rate": "0.9598",
      "observed_delivery_days": "15.007740",
      "observed_price_index": "0.8800000"
    },
    {
      "profile": "C",
      "observed_on_time_rate": "0.9096",
      "observed_quality_rate": "0.8700",
      "observed_delivery_days": "7.987220",
      "observed_price_index": "1.0000000"
    },
    {
      "profile": "D",
      "observed_on_time_rate": "0.7996",
      "observed_quality_rate": "0.8302",
      "observed_delivery_days": "11.992226",
      "observed_price_index": "0.9400000"
    }
  ]
}
```

## EXPLAIN（原始结果；完整索引清单见JSON）

```json
{
  "supplier_candidates": [
    {
      "id": 1,
      "select_type": "SIMPLE",
      "table": "q",
      "partitions": null,
      "type": "range",
      "possible_keys": "idx_quote_candidate,idx_quote_supplier,idx_quote_price",
      "key": "idx_quote_candidate",
      "key_len": "12",
      "ref": null,
      "rows": 17,
      "filtered": 1.23,
      "Extra": "Using index condition; Using where; Using filesort"
    },
    {
      "id": 1,
      "select_type": "SIMPLE",
      "table": "s",
      "partitions": null,
      "type": "eq_ref",
      "possible_keys": "PRIMARY",
      "key": "PRIMARY",
      "key_len": "8",
      "ref": "procureflow.q.supplier_id",
      "rows": 1,
      "filtered": 33.33,
      "Extra": "Using where"
    },
    {
      "id": 1,
      "select_type": "SIMPLE",
      "table": "k",
      "partitions": null,
      "type": "eq_ref",
      "possible_keys": "uq_supplier_qualification,idx_qualification_valid",
      "key": "uq_supplier_qualification",
      "key_len": "210",
      "ref": "procureflow.q.supplier_id,const",
      "rows": 1,
      "filtered": 5.0,
      "Extra": "Using where"
    },
    {
      "id": 1,
      "select_type": "SIMPLE",
      "table": "k",
      "partitions": null,
      "type": "eq_ref",
      "possible_keys": "uq_supplier_qualification,idx_qualification_valid",
      "key": "uq_supplier_qualification",
      "key_len": "210",
      "ref": "procureflow.q.supplier_id,const",
      "rows": 1,
      "filtered": 5.0,
      "Extra": "Using where"
    }
  ],
  "department_budget": [
    {
      "id": 1,
      "select_type": "SIMPLE",
      "table": "department_budgets",
      "partitions": null,
      "type": "const",
      "possible_keys": "uq_department_year",
      "key": "uq_department_year",
      "key_len": "12",
      "ref": "const,const",
      "rows": 1,
      "filtered": 100.0,
      "Extra": null
    }
  ],
  "purchase_order": [
    {
      "id": 1,
      "select_type": "SIMPLE",
      "table": "purchase_orders",
      "partitions": null,
      "type": "const",
      "possible_keys": "request_id",
      "key": "request_id",
      "key_len": "8",
      "ref": "const",
      "rows": 1,
      "filtered": 100.0,
      "Extra": null
    }
  ]
}
```
