## Context
LEAN把Universe数据与入选后的行情订阅分离；免费开源库不是完整免费数据授权。参考OpenBB的Nasdaq/provider抽象和yfinance的有界预设筛选，直接使用标准库适配公开源，不安装大型框架。

## Goals / Non-Goals
实现可随查、可追溯的研究筛选和Paper比较；不提供Live登录、付费snapshot、全市场实时保证，不把季度财务当TTM或历史point-in-time。

## Decisions
- Nasdaq download与日期端点仅在至少3个样本价格一致时借用日期；记录DATE_ONLY_CROSS_ENDPOINT_SAMPLE，不能用于实时执行。
- Yahoo最多两页预设Most Active，标partial；不是全市场。
- SEC固定最近完整自然季度的资产/权益/净利润/营收；逐字段期间、USD、披露编号与缺失，旧资料保留；不计算估值。
- cache→L1/L2/L3研究投影引用共享LAYERS；canonical原数据不被重写。平均量缺失不冒充当日量；流动性研究规则仅price>=5且session_volume>=1e6，其他资格仍待核验。
- BrokerScanner在现有client上单请求/50条/20秒，原生end后取消，TTL180秒，最多12次/小时；回调只写有界内存，原owner落库，STARTED重启转UNKNOWN不重放。
- 外部日期、broker成交时刻、币种、合约映射、type1、新鲜度不齐全时只展示，不计算严格偏差。
- 维护worker每分钟检查新任务，08:25Berlin和工作日18:20NY价量，SEC至少20h；工作日09:40/15:45NY排队三种broker扫描，不补跑历史。

## Risks / Trade-offs
公开接口无SLA且可能限流；403/429持久退避；源缺失/旧数据可见。季度frames不覆盖所有IFRS/自定义标签，filed_at未知；不能宣称样本外历史验证。对齐时间不等于数据一定正确。权限和交易门禁独立。

## Migration Plan
新增表保留原库/旧数据与备份；测试/secret scan后Git部署，单独policy允许只读研究，重载原inbox/paper-safety，不重启Gateway。回滚先停新maintenance timer并恢复代码/manifest，不用旧DB覆盖新事件。
