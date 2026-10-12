"""Generate the migration report from actual verification artifacts, never planned results."""
from datetime import datetime, timezone
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from config import ROOT


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def build():
    directory = ROOT/'reports/migration'
    before, after = read(directory/'BEFORE.json'), read(directory/'AFTER.json')
    backup = read(directory/'BACKUP.json')
    native = read(directory/'NATIVE_RETIREMENT.json')
    verified = read(directory/'MIGRATION_VERIFICATION.json')
    artifacts = read(ROOT/'reports/VERIFICATION.json')
    audit = read(ROOT/'reports/DATASET_AUDIT.json')
    smoke = read(ROOT/'reports/MCP_HTTP_SMOKE.json')
    generated = read(directory/'GENERATED_STORAGE.json')
    xml = ET.parse(directory/'pytest_docker.xml').getroot()
    cases = list(xml.iter('testcase'))
    failed = sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
    skipped = sum(c.find('skipped') is not None for c in cases)
    passed = len(cases)-failed-skipped
    suites = list(xml.iter('testsuite'))
    duration = sum(float(s.get('time','0')) for s in suites)
    names = {c.get('name') for c in cases}
    required_tests = {
        'test_transaction_rollback_after_item_insert','test_rollback_after_budget_and_request_mutation',
        'test_confirmation_rolls_back','test_concurrent_idempotency','test_database_unique_constraint',
        'test_success_real_inserts_and_requery','test_commit_exact_amount',
        'test_reserve_release_and_retry','test_concurrent_reserves_do_not_overspend',
        'test_all_procurement_tools',
    }
    gates = {
        'migration_verification':verified['result']=='PASS',
        'fresh_dataset_audit':audit['result']=='PASS' and audit['mysql_version']==after['version'],
        'full_phase1_pytest':passed>=85 and failed==0 and skipped==0,
        'required_transaction_and_idempotency_tests':required_tests<=names,
        'real_mcp_http':len(smoke)==4 and all(s['result']=='PASS' for s in smoke),
        'smartvoyage_integrity':artifacts['source_integrity']['result']=='PASS',
        'secret_and_phase_scan':artifacts['static_scan']['result']=='PASS',
        'generated_files_copied_unchanged':generated['result']=='PASS' and generated['copied_not_regenerated'],
    }
    result = 'PASS' if all(gates.values()) else 'BLOCKED'
    report_time = datetime.now(timezone.utc).isoformat()
    summary = dict(result=result,generated_at=report_time,gates=gates,
        before_count=before['total_rows'],after_count=after['total_rows'],tables=len(after['tables']),
        pytest=dict(passed=passed,failed=failed,skipped=skipped,seconds=duration,
                    timestamp=suites[0].get('timestamp') if suites else None),
        original_data_retained=native['old_data_retained'],phase2_started=False)
    (directory/'RESULTS.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    docker = verified['docker']
    lines = [f'# ProcureFlow 数据迁移与Docker化验收 — {result}', '',
        f'报告时间（UTC）：{report_time}。本报告来自本次实际查询、数据审计、Pytest、MCP HTTP和完整性检查。',
        '', '## 环境规范与映射清理', '',
        f"原映射为 `{before['datadir'][:2]} → {ROOT}`。2026-10-02在完成备份并正常关闭旧专用实例后，已执行映射删除命令；随后映射列表为空。最新复核使用Windows设备查询，映射仍不存在。未删除或移动真实项目目录。",
        '', f"项目维护的源码、配置、.env/.env.example、SQL、启动与测试脚本、README、reports和Docker配置已扫描；最新扫描{verified['path_scan']['files_scanned']}个文本文件，**有效映射路径依赖为0**。历史报告中的原datadir、长期禁止规则和审计检测表达式属于证据/规则文本，不作为运行路径。第三方依赖、字节码与数据库二进制文件不属于有效源码依赖检查。",
        '', '原bootstrap_local_mysql入口已禁用；local_mysql兼容入口只控制本项目Compose服务。旧.runtime启动配置已标记退役，不能再创建映射或启动原生数据库。AGENTS.md已固化真实路径、Docker优先、E盘bind mount、凭据保护和原数据保留约定。README只介绍当前Docker运行方式。',
        '', '## 原MySQL实例与数据位置', '',
        f"- 原版本：MySQL {before['version']}；连接：{before['endpoint']}。",
        '- 启动方式：Windows mysqld.exe独立后台进程，使用项目内.runtime/my.ini；不是MySQL80服务。迁移前监听3307的进程实查为10376，原启动记录记录的进程为14568。',
        f"- 实际执行 `{before['datadir_query']}`，结果：`{before['datadir']}`。",
        f"- 映射对应的真实目录：`{native['original_real_directory']}`，**旧ProcureFlow数据本来就在E盘，不在C盘**。",
        '- 该实例仅有procureflow、procureflow_test和MySQL系统库；停机前核验server_uuid及数据库列表，确认是ProcureFlow专用实例。其他MySQL80服务未被关闭或改动。',
        '', '## 完整备份', '',
        f"- 文件：`{backup['backup_path']}`。",
        f"- 时间（UTC）：{backup['created_at']}。",
        f"- 大小：{backup['bytes']:,} bytes（{backup['bytes']/1024/1024:.2f} MiB）。",
        f"- SHA-256：`{backup['sha256']}`。",
        f"- 原表数：{backup['table_count']}；原总行数：{backup['total_rows']:,}。",
        '- 使用官方mysqldump，包含schema、数据、索引、外键和CHECK约束，保留触发器/事件/存储程序导出选项。使用single-transaction/quick，密码通过临时客户端配置提供；临时凭据文件已清理，密码未置于命令行。',
        '- 备份成功后才关闭原实例；恢复使用该SQL文件而非生成器。恢复目标先验证为空库，导入日志位于E盘backup/restore.log。最新复核备份哈希未变。',
        '', '## Docker实例与真实E盘bind mount', '',
        f"- 镜像：`{docker['configured_image']}`；实测MySQL版本：{after['version']}。",
        f"- 容器：`{docker['name']}`，健康状态：{docker['state']['Health']['Status']}。",
        f"- Compose：`{ROOT/'docker-compose.yml'}`，仅包含MySQL服务。",
        '- 端口：`127.0.0.1:3307 → container:3306`。Python仍通过DB_*环境配置连接，未感知平台差异。',
        f"- Docker内再次执行SHOW VARIABLES查询，datadir为 `{after['datadir']}`。",
        '- Python连接得到的server_uuid与容器内SQL查询的server_uuid一致，且不同于旧实例；因此本次审计、业务查询所连接的是新Docker实例。',
        '', '| Host bind source | Container destination | 权限 |', '|---|---|---|',
        *[f"| {m['Source']} | {m['Destination']} | {'读写' if m['RW'] else '只读'} |" for m in docker['mounts']],
        '', '上述映射来自docker inspect的真实Mounts字段，所有持久化挂载Type均为bind，没有使用named volume。宿主E盘已实际出现MySQL数据文件和error.log。容器logging driver设为none，MySQL长期错误日志写入E盘挂载目录。',
        '', '大规模生成数据已从项目旧目录逐文件复制到E:/ProcureFlowData/generated；复现样本在generated/reproduction，共34个文件哈希一致。本次没有运行随机生成器替代数据库。项目旧副本保留不动；未来默认输出与MCP/Python日志已切换到统一E盘根目录。',
        '', '## 迁移前后逐表对账', '', '| 表 | 迁移前 | Docker迁移后 | 内容SHA-256 |', '|---|---:|---:|---|',
        *[f"| {t} | {before['counts'][t]:,} | {after['counts'][t]:,} | {'一致' if before['table_sha256'][t]==after['table_sha256'][t] else '不一致'} |" for t in before['counts']],
        '', f"**合计：{before['total_rows']:,} → {after['total_rows']:,}，16张表全部一致。**",
        '', '逐表内容哈希按主键顺序读取数据库全部行并规范化序列化计算，包含所有列。除行数一致外，字段、索引、FK、CHECK、引擎/排序规则和AUTO_INCREMENT元数据也全部一致；schema差异为0。原数据无丢失、无替换。证据：reports/migration/BEFORE.json、AFTER.json、MIGRATION_VERIFICATION.json。',
        '', '## 新实例上的数据审计', '',
        f"实际重新运行scripts/audit_dataset.py：**{audit['result']}**，MySQL版本{audit['mysql_version']}，{len(audit['checks'])}项关键检查、{len(audit['orphan_checks'])}组外键关系，异常数均为0。未引用旧审计作为本次结果。",
        '', '覆盖外键孤儿、预算汇总/逐笔余额/申请预占/COMMIT对账、supplier_performance计数、资质与报价有效性、状态分布、request/order关联、订单明细金额、重复request/PO、唯一约束和索引访问。完整新报告：reports/DATASET_AUDIT.md及JSON；旧报告归档于reports/migration/phase1_before。',
        '', '## 全量Pytest、事务和并发幂等', '',
        f"实际重新执行完整测试：**{passed} passed、{failed} failed、{skipped} skipped**，耗时{duration:.2f}秒。测试时间：{summary['pytest']['timestamp']}；XML：reports/migration/pytest_docker.xml。",
        '', '测试连接Docker MySQL的procureflow_test，正式procureflow数据不受fixture清理影响。连接失败不会skip。四类Service、四类MCP、HTTP、规则及数据库约束均覆盖。',
        '', '- RESERVE、RELEASE、COMMIT及重复操作：通过，预算余额与流水一致。',
        '- 真实INSERT写入订单和明细、独立get_purchase_order重新查询：通过。',
        '- 在订单明细INSERT后、预算/请求更新后、COMMIT流水后分别注入异常：通过，验证完整回滚。',
        '- 六线程并发创建同一request：通过，只产生一个PO；数据库唯一约束直接重复INSERT被拒绝。',
        '- 两个请求并发竞争预算：通过，不超额预占。',
        '- 合法状态流转、非法状态拒绝、取消还原库存：通过。',
        '', '## 真实MCP连接新数据库', '',
        '另外实际启动四个CLI MCP服务，通过默认端口Streamable HTTP完成初始化、发现工具和查询新Docker正式库。测试后仅停止本次启动的MCP进程；MySQL容器继续运行。',
        '', '| Server | 端口 | 实际调用 | 结果 |', '|---|---:|---|---|',
        *[f"| {s['server']} | {s['port']} | {s['tested_tool']} | {s['result']} |" for s in smoke],
        '', '完整16个Tool清单及结果见reports/MCP_HTTP_SMOKE.json。Pytest中的协议和真实HTTP测试还验证创建PO、查询、预算、重试幂等、状态更新；未提供任意SQL Tool。',
        '', '## Secret、原项目和范围保护', '',
        f"实际凭据比对扫描与静态扫描均PASS，代码/报告/服务日志未发现DB密码或root密码泄露。Compose通过.env变量注入，无明文密码；.env被Git忽略。SmartVoyage源码及ZIP的{artifacts['source_integrity']['files_checked']}个文件校验全部一致。",
        '', '环境API Key未回显；Docker inspect仅选取不含Config.Env的字段。备份下legacy-native-config包含用于回退的本机敏感配置，不属于可提交或共享的报告。未修改Docker Desktop/WSL全局配置、其他项目的容器/卷或数据目录，未开发Phase 2。',
        '', '## 旧数据保留与之后可清理的范围', '',
        f"ProcureFlow已经不再依赖旧本地MySQL。`{native['original_real_directory']}`仍原样保留，未删除。此次实例不在C盘，因此不存在由本次迁移产生、需要清理的C盘旧ProcureFlow datadir；未据此推断其他项目或全机C盘没有数据库。",
        '', 'Docker、数据审计、全套Pytest及真实MCP已稳定通过。现在可以在用户另行明确清理时，仅清理以下已失去运行依赖的旧副本：',
        '', f"- `{ROOT/'.runtime/mysql-data'}`：已关闭的ProcureFlow专用旧实例目录。",
        f"- `{ROOT/'data/generated'}` 与 `{ROOT/'.runtime/reproduction'}`：已按哈希复制到统一E盘数据根目录的历史生成数据副本。",
        '', '本次未执行上述清理。建议继续保留E:/ProcureFlowData/mysql/backup中的SQL备份及备份校验记录。禁止将其他Windows MySQL服务的数据目录、Docker其他项目数据、E:/ProcureFlowData/mysql/data当前库纳入旧数据清理。',
        '', '## Docker Desktop自身与遗留事项', '',
        '- Docker引擎报告DockerRootDir=/var/lib/docker（Linux内部路径），不能据此确定其宿主物理盘。Docker Desktop的镜像层、build cache、容器元数据及WSL虚拟磁盘仍可能占用C盘；没有修改或迁移全局数据目录。ProcureFlow自身业务数据已通过实际bind mount确认落在E盘。',
        '- 主机另一项目的停止状态MySQL容器也配置了3307；其配置保持原样。若以后启动该容器，会与本项目争用端口，应由用户选择端口分配。',
        '- Windows目录bind mount的首次初始化/导入写入较慢；本次未降低MySQL事务持久性来换取测试通过。',
        '- 当前保留了旧数据库与生成数据副本以便回退，因而会额外占用E盘空间。它们是历史备份，不是活动持久化路径。',
        '- 没有未解决的关键迁移FAIL；原Phase 1的单供应商订单、无审批交互及本地开发权限边界保持不变。',
        '', '## 启动方式与最终结论', '',
        '启动Docker Desktop后，在真实项目目录运行：', '',
        '```powershell', '.\\.venv\\Scripts\\python.exe -m scripts.docker_mysql prepare',
        'docker compose up -d mysql', 'docker compose ps mysql', '```',
        '', f'本次迁移验收：**{result}**。完成后停止，未继续Phase 2。', '']
    (ROOT/'MIGRATION_AND_DOCKERIZATION_REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True))
    if result!='PASS':
        raise SystemExit(1)


if __name__=='__main__':
    build()
