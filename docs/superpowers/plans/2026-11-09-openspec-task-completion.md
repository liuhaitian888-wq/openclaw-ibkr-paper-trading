# OpenSpec任务收尾维护接入

用户要求：覆盖五项目，保留dee/archify/采集器；仅开发任务完成且有变化时维护，不运行无人使用时的小时/每日检查。用户已授权实现、安装、配置及验证。

实现：固定OpenSpec版本和上游技能来源；五项目规格命名空间与既有证据链对齐。受控Stop hook在登记的项目/worktree内核对内容指纹；无变化立即退出，有变化最多请求一轮有边界的维护接续，继续中的Stop不递归。人工目标、历史/当前/未来和离线/部署/验收仍分开。收尾步骤路由dee→OpenSpec变更/同步→受影响图表archify→适用验证→采集器状态刷新。

文件：新增engineering/task_completion.py、scripts/maintain_task_completion.py、相关隔离回归；更新.der/maintenance规则/注册、AGENTS收尾入口；新增openspec当前规格和集成记录。最终用户级hook只引用已测试的主工作区入口，保留现有secret扫描hook和notify，按原生信任审阅流程启用，不直接伪造trust hash。暂停旧小时automation，不另建每日任务。

验证：纯问答/源码未变不接续；登记项目外不处理；不同项目状态隔离；重复事件/并行结束幂等；维护自身变化不循环；dirty/unborn与工作树定位保留；故障不伪造完成；不读原始聊天或凭据；真实OpenSpec CLI检查；仅linked worktree完整离线套件、秘密扫描、Git整合，主目录quick smoke。配置备份与脱敏回执单独保存。
