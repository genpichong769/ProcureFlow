# MySQL schema

需要 MySQL 8.0.16+（Docker迁移目标版本 8.0.43），使用 InnoDB / utf8mb4，CHECK 约束必须实际生效。

原数据库迁移使用经过校验的mysqldump备份恢复，不执行数据生成或批量加载。仅从零创建新的合成环境时，执行 `python -m scripts.load_procurement_dataset` 会在空数据库依次执行 create_tables.sql、create_indexes.sql，再在一个事务中批量导入16个数据文件。数据库需预先建立；Compose的首次初始化创建 procureflow 与 procureflow_test。

脚本不执行 DROP DATABASE，不关闭外键检查，不覆盖已有数据。发现任何业务行即拒绝导入；批量导入异常则整批回滚。MySQL DDL 不支持与数据一起回滚，部分建表失败时脚本会拒绝继续，需人工检查该新库，不自动删除表。

核心约束：department_budgets(department_id,fiscal_year)唯一；purchase_orders(request_id)唯一；request_no与po_no分别唯一；申请与订单每产品只一行；所有金额、数量、日期、状态与履约计数受约束。purchase_requests.fiscal_year锁定申请年度，预算确认跨年也不漂移。

索引同时使用建表内的PK/FK/UNIQUE和create_indexes.sql中的显式复合索引。审计对实际数据库运行SHOW INDEX、EXPLAIN，并记录到reports/DATASET_AUDIT.json。报价查询先按product_id定位，随后筛选状态、有效期、库存、限价、交期与关键资质；排序可能使用filesort，这是对候选小集合的排序，不等同全表扫描。

预算字段按流水推导：RESERVE增加reserved；RELEASE减少reserved；COMMIT减少reserved并增加used。COMMIT不改变available，因为该金额在预占时已经扣减。余额序列从total_budget减累计ADJUST还原期初总额，再重放流水。当前阶段不提供ADJUST写入Tool。

订单状态仅允许CREATED→CONFIRMED或CREATED→CANCELLED；相同目标状态重试无新增流水。已确认订单不支持退货或冲销。取消的申请保持唯一PO关联，重试创建仍返回该已取消PO；重新采购需新申请。
