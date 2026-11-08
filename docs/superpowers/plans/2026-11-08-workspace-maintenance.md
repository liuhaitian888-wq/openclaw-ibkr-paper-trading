# 五项目证据维护与架构融合

目标：用户已指定五个子项目分别维护状态。先用无第三方依赖的证据采集器与持久维护规则，建立自动接续入口；复用 .der/context，明确历史/当前/提案，避免把文件存在、测试通过或代码提交当作部署验收。

范围：kander-cross-display、OpenWorkspace、买der、刷der、der token（源码在der-tokenwatch）。不覆盖正在进行的未提交修改，不删除或移动历史状态、备份或未知文件，不改变交易与外部消息权限。

## 实现与验收
1. 新增 .der/maintenance/workspace.json：五项目、根路径、资料范围、验证命令及自动操作边界；买der登记local-history/cloud-preparation/cloud-monitoring/target-design分期与证据来源。
2. 新增 engineering/workspace_maintenance.py 与 scripts/maintain_workspace.py：只读Git/文件元数据/安全源码依赖，生成各项目独立状态、文件归属、图表依赖缺口、差异、隔离候选及下一步Prompt。所有未知运行/测试/部署均保持UNKNOWN。
3. 输出只写独立工程状态目录，采用文件锁与原子替换；不执行文档中的命令、不读凭据/生产数据库、不递归追踪外部symlink、不覆盖源项目。无提交仓库和脏仓库仍可清点，必须保留来源。
4. 更新本仓库 .der/context，加入阶段分界和实时状态入口；其他项目先生成接续资料，不覆盖其人工内容。持续维护任务通过原生Codex自动化接续，在各项目独立worktree按其规范推进有边界的更新。
5. 回归：不同项目隔离、无提交/脏仓库、保护文件及symlink、跨阶段证据不互相覆盖、图表缺来源不冒充新鲜、幂等写入与并发锁、证据无法核验不升级状态。
6. 仅linked worktree运行完整离线套件和秘密扫描；Git整合到本机主工作区，本机只quick smoke。不为工程维护部署云端业务服务。
7. 交付五项目现状/差距、阶段分界图、持续维护规则及自动化入口。图表确定性校验和浏览器证据与视觉审阅分别记录。
