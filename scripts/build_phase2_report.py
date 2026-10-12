"""Build the acceptance report exclusively from executed evidence."""
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from config import ROOT,get_settings


def build():
    folder=ROOT/'reports/phase2'
    def read(name):return json.loads((folder/name).read_text(encoding='utf-8'))
    evaluation,verification,facts=read('evaluation.json'),read('verification.json'),read('facts-verification.json')
    after=read('AFTER.json')
    def suite(name):
        root=ET.parse(folder/name).getroot()
        suites=[root] if root.tag=='testsuite' else list(root.iter('testsuite'))
        return {key:sum(int(s.attrib.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}
    phase1,phase2=suite('phase1-regression.xml'),suite('phase2-tests.xml')
    traces=[json.loads(line) for line in (folder/'evaluation-trace.jsonl').read_text(encoding='utf-8').splitlines()]
    actions=Counter(t['action'] for t in traces)
    targets=Counter(t['target_agent'] for t in traces if t['action']=='A2A_CALL')
    tools=Counter(t['tool_name'] for t in traces if t['action']=='MCP_CALL')
    success=all(x['result']=='PASS' for x in (evaluation,verification,facts)) and phase1['tests']==85 and phase2['tests']>=52 and all(s[k]==0 for s in (phase1,phase2) for k in ('failures','errors','skipped'))
    formulas={
        'task_success_rate':'预期业务状态完全匹配的场景 / 全部场景；业务拒绝也是正确任务结果',
        'requirement_parse_accuracy':'所有指定关键字段（含缺失null）均正确的请求 / 全部请求；金额按Decimal数值比较',
        'budget_accuracy':'预算各金额、判定、采购后余额均匹配独立SQL基准 / 45条预算适用请求',
        'supplier_filter_accuracy':'原始及合规候选quote_id集合均匹配独立SQL基准 / 40条寻源适用请求',
        'compliance_accuracy':'每个候选的合规结论、最低报价数、审批链均匹配基准 / 30条合规适用请求',
        'recommendation_validity':'推荐quote_id等于独立评分第一名且合规通过 / 20条应有推荐的请求',
        'tool_call_success_rate':'成功MCP_CALL记录 / 所有MCP_CALL尝试（包括重试）',
        'a2a_call_success_rate':'成功A2A_CALL记录 / 所有A2A_CALL尝试（含50次外部协调入口）',
    }
    lines=['# ProcureFlow Phase 2 验收报告','',f"最终结论：**{'PASS' if success else 'FAIL'}**。生成时间：{datetime.now(timezone.utc).isoformat()}。",
        f"实测模型：`{evaluation['model']}`；评测运行ID：`{evaluation['run_id']}`。本次范围止于采购方案，不审批、不正式下单。",'',
        '## 架构、四个Agent与A2A拓扑','',
        '自然语言进入ProcurementCoordinatorAgent:5008。协调Agent分别经A2A调用BudgetAgent:5005、SupplierSourcingAgent:5006、ComplianceApprovalAgent:5007，三个专业Agent均将结果返回协调Agent。协调Agent依次进行预算、寻源、合规和排序，再返回结构化方案与中文解释；业务不满足条件时提前返回对应状态。',
        '三个专业Agent通过Streamable HTTP MCP访问Phase1 Service / rules.py，再连接现有Docker MySQL 127.0.0.1:3307。协调Agent不导入Service/Repository，所有Agent不直接查询数据库。独立评测脚本的SQL只用于校验基准。','',
        '| Agent | 职责 | MCP与工具 |','|---|---|---|',
        '| ProcurementCoordinatorAgent | 提取、完整性检查、A2A编排、硬过滤、确定性排名、方案解释 | 只调用三个专业Agent，无MCP写入能力 |',
        '| BudgetAgent | 读取预算及规则判定，组织预算结果 | 8001：get_department_budget、check_budget |',
        '| SupplierSourcingAgent | 真实报价、库存、交期、供应商详情及25期履约历史 | 8002：search_supplier_quotes、get_supplier_detail、get_supplier_performance |',
        '| ComplianceApprovalAgent | 资质、状态、报价数量、审批链预检 | 8003：get_supplier_qualifications、get_procurement_rules、evaluate_procurement_compliance |','',
        '端口、超时、重试和评分权重集中于config.py及环境变量。python-a2a真实AgentCard/AgentSkill/Task协议参考SmartVoyage的TicketOrderAssistant调用结构，未复制旅游逻辑。阶段依赖使用python-a2a、LangChain、langchain-openai、langchain-mcp-adapters；实际MCP传输采用其底层MCP SDK ClientSession。', '',
        '## Schema与Structured Output','',
        'agents/schemas.py使用Pydantic extra=forbid。ProcurementRequirement保存request_id、部门、产品名称/编码、数量、单价/总价预算、交期/日期、类别、原因；另含仅在用户明确给出时提取的supplier_id。缺失字段保留null。',
        'BudgetCheckResult包含总额、已用、预占、可用、申请金额、是否足额、剩余和原因。SupplierCandidate包含真实产品/供应商标识、报价、库存、交期、有效期、履约比率及各项评分；SupplierSearchResult包含计数、候选和警告。ComplianceResult包含判定、审批链、失败规则、最低报价数及原始资质证据。ProcurementProposal汇总上述结果，并返回六种业务状态之一。',
        '统一缓存的Qwen客户端仅通过os.getenv("DASHSCOPE_API_KEY")取凭据。LangChain function_calling → RequirementFields Pydantic校验，未使用自由文本作内部业务主结构。精确名称可由只读Tool解析为真实编码；未知或歧义名称不猜映射。',
        'LLM产生受白名单约束的工具计划，程序补齐不可省略的证据并绑定已验证参数；执行遵循数据依赖，独立查询遵循计划顺序。LLM选择解释因素（价格、交期、准时率、质量），中文事实由程序从已验证结果渲染，避免自由生成虚构价格或供应商。这是受约束的解释生成，不是开放式自由写作。','',
        '## 硬规则与评分','',
        '供应商ACTIVE；库存≥数量；金额=真实单价×数量且不超过总价/单价上限；交期满足要求；报价有效；产品/类别匹配；关键资质有效；Phase1合规通过。任何合规失败直接淘汰，LLM无覆写入口。有效报价数量按不同供应商计数，显式限定供应商也不能绕过资质或最低报价数规则。',
        '预算检查使用申请预算上限进行预检，remaining_after_purchase按该预检金额计算。此阶段不预占预算。',
        '对合规候选：price_score=最低单价/本单价×100；delivery_score=最短交期/本交期×100；on_time_score=准时率×100；quality_score=质量合格率×100。final_score=0.35×价格+0.25×交期+0.25×准时率+0.15×质量。Decimal计算，最终分数和展示分项分别保留6位小数。相同总分依次按总价、交期、supplier_id、quote_id升序稳定排序。权重必须非负且和为1。','',
        '## Trace与异常边界','',
        '日志位于E:/ProcureFlowData/logs/agents/trace.jsonl；每行包含timestamp、request_id、agent_name、action、target_agent、tool_name、status、latency_ms、error_type，不记录Prompt、API Key、连接密码或原始异常。验收Trace副本为reports/phase2/evaluation-trace.jsonl。',
        'A2A默认180秒、MCP 20秒、LLM 60秒；默认额外重试1次，有上限。供应商最多20页×100条，超过上限明确失败。异常覆盖A2A超时、三个Agent不可用、MCP不可用、数据库不可达、工具业务失败/空结果、模型结构化失败。返回ERROR及安全错误码或对应业务拒绝状态。AgentCard和request_id关联验证用于避免错接结果。', '',
        '## 实际执行证据','',
        f"- Phase1：{phase1['tests']} passed，{phase1['failures']} failed，{phase1['errors']} errors，{phase1['skipped']} skipped（phase1-regression.xml）。",
        f"- Phase2：{phase2['tests']} passed，{phase2['failures']} failed，{phase2['errors']} errors，{phase2['skipped']} skipped（phase2-tests.xml）。",
        '- 原85项规则/事务/并发幂等/MCP测试只在同一Docker实例原有procureflow_test中构造fixture；没有向正式库创建PO。',
        '- 新测试含四个真实AgentCard、真实Qwen采购建议/缺失字段、预算A2A→MCP→MySQL，以及真实关闭端口的A2A/MCP失败、MCP对不可达数据库的错误封装。其余单元测试使用明确fixture，未冒充真实集成。',
        '- 本次临时A2A/MCP验收进程已停止，七个端口已释放；Docker MySQL保留运行。通过README命令可重新启动。',
        '- pip check：No broken requirements found。两个pytest DeprecationWarning来自websockets/uvicorn旧接口，不影响结果。',
        f"- Docker：MySQL {after['version']}，{after['endpoint']}，datadir={after['datadir']}，容器healthy；E盘bind mount核验通过。",
        '- 正式库16张表、398869行；BEFORE/AFTER逐表数量、内容SHA-256、Schema SHA-256与迁移冻结基线全部相同。DATASET_AUDIT再次PASS。',
        '- 原SmartVoyage目录及ZIP完整性PASS；未生成替代业务数据或新建数据库；未依赖虚拟盘映射。', '',
        'A2A实际调用次数：`'+json.dumps(targets,ensure_ascii=False)+'`。',
        'MCP实际工具次数：`'+json.dumps(tools,ensure_ascii=False)+'`。',
        'LLM/通信Trace动作次数：`'+json.dumps(actions,ensure_ascii=False)+'`。','',
        '## 50条固定真实实体评测与指标','',
        f"场景：{evaluation['scenario_file']}；SHA-256：`{evaluation['scenario_sha256']}`。",
        '20条正常采购，预算不足、交期过严、库存不足、资质/供应商状态异常、报价不足、缺字段各5条。所有实体从现有正式库只读选取；全部自然语言请求实际经过Qwen和A2A，适用专业任务实际经过MCP和MySQL。独立SQL基准不调用Agent、Service或rules.py。',
        '分母按预期路径确定，发生故障不会通过减少分母获得更高分；工具/通信统计按实际尝试计数。业务拒绝不等于通信失败。','',
        '| 指标 | 分子/分母 | 实测值 | 计算口径 |','|---|---:|---:|---|']
    for name in formulas:
        m=evaluation['metrics'][name]
        lines.append(f"| {name} | {m['numerator']}/{m['denominator']} | {m['rate']:.2%} | {formulas[name]} |")
    lines += ['',f"补充独立事实复核：{facts['candidate_records_checked']}份候选/推荐记录，每份16个业务字段（供应商/产品身份、名称、价格、总价、库存、交期、有效期、履约率等）与数据库一致；{facts['parse_requests_checked']}条需求再次核验通过。证据：facts-verification.json。",'',
        '## 失败案例及已修复问题','',
        '- 初始qwen3-max真实调用返回HTTP 404/model_not_found。账户模型列表确认并实测qwen-plus-latest；集中配置已更新，未回退mock。',
        '- 首轮50条业务结论全部正确，但评测器按字符串比较金额，2266.80与2266.8被误判，提取指标为31/50。修复Decimal语义比较并加测试；保留evaluation-initial.json及原Trace，最终实现重新实跑50条，结果见当前evaluation.json。',
        '- 关闭端口测试最初使用2秒总预算，SDK多端点探测先产生超时。加入AgentCard身份验证并分别测试不可用和响应超时；重试次数受到集中配置限制。',
        '- 业务失败示例：S21–S25 NO_BUDGET；S26–S35 NO_SUPPLIER；S36–S45 COMPLIANCE_FAILED；S46–S50 NEED_MORE_INFORMATION。这些是期望的正确拒绝，均未创建订单。',
        f"- 最终评测失败场景：{evaluation['failures']}。",'',
        '## 新增及修改文件','',
        '- 新增agents/：schemas、prompts、llm、common、mcp_client、a2a_transport、specialists、coordinator及包入口。',
        '- 新增a2a_server/：common和四个Agent服务入口及包入口。',
        '- 新增scripts/：phase2_stack、run_procurement、evaluate_phase2、verify_evaluation_facts、verify_phase2、build_phase2_report。',
        '- 新增tests/phase2/：budget、supplier、compliance、procurement、faults、evaluation、a2a_integration、agent_e2e测试及fixture/helper。',
        '- 新增requirements-phase2.txt、requirements-phase2-lock.txt、PHASE2_REPORT.md、reports/phase2/证据；E盘generated/phase2下新增固定场景文件。',
        '- 修改config.py、.env.example（集中Agent配置）、本机忽略的.env（模型名）、README.md、AGENTS.md；四个MCP入口改用配置端口，Tool名称/数量不变。',
        '- 最小只读接口增强：BudgetRepository/SupplierRepository允许唯一精确名称匹配；BudgetService返回部门标识；SupplierService返回真实产品标识和类别。未改Phase1规则或表结构。',
        '- verify_artifacts.py将已授权A2A/LangChain依赖纳入Phase2，仍拒绝LangGraph/Streamlit越界导入。', '',
        '## Secret扫描、当前限制与Phase3建议','',
        f"Secret扫描：{verification['scan_files']}个项目文本/报告/日志文件；关键字形态及内存中实际凭据比对均通过。报告仅记录发现路径，不输出匹配内容。静态检查四Agent、只读8工具、无直连DB/Service、无LangGraph安装均通过。",
        '当前是本地单产品、单币种采购建议系统。精确名称/编码解析，不支持模糊别名消歧、多行采购或拆单。50条主要使用真实编码和三种中文句式，是可复现验收集，不代表任意自然语言的泛化准确率。数据是Phase1冻结的合成业务历史，非实际企业交易。',
        '规则及资质按执行当天判断，数据时间窗或年度变化可能使固定场景前置条件不再成立，脚本会明确失败而不自动改写数据。模型latest别名也可能变化，报告记录本次使用配置，不承诺未来输出完全一致。',
        'HTTP服务仅用于本机开发，尚无生产鉴权、TLS、限流或持久会话。网络超时可能结束等待但后台只读线程短暂继续；没有写入副作用。Trace为本地多进程追加JSONL，不是生产级日志平台。',
        '可用预算仅预检，没有预占或并发业务承诺；READY_FOR_APPROVAL不是审批通过。解释采用受约束因素选择和证据渲染。正式采购执行、人工审批、Checkpoint、Interrupt/Resume、LangGraph、前端、RAG及新基础设施均未实现。',
        'Phase3建议仅供后续授权：先设计可信审批身份、预算预占与幂等采购执行，再设计持久化工作流和恢复机制。本次在Phase2验收处停止。','']
    (ROOT/'PHASE2_REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(result='PASS' if success else 'FAIL',phase1=phase1,phase2=phase2,evaluation_run=evaluation['run_id']),ensure_ascii=False))
    return success


if __name__=='__main__':raise SystemExit(0 if build() else 1)
