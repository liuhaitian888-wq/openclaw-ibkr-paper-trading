# Gateway持续无响应的受限恢复

## 已有故障与原因

Nov7 07:09:54柏林上游断开；旧Java进程后来卡在Restart in progress / Shutdown API，进程仍在，不能触发仅监测退出的systemd Restart。Nov8人工通过唯一ibkr-gateway.service重启，新的Java generation、原生完整回读和独立readback均验证恢复。FD与线程增长已记录，但Java内部卡死根因未证明消除。没有进行第二次故障演练。

## 上游依据与适配

- [IBKR Gateway](https://www.interactivebrokers.com/docs/tws-api/doc/architecture/the-trader-workstation/the-ib-gateway)：每日重启、周度重新认证是不同事件。
- [QuantConnect/IBAutomater](https://github.com/QuantConnect/IBAutomater/blob/master/README.md)：Restarted与Exited分开，调用方重连/重新登录；维护时退避，2FA仍需手机。继续使用现有固定版本。
- [ib_async watchdog](https://github.com/ib-api-reloaded/ib_async/blob/master/ib_async/ibcontroller.py)：超时后探测，再决定应用恢复；本项目只借鉴分层思路，不复制其1100即重启/历史行情探针，不新增竞争API客户端。
- [IBC userguide](https://github.com/IbcAlpha/IBC/blob/master/userguide.md)：软重启、完整认证、外部调度各自负责，避免多个恢复机制同时竞争。本轮未安装IBC。

## 新增机制

`ibkr-gateway-watchdog.timer`每30秒运行User=ibkr/Group=ibkr的oneshot watchdog。Python、虚拟环境、观察、持久化、事件和重启请求全部以ibkr身份执行，经过同一monitoring manifest与内核锁，锁覆盖动作提交。由root保护的polkit规则只允许ibkr对固定ibkr-gateway.service执行restart；没有root解释器、runuser委托或root解析应用JSON的路径。实际Gateway仍由原有单一systemd cgroup与IBAutomater管理，无第二个Gateway owner、无整机重启、无新增密码副本。

普通进程退出继续由原systemd/IBAutomater处理。卡死候选要求：审批恢复policy、服务active、唯一Java generation稳定、原生API心跳持续缺失、现有独立readback的本地API协议握手也失败、至少两个不同时间的独立账户回读失败（最新420秒内），且连续观察至少900秒。独立readback已完成本地API协议握手时，即使远程心跳/账户回读失败也只等待上游。握手缺少字段时不猜测失败。API仍响应而上游1100、周末没tick或行情权限缺失，均不会触发。需要2FA/既有会话冲突/登录失败/身份不符时停止；journal和readback不可读时也不猜测重启。正常重启有15分钟等待窗口。

24小时只保留一次自动重启额度，原子保存STARTED后才返回动作。提交systemd job前重新核对generation/service/独立GATEWAY_RECOVERY_HOLD标记。STARTED或结果不明不重放；10分钟没有恢复则OPERATOR_REQUIRED。恢复需要新generation、原生正确账户/4个end/非dirty心跳、重启后独立完整Paper回读，并稳定60秒。systemctl成功不等于业务恢复。

状态：runtime/gateway-recovery-state.json；批准：runtime/gateway-recovery-policy.json；临时人工停止：runtime/GATEWAY_RECOVERY_HOLD。现有PAUSED/MAINTENANCE与交易测试额度完全独立；仅明确的maintenance-compatible恢复批准允许此基础设施服务在监控维护期观察，不解除交易暂停。要禁用自动修复，可停止/禁用此timer或创建HOLD。不得手工删除STARTED来反复触发。

通过共享reporting.health的GATEWAY_RECOVERY记录新鲜状态，事件gateway-hang进入原有incident/outbox，仅owner私聊。无独立通知直发、不重复演练、不改变账户或保护单。

## 验收限制

完整离线测试覆盖判断、重复快照、上游断开、认证、身份、预算、进程变化、UNKNOWN及稳定回读恢复。线上只核验正常状态无动作和timer持久启用，不制造卡死。未来真实卡死的自动恢复长跑验收仍需自然事件提供证据；这不是已经修复Java内部根因的声明。

## Nov8权限边界修复

最初部署的service未设置User，导致root定时执行ibkr可写的Git脚本、imports和venv。固定systemctl参数不能防止此前已发生的root代码执行；原文“root只可执行固定命令”错误。发现后立即disable/stop timer与watchdog service，保留Gateway运行及审计状态，未发现卡死恢复事件，但这不能证明从未被利用。

当前service明确User/Group=ibkr，NoNewPrivileges=yes、空CapabilityBoundingSet/AmbientCapabilities、RestrictSUIDSGID=yes。root-owned /etc/polkit-1/rules.d/00-openclaw-paper-gateway.rules不导入脚本，仅严格匹配subject.user、action.id、unit、verb；不使用通配符或YES_KEEP。不匹配的ibkr manage-units请求明确NO。该文件、父目录、目标Gateway unit与全部drop-ins必须root所有、ibkr不可写，目标服务User=ibkr且无提升权限的ExecStartPre/Post/Stop钩子；否则保持timer禁用。

该授权允许ibkr直接重启自己拥有的固定Gateway服务，不能管理其他服务、安装/修改unit、重载systemd或运行root代码。应用的15分钟/24小时次数限制用于正常运行，不是对已经攻陷ibkr账户的内核强制限流；后者本就可终止自己拥有的进程。授权矩阵使用pkcheck检查，不调用实际restart；正常Gateway PID必须保持。

部署入口ops/cloud/install_watchdog_permissions.py是一次性人工管理员安装器，不是服务执行目标。管理员通过系统/usr/bin/python3 -I -S运行已审阅代码并提供审阅版本unit/rule SHA256；安装器验证实际Gateway User/Group/NoNewPrivileges、unit/dropin和路径root权限、拒绝特权前缀及额外Exec钩子，备份只写/root下受保护目录。源文件与预期哈希不符即拒绝；临时目标用exclusive create，拒绝符号链接/既有临时文件。安装器不启用timer、不执行restart。先用pkcheck核验固定restart授权、其他单元/动作拒绝，再由管理员启用timer。通用install-host.sh不安装授权规则；缺少规则时service的ConditionPathExists使其保持跳过，不能声称新主机已具备自动恢复。
