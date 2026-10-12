# Phase 4 架构审计

结论：**PASS**。审计基于当前源码、96条新评测、Phase 1～4最终回归、真实Trace、持久化Checkpoint和MySQL前后快照。

状态含义：`VERIFIED`表示实现与动态证据一致；`FAIL`表示验收条件未满足。本次没有架构项为FAIL。

## 审计矩阵

| 范围 | 状态 | 实际证据 |
|---|---|---|
| LangGraph主流程 | VERIFIED | 运行时代码只有一个StateGraph；14个节点和条件边控制方案、申请、RESERVE、审批、PO、COMMIT、验证与恢复。State为显式TypedDict。 |
| Checkpoint与interrupt/resume | VERIFIED | SqliteSaver位于`PROCUREFLOW_DATA_ROOT/langgraph/checkpoints.sqlite`；Phase3不同PID重启证据仍为PASS；Phase4新Checkpoint案例1/1成功。 |
| 重复resume与副作用 | VERIFIED | 新Workflow 6/6符合终态；完成后重复resume被拒绝；应创建PO的5条中重复PO为0。 |
| A2A | VERIFIED | Coordinator只通过`A2AClient.send_task_async`访问5005/5006/5007三个专业Agent；没有导入专业Agent实现。30条LLM和54条离线方案均产生真实网络Trace。 |
| A2A失败边界 | VERIFIED | 断端和0.25秒慢服务均返回安全错误；含刻意失败/业务拒绝时，离线136/142、LLM 95/98成功。 |
| MCP | VERIFIED | 专业Agent经Streamable HTTP访问8001/8002/8003，Workflow经8004访问采购能力；Agent和Workflow均无Repository/Service/MySQL导入。 |
| MCP工具边界 | VERIFIED | 白名单无任意SQL Tool；`execute_sql`探测返回FORBIDDEN_TOOL；Pydantic/FastMCP校验参数，工具错误使用结构化安全码。 |
| MCP失败边界 | VERIFIED | 暂时不可用与错误参数均被识别；含负面探针时离线1549/1553、LLM 1002/1005成功。 |
| 业务规则权威性 | VERIFIED | 预算、库存、报价有效期、供应商状态、资质、合规、评分和PO金额均来自Tool结果及确定性规则；LLM没有覆写通过入口。 |
| Trace | VERIFIED | Phase4导出Trace共4745条且字段完整。历史追加日志保留7条修复前碎片；最终命名跨进程互斥锁的8进程压力验证为400/400行有效。 |
| 数据与Secret | VERIFIED | 16表398,869行，前后内容与Schema哈希一致；最终Secret扫描272个文本文件，发现0项。 |

## LangGraph控制流

`build_proposal`把Coordinator返回的结构化方案写入State；条件边只允许`READY_FOR_APPROVAL`继续。随后真实创建申请和RESERVE，`human_approval`调用`interrupt`，恢复输入经过审批人状态、部门和角色校验。REJECT写审批记录、RELEASE并终止；全链APPROVE后才创建PO。执行、COMMIT或重新查询失败进入有上限的`recovery_wait`，不会无限循环。

没有发现绕过Graph的隐藏采购执行路径。FastAPI只调用`ProcurementWorkflow.start/get/resume/retry`。MySQL保存业务事实，Checkpoint保存流程位置；两者职责没有混用。

## A2A实际路径

地址：Coordinator `http://127.0.0.1:5008`，Budget `:5005`，Supplier `:5006`，Compliance `:5007`。请求是包含`request_id`和结构化任务的A2A Task；响应是`{ok,data}`或`{ok:false,error_type}`包。评测报告只保存业务字段，不保存Prompt、Key或连接密码。

实际路径为：Coordinator → `A2ATransport.call` → AgentCard校验 → A2A Task → 专业Agent。错误按超时、目标Agent不可用、无artifact或远端安全错误码分类，并有有限重试。

## MCP实际路径

地址：Budget `http://127.0.0.1:8001/mcp`，Supplier `:8002/mcp`，Compliance `:8003/mcp`，Procurement `:8004/mcp`。专业Agent发现白名单Tool后提交已验证参数，MCP Server调用Service/Rules，再访问Docker MySQL。Coordinator、专业Agent和Workflow源码均未直接访问数据库。

不是装饰性Tool：独立评测实际产生预算读取、报价查询、供应商详情/履约、资质、规则、合规和采购写入Trace；断开MCP会使任务失败，不存在静默本地回退。

## 已知边界

- 本地回环部署没有生产鉴权、TLS、审批委托或多实例分布式锁。
- SQLite Checkpoint适合单机演示，不代表多副本高并发状态存储。
- 三条无金额单位的口语输入发生数字拼接，需在产品化时增加高风险金额确认或更严格的单位校验。
- 历史Trace旧碎片没有删除；最终互斥锁压力验证0坏行，Phase4导出Trace全部可解析。
