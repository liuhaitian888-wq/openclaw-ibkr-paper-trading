# 五项目维护入口

workspace.json 是当前用户指定的项目范围、资料分期与维护边界。采集器不执行项目文档中的命令，不改变业务配置，也不清理文件。每个项目的状态、下一步Prompt、文件清单与图表缺口分别输出，工作区首页只做汇总。

主工作区入口：`python scripts/maintain_workspace.py --workspace-root ~/Documents/der --refresh`。
默认输出：`~/.local/state/openclaw/engineering/workspace-maintenance/current/`。
开发/离线测试请指定临时输出；完整套件仍遵守 AGENTS.md。`--check` 只检查，不发布输出。

## 分界和融合

- 本机历史维护、云端准备、云端实际观测、未来目标设计分别记录。旧业务模型可以继续有效，旧部署假设必须重新核验。
- 来源优先级依据适用范围：相同环境的新鲜运行证据、已验证源码、明确设计决定、历史材料。不能简单使用“最新文档覆盖全部旧记录”。
- 差异逐项裁决：KEEP / ADAPT / REPLACE / HISTORICAL / PROPOSAL / QUARANTINE_CANDIDATE。缺证据保持UNKNOWN，不能因为文件旧或无静态引用就自动删除。
- 实现、离线测试、部署、真实验收各自记录；文档自称VERIFIED或出现测试数量不能自动升级状态。
- 生成的上下文与Prompt不是执行授权。自动接续只能在既有用户目标和各项目权限内实施，业务授权、不可逆数据迁移、外部发送和交易单独受门禁约束。

## 更新规则

日常证据更新使用文件指纹和Git状态检测变化，生成目录不作为业务源码输入，避免自身更新导致无限循环。项目源码保持只读；上下文与文档的Git同步在各项目独立worktree完成，保留人工段落和并行修改。

隔离要有原路径、内容指纹、归属、替代来源、引用检查和恢复办法。生产数据库、WAL/SHM、凭据、备份、历史证据、未提交或未合并worktree始终受保护。v1只生成隔离候选，不移动、不删除。


图表依赖收据由各项目`.der/maintenance/diagram-dependencies.json`登记：`{"diagrams":[{"path":"docs/flow.svg","output_sha256":"输出SHA256","inputs":{"src/module.py":"输入SHA256"}}]}`。输入与输出指纹相符时只标CONTENT_MATCHES_RECEIPT；输入或输出变化标STALE_CONTENT。无收据继续NEEDS_DEPENDENCY_BASELINE；内容相符不代表业务语义审阅通过。维护代理更新设计/代码后重建受影响图表，审阅后更新收据。


## 2026-11-09 起的触发方式

用户要求仅在开发任务收尾时触发，旧小时heartbeat已暂停；不配置每日空跑。全局Codex UserPromptSubmit/Stop hook仅对登记五项目及其linked worktree生效：起点/上次完成指纹与结束指纹不同才请求一轮维护；纯问答、无变化和context-only更新不接续。stop_hook_active与事件去重避免维护自身循环。事件仅保留有界元数据，不保存prompt或模型原文；返回不是语义验收，缺口继续记录UNKNOWN。

每个项目各自使用openspec/config.yaml、specs和changes；OpenSpec CLI固定1.16.1，官方技能全局共享。按dee路由既有任务，OpenSpec保留设计变化和规格同步，archify更新受影响图表，采集器刷新独立证据。任务未结束时不因每次保存触发；没有活动任务就不执行维护。手工改动在下一次项目任务结束时被比较到；hook不监听其他编辑器独立保存。

配置与信任：~/.codex/hooks.json新增本次两个命令hook，保留已有hook和notify。hook通过原生审阅和真实currentHash信任，不关闭信任机制、不使用bypass。脚本入口只引用已测试的买der主工作区，不让生产worker或工作树承担新的常驻服务。
