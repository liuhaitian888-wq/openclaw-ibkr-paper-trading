# der 美股自动交易系统工程手册

版权声明：Copyright (c) 2026 der. All rights reserved. 本项目为专有和保密项目，仅供授权阅读、审阅和协作。未经 der 事先书面许可，任何人不得复制、转发、公开发布、修改、商用、再授权或分享给第三方。完整条款见根目录 `LICENSE`。

本文面向项目用户、维护者和策略开发者，目标是按软件工程方式说明系统边界、运行模式、文件职责、API/安全约束和专业术语。本文不是法律意见，也不是投资建议。

## 目录
- 1. 项目定义和权利说明
- 2. 当前系统状态和运行模式
- 3. 架构总览
- 4. 关键业务语义
- 5. 用户上手示例
- 6. 工程目录与逐文件索引
- 7. Appendix A: API 与安全文件
- 8. Appendix B: 术语表

## 1. 项目定义和权利说明
| 项 | 说明 |
|---|---|
| 项目名 | `der`，本手册中作为项目名和版权声明中的权利标识使用。 |
| 法律身份 | `der` 这个写法本身不自动等于公司、个人实名或注册商标；如果要做更强权利保护，应把 `LICENSE` 中的主体改成个人法定姓名或公司主体，并按目标司法辖区申请版权登记/商标注册。 |
| 授权方式 | 当前采用 proprietary / all rights reserved：未获书面许可，不得复制、转发、公开、修改、商用或再授权。 |
| 协作边界 | 给用户或协作者访问仓库，只代表授权阅读或协作，不代表开源许可。贡献代码的归属和使用权建议另签简单贡献协议。 |
| 投资边界 | 本项目是 IBKR paper trading 自动化实验系统，不是实盘投资建议系统。live trading 当前没有安全启用路径。 |

## 2. 当前系统状态和运行模式
当前菜单已经把常用入口收敛为主菜单 `0/1/9/2`：`0 STOP` 停止，`1 DEV_LOCK` 开发锁，`9 MODE9_RUNTIME` 自动确保 TRADE_LOCK API 并启动 autonomous agent，`2 MORE_TOOLS` 才展开高级/手动工具。

| 模式 | 当前位置 | 是否下单 | 核心含义 |
|---|---|---:|---|
| `0 STOP` | 主菜单 | 否 | 停 API、停 agent、停 pool strategy、清 trade token。 |
| `1 DEV_LOCK` | 主菜单 | 否 | 开发/检查模式，kill switch 开，`ALLOW_PAPER_TRANSMIT=false`。 |
| `9 MODE9_RUNTIME` | 主菜单 | 可能 | 推荐自动化入口：确保 TRADE_LOCK API 后启动 autonomous agent；agent 按节奏监控股票池并调用策略。 |
| `2 MORE_TOOLS` | 主菜单 | 视子项 | 展开高级工具，不是交易锁状态。 |
| `2 TRADE_LOCK` | 高级菜单 | 不直接下单 | 启动 paper API、生成 daily token、允许 paper transmit 的前置状态。 |
| `3 HEALTH` | 高级菜单 | 否 | 查询 API/TWS/token/account readiness。 |
| `4 AUTO_VALIDATE_SEQ` | 高级菜单 | 否 | 生成结构化订单请求并调用 validate endpoint；不创建 TWS 订单。 |
| `5 AUTO_STAGE_SEQ` | 高级菜单 | 是，未传输 | 创建新的 TWS staged order，`transmit=False`，可能需要手动 Transmit 或取消；危险测试项。 |
| `6 AUTO_PAPER_SEQ` | 高级菜单 | 是，自动传输 | 创建新的 transmitted paper order，`transmit=True`；偏一次性测试。 |
| `7 POOL_STRATEGY_PAPER` | 高级菜单 | 可能 | 前台跑 pool strategy；日志显示在当前终端，策略语义和后台相同，若 mode=paper 会提交 paper endpoint。 |
| `8 POOL_STRATEGY_BG` | 高级菜单 | 可能 | 后台长期跑 pool strategy；差异是进程管理和日志位置，不是“只展示”。 |
| `10-22` | 高级菜单 | 多为报告/诊断 | 监控、市场会话、rollout precheck、full paper automation、discovery/news/simulation、account sync、callback dry-run 等。 |

常见误解澄清：`validate` 不是 TWS 虚拟单，它只是 Trading API 的校验请求；`stage` 才会进 TWS 但不 transmit；`paper` 会进 TWS paper 并自动 transmit。`7` 和 `8` 不是展示模式，它们都可能根据 `POOL_STRATEGY_MODE` 调用 validate/stage/paper；前台/后台只影响是否占用当前终端和日志在哪里看。

## 3. 架构总览
| 层 | 主要目录/文件 | 职责 | 禁止事项 |
|---|---|---|---|
| 控制入口 | `scripts/control_trading_mode.command`, `api_service.py` | 启停模式、暴露 HTTP API、统一入口。 | 不绕过 API 直连 broker。 |
| 数据层 | `data/`, `trading/market_data.py`, `trading/ibkr_readonly.py` | 股票池、security master、行情读取、bar/cache。 | 不用延迟/缺失行情做 fast execution。 |
| 研究层 | `openclaw/`, `trading/candidate_research.py`, `research/` | AI/规则候选、报告、paper 证据链。 | AI 不直接写 universe，不直接下单。 |
| 策略层 | `trading/strategy_modules.py`, `trading/strategy.py`, `scripts/run_pool_strategy_module.py` | BUY/SELL/HOLD、组合风险、订单意图。 | 策略不保存 daily token，不连接 TWS 执行。 |
| 风控层 | `trading/risk.py`, `trading/session_policy.py`, `trading/event_risk_control.py` | lock、token、allowlist、金额、风险、时段、事件风险。 | 不因行情缺失放松风险参数。 |
| 执行层 | `trading/service.py`, `trading/tws_paper.py`, `execution/` | validate/stage/paper、TWS paper order、审计。 | live trading 当前禁用。 |
| 审计/展示 | `trading/audit.py`, `reports/`, `dashboard/` | SQLite audit、JSON/MD/HTML 报告、dashboard。 | 不手改 `trading_audit.sqlite3`。 |

## 4. 关键业务语义
| 主题 | 工程解释 |
|---|---|
| `MODE9_RUNTIME` | 当前推荐自动化入口；它会确保 TRADE_LOCK API 后启动 autonomous agent。agent 周期性做 health、universe、quote、risk、strategy、report。 |
| `POOL_STRATEGY_PAPER/BG` | 同一个 pool strategy runner 的前台/后台运行方式；前台便于观察，后台适合长跑。只要 mode=paper 且风控通过，就可能提交 paper order。 |
| `AUTO_VALIDATE_SEQ` | 自动构造测试/候选 payload 并请求 API 校验；不会提交 TWS，不会生成 staged order。 |
| `AUTO_STAGE_SEQ` | 自动构造 payload 并创建 TWS untransmitted order；这不是安全展示，可能在 TWS 留下待手动处理订单。 |
| `AUTO_PAPER_SEQ` | 自动构造 payload 并提交 transmitted paper order；需要 TRADE_LOCK、token、TWS ready 和风控通过。 |
| bracket order | parent limit entry + child stop；parent 通常 `transmit=False`，child stop transmit 时整组提交。不要简单把 parent 改为 `transmit=True`。 |
| single limit order | pool strategy 当前主要提交 single limit order；是否 transmit 由 endpoint mode 决定。 |
| audit ledger | SQLite 本地审计，不是交易路径的一部分；用于证明请求、失败、TWS acknowledgement 和耗时。 |
| generated artifacts | `reports/`, `dashboard/`, `logs/`, `.runtime/` 是运行输出；手册按目录说明，不逐个产物维护。 |

## 5. 用户上手示例
| 场景 | 操作 | 预期结果 |
|---|---|---|
| 只读代码 | 读 `README.md`、本手册、`docs/PROJECT_MAP.md`、`docs/STRATEGY_MODULES.md`。 | 了解边界和主流程，不触碰 TWS。 |
| 本地模拟策略 | `.venv313/bin/python scripts/run_strategy_simulation.py --symbols AAPL,MSFT --steps 12` | 不连接 IBKR，不下单，只验证 quote/cache/bar/signal。 |
| validate 策略 | `.venv313/bin/python scripts/run_pool_strategy_module.py --mode validate --source simulated-scenario --symbols AAPL,MSFT,AMD,INTC,KO,PFE,T,F --steps 18 --batch-size 4` | 调 API validate 或本地模拟路径，不创建 TWS order。 |
| 查看运行状态 | 打开 `reports/autonomous_agent/latest.json`、`logs/autonomous_agent.log`。 | 判断 agent 是否运行、行情是否缺失、是否有订单提交。 |
| 只读 IBKR 行情 | `.venv313/bin/python scripts/check_ibkr_quotes.py --symbols AAPL,MSFT,QQQ --market-data-type 3` | 检查 delayed/read-only quote，不提交订单。 |
| 推荐自动 paper 入口 | 运行 `scripts/control_trading_mode.command`，选择 `9 MODE9_RUNTIME`。 | 自动确保 TRADE_LOCK API 并启动 agent；仍受所有风控限制。 |

## 6. 工程目录与逐文件索引
说明：本节以目录为大类列出 git 已跟踪源文件。`作用` 来自模块 docstring、一级标题或文件命名；`关键函数/类` 通过 AST/脚本函数名抽取，描述保持短句，便于快速定位。

### 根目录
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `.env.example` | 环境变量示例，不能放真实 secret | 无函数；作为文档、配置或数据输入使用 |
| `.gitignore` | Git 忽略规则 | 无函数；作为文档、配置或数据输入使用 |
| `.pre-commit-config.yaml` | pre-commit 与 gitleaks 配置 | 无函数；作为文档、配置或数据输入使用 |
| `AGENTS.md` | Repository Instructions | 无函数；作为文档、配置或数据输入使用 |
| `ARCHITECTURE.md` | Architecture | 无函数；作为文档、配置或数据输入使用 |
| `AUDIT_MODEL.md` | Audit Model | 无函数；作为文档、配置或数据输入使用 |
| `DATA_FEEDS.md` | Data Feeds | 无函数；作为文档、配置或数据输入使用 |
| `LICENSE` | 专有版权与使用限制条款 | 无函数；作为文档、配置或数据输入使用 |
| `README.md` | IBKR Paper Trading Gateway | 无函数；作为文档、配置或数据输入使用 |
| `SECURITY_MODEL.md` | Security Model | 无函数；作为文档、配置或数据输入使用 |
| `TRADING_LOCK.md` | Trading Lock Policy | 无函数；作为文档、配置或数据输入使用 |
| `VALUE_POOL.md` | Value Pool | 无函数；作为文档、配置或数据输入使用 |
| `api_service.py` | Authenticated JSON API for OpenClaw-to-Python trading requests. | 类 `TradingApiHandler`(do_GET, do_POST, log_message, _authenticated, _read_json, _send_json); `main`:命令入口 |
| `main.py` | 项目文件 | `main`:命令入口 |
| `run_dry_run_api.command` | macOS 可双击/终端运行脚本 | 脚本式流程，无显式 shell function |
| `tws_readonly_check.py` | Verify a read-only connection to an IBKR paper-trading TWS session. | 类 `ReadOnlyTwsClient`(__init__, nextValidId, currentTime, managedAccounts, accountSummary, accountSummaryEnd, error); `parse_args`:解析命令行参数; `main`:命令入口 |

### .codex
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `.codex/hooks.json` | JSON 配置或钩子定义 | 无函数；作为文档、配置或数据输入使用 |

### config
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `config/__init__.py` | 项目文件 | 无顶层类/函数，主要为常量、导入或包初始化 |
| `config/autonomous_paper.env.example` | 环境变量示例，不能放真实 secret | 无函数；作为文档、配置或数据输入使用 |
| `config/defaults.py` | 项目文件 | 无顶层类/函数，主要为常量、导入或包初始化 |

### data
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `data/security_master.csv` | 项目数据表/股票池输入 | 无函数；作为文档、配置或数据输入使用 |
| `data/us_equity_universe.csv` | 项目数据表/股票池输入 | 无函数；作为文档、配置或数据输入使用 |

### docs
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `docs/BOOK_BASED_RESEARCH_ROADMAP.md` | Book-Based Quant Research Roadmap | 无函数；作为文档、配置或数据输入使用 |
| `docs/HARDWARE_SOFTWARE_ROADMAP.md` | Hardware And Software Roadmap | 无函数；作为文档、配置或数据输入使用 |
| `docs/NEXT_PHASE_AUTONOMOUS_PAPER_TRADING_PROMPT.md` | Next Phase Prompt: Autonomous IBKR Paper Trading Runtime | 无函数；作为文档、配置或数据输入使用 |
| `docs/PROJECT_HANDOFF_MANUAL_CN.md` | der 美股自动交易系统工程手册 | 无函数；作为文档、配置或数据输入使用 |
| `docs/PROJECT_MAP.md` | Project Map | 无函数；作为文档、配置或数据输入使用 |
| `docs/RESEARCH_CANDIDATE_PIPELINE.md` | Research Candidate Pipeline | 无函数；作为文档、配置或数据输入使用 |
| `docs/STRATEGY_DEBT.md` | Strategy Debt | 无函数；作为文档、配置或数据输入使用 |
| `docs/STRATEGY_FLOW.md` | Strategy Flow | 无函数；作为文档、配置或数据输入使用 |
| `docs/STRATEGY_MODULES.md` | OpenClaw Strategy Modules | 无函数；作为文档、配置或数据输入使用 |
| `docs/YUGE_AUTONOMOUS_TRADING_BRIEF.md` | OpenClaw / IBKR Paper 自动投资系统说明 | 无函数；作为文档、配置或数据输入使用 |

### docs/trading_sessions
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `docs/trading_sessions/01_calendar_and_timezones.md` | Calendar And Timezones | 无函数；作为文档、配置或数据输入使用 |
| `docs/trading_sessions/02_overnight_session.md` | Overnight Session | 无函数；作为文档、配置或数据输入使用 |
| `docs/trading_sessions/03_premarket_session.md` | Premarket Session | 无函数；作为文档、配置或数据输入使用 |
| `docs/trading_sessions/04_regular_session.md` | Regular Session | 无函数；作为文档、配置或数据输入使用 |
| `docs/trading_sessions/05_afterhours_session.md` | Afterhours Session | 无函数；作为文档、配置或数据输入使用 |
| `docs/trading_sessions/06_risk_by_session.md` | Risk By Session | 无函数；作为文档、配置或数据输入使用 |
| `docs/trading_sessions/07_order_types_by_session.md` | Order Types By Session | 无函数；作为文档、配置或数据输入使用 |
| `docs/trading_sessions/08_monitoring_and_recovery.md` | Monitoring And Recovery | 无函数；作为文档、配置或数据输入使用 |
| `docs/trading_sessions/09_autonomous_runtime_runbook.md` | Autonomous Runtime Runbook | 无函数；作为文档、配置或数据输入使用 |
| `docs/trading_sessions/README.md` | Trading Sessions | 无函数；作为文档、配置或数据输入使用 |

### execution
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `execution/__init__.py` | 项目文件 | 无顶层类/函数，主要为常量、导入或包初始化 |
| `execution/paper.py` | 项目文件 | 类 `PaperOrder`; `paper_order`:模块辅助逻辑; `live_order`:模块辅助逻辑 |

### openclaw
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `openclaw/SKILL.md` | IBKR Paper Gateway | 无函数；作为文档、配置或数据输入使用 |
| `openclaw/openclaw_trading_client.py` | OpenClaw client for the Mac Python IBKR paper-trading gateway. | `attach_workflow_step`:模块辅助逻辑; `workflow_error_payload`:模块辅助逻辑; `load_secret`:读取/加载数据; `request_json`:发起请求; `parse_args`:解析命令行参数; `add_order_args`:模块辅助逻辑; `order_payload`:模块辅助逻辑; `preflight_paper_order`:模块辅助逻辑; `exit_code_for_result`:模块辅助逻辑; `add_client_timing`:模块辅助逻辑; `add_execution_mode`:模块辅助逻辑; `require_trade_session_token`:模块辅助逻辑; `_elapsed_ms`:内部辅助; `_utc_now`:内部辅助; `main`:命令入口 |

### ops/launchd
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `ops/launchd/com.openclaw.autonomous-paper.plist` | macOS launchd 后台任务配置 | 定义后台启动命令、环境变量和进程标签 |
| `ops/launchd/com.openclaw.mode9-agent.plist` | macOS launchd 后台任务配置 | 定义后台启动命令、环境变量和进程标签 |

### research
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `research/.gitkeep` | 项目文件 | 无函数 |
| `research/__init__.py` | 项目文件 | 无顶层类/函数，主要为常量、导入或包初始化 |
| `research/full_paper_trial_pipeline.py` | 项目文件 | 类 `FullPaperTrialPipelineConfig`; 类 `FullPaperTrialPipelineReport`; `run_full_pipeline`:运行流程; `main`:命令入口; `_overall_status`:内部辅助; `_artifacts`:内部辅助 |
| `research/guarded_paper_trial_session.py` | 项目文件 | 类 `GuardedPaperTrialSessionConfig`; 类 `GuardedPaperTrialSessionReport`; `run_guarded_session`:运行流程; `main`:命令入口; `_load_or_fetch_health`:内部辅助; `_session_report`:内部辅助; `_session_status`:内部辅助; `_artifacts`:内部辅助; `_write_session_report`:内部辅助 |
| `research/ibkr_mean_reversion_pipeline.py` | 项目文件 | 类 `IbkrMeanReversionPipelineConfig`; 类 `IbkrMeanReversionPipelineReport`; `run_pipeline`:运行流程; `main`:命令入口; `_diagnose_csv`:内部辅助; `_paper_plan`:内部辅助; `_pipeline_report`:内部辅助 |
| `research/ibkr_quote_recorder.py` | 项目文件 | 类 `QuoteSource`(get_quotes); 类 `QuoteRecorderConfig`; 类 `QuoteRecorderReport`; `record_quotes`:记录数据; `main`:命令入口; `_quote_row`:内部辅助; `_new_errors`:内部辅助 |
| `research/mean_reversion_diagnostics.py` | 项目文件 | 类 `MeanReversionDiagnostics`; 类 `PriceDiagnostics`; `diagnose_prices`:模块辅助逻辑; `diagnose_symbol_prices`:模块辅助逻辑; `read_prices_csv`:读取输入; `write_report`:写出文件或结果; `main`:命令入口; `_lag1_adf_t_stat`:内部辅助; `_half_life`:内部辅助; `_hurst_exponent`:内部辅助; `_variance_ratio`:内部辅助; `_latest_z_score`:内部辅助; `_ols_slope`:内部辅助; `_slope_t_stat`:内部辅助; `_sample_variance`:内部辅助; `_round_optional`:内部辅助 |
| `research/paper_candidate_hunt.py` | 项目文件 | 类 `CandidateHuntAttempt`; 类 `PaperCandidateHuntReport`; 类 `PaperCandidateHuntConfig`; `run_candidate_hunt`:运行流程; `main`:命令入口; `_candidate_found`:内部辅助; `_hunt_status`:内部辅助; `_int_value`:内部辅助; `_load_optional_json`:内部辅助 |
| `research/paper_execution_gate.py` | 项目文件 | 类 `PaperExecutionGateReport`; `load_json_object`:读取/加载数据; `build_gate_report`:构建对象/报告; `execute_if_confirmed`:模块辅助逻辑; `write_report`:写出文件或结果; `main`:命令入口; `_selected_candidate`:内部辅助; `_health_block_reason`:内部辅助; `_pre_submit_review_block_reason`:内部辅助; `_load_optional_json`:内部辅助; `_replace_report`:内部辅助; `_request_json`:内部辅助 |
| `research/paper_pre_submit_review.py` | 项目文件 | 类 `PreSubmitReviewItem`; 类 `PaperPreSubmitReview`; `build_pre_submit_review`:构建对象/报告; `write_review_json`:写出文件或结果; `write_review_markdown`:写出文件或结果; `main`:命令入口; `_item`:内部辅助; `_one_share_buy_payload`:内部辅助; `_payload_detail`:内部辅助; `_pnl_detail`:内部辅助; `_status`:内部辅助; `_value`:内部辅助; `_mapping_or_none`:内部辅助; `_load_optional_json`:内部辅助; `_load_last_jsonl`:内部辅助 |
| `research/paper_readiness_report.py` | 项目文件 | 类 `ReadinessItem`; 类 `PaperReadinessReport`; `load_plan`:读取/加载数据; `build_readiness_report`:构建对象/报告; `write_readiness_report`:写出文件或结果; `main`:命令入口; `_readiness_items`:内部辅助; `_operator_steps`:内部辅助 |
| `research/paper_session_runbook.py` | 项目文件 | 类 `RunbookCommand`; 类 `PaperSessionRunbook`; `build_runbook`:构建对象/报告; `write_runbook_json`:写出文件或结果; `write_runbook_markdown`:写出文件或结果; `render_markdown`:渲染输出; `main`:命令入口; `_blockers`:内部辅助; `_runbook_status`:内部辅助; `_summary`:内部辅助; `_operator_steps`:内部辅助; `_commands`:内部辅助; `_artifacts`:内部辅助; `_load_json_object`:内部辅助; `_load_optional_json_object`:内部辅助; `_dedupe`:内部辅助 |
| `research/paper_session_status_page.py` | 项目文件 | `render_status_page`:渲染输出; `write_status_page`:写出文件或结果; `main`:命令入口; `_state_panel`:内部辅助; `_list_panel`:内部辅助; `_ordered_panel`:内部辅助; `_commands_panel`:内部辅助; `_artifacts_panel`:内部辅助; `_status_class`:内部辅助; `_css`:内部辅助; `_load_json_object`:内部辅助 |
| `research/paper_trial_evidence_bundle.py` | 项目文件 | 类 `EvidenceArtifact`; 类 `PaperTrialEvidenceBundle`; `build_evidence_bundle`:构建对象/报告; `write_evidence_bundle`:写出文件或结果; `write_evidence_markdown`:写出文件或结果; `main`:命令入口; `_stage`:内部辅助; `_summary`:内部辅助; `_next_actions`:内部辅助; `_artifacts`:内部辅助; `_artifact_status`:内部辅助; `_artifact_created_at`:内部辅助; `_status`:内部辅助; `_load_optional_json`:内部辅助 |
| `research/paper_trial_preflight_checklist.py` | 项目文件 | 类 `PreflightCheck`; 类 `PaperTrialPreflightChecklist`; `build_preflight_checklist`:构建对象/报告; `write_preflight_json`:写出文件或结果; `write_preflight_markdown`:写出文件或结果; `render_markdown`:渲染输出; `main`:命令入口; `_machine_checks`:内部辅助; `_status`:内部辅助; `_next_allowed_action`:内部辅助; `_manual_confirmations`:内部辅助; `_stop_conditions`:内部辅助; `_commands`:内部辅助; `_rehearsal_is_clean`:内部辅助; `_rehearsal_detail`:内部辅助; `_load_json_object`:内部辅助; `_load_optional_json_object`:内部辅助 |
| `research/paper_trial_readiness_monitor.py` | 项目文件 | 类 `ReadinessMonitorSnapshot`; 类 `PaperTrialReadinessMonitorReport`; 类 `PaperTrialReadinessMonitorConfig`; `run_readiness_monitor`:运行流程; `main`:命令入口; `_monitor_status`:内部辅助; `_load_optional_json_object`:内部辅助 |
| `research/paper_trial_reconciliation.py` | 项目文件 | 类 `ReconciliationItem`; 类 `PaperTrialReconciliationReport`; `build_reconciliation`:构建对象/报告; `write_reconciliation`:写出文件或结果; `main`:命令入口; `_audit_item`:内部辅助; `_tws_order_item`:内部辅助; `_pnl_item`:内部辅助; `_tws_snapshot_contains_key`:内部辅助; `_report`:内部辅助; `_idempotency_from_gate`:内部辅助; `_load_audit_order`:内部辅助; `_load_optional_json_object`:内部辅助; `_load_latest_jsonl`:内部辅助; `_optional_str`:内部辅助 |
| `research/paper_trial_rehearsal.py` | 项目文件 | 类 `PaperTrialRehearsalReport`; 类 `RehearsalQuoteSource`(__init__, get_quotes); `run_rehearsal`:运行流程; `main`:命令入口; `_rehearsal_settings`:内部辅助 |
| `research/paper_trial_report_refresh.py` | 项目文件 | 类 `PaperTrialReportRefreshConfig`; 类 `PaperTrialReportRefreshReport`; `refresh_reports`:刷新状态; `main`:命令入口; 类 `_BlockedQuoteSource`(get_quotes); `_artifacts`:内部辅助; `_load_optional_json`:内部辅助; `_load_latest_jsonl`:内部辅助; `_idempotency_from_gate`:内部辅助; `_load_audit_order`:内部辅助 |
| `research/paper_validation_plan.py` | 项目文件 | 类 `PaperValidationCandidate`; 类 `PaperValidationPlan`; `build_plan`:构建对象/报告; `load_diagnostics`:读取/加载数据; `write_plan`:写出文件或结果; `submit_validate_payloads`:提交请求; `main`:命令入口; `_candidate_from_item`:内部辅助; `_validation_payload`:内部辅助; `_optional_float`:内部辅助; `_request_json`:内部辅助 |
| `research/project_completion_audit.py` | 项目文件 | 类 `CompletionRequirement`; 类 `ProjectCompletionAudit`; `build_completion_audit`:构建对象/报告; `write_completion_audit_json`:写出文件或结果; `write_completion_audit_markdown`:写出文件或结果; `render_markdown`:渲染输出; `main`:命令入口; `_requirement`:内部辅助; `_summary`:内部辅助; `_next_required_evidence`:内部辅助; `_clean_rehearsal`:内部辅助; `_rehearsal_detail`:内部辅助; `_stage`:内部辅助; `_quote_capture_done`:内部辅助; `_validate_done`:内部辅助; `_validate_detail`:内部辅助; `_status`:内部辅助; `_value`:内部辅助; `_load_optional_json`:内部辅助 |
| `research/quote_quality_report.py` | 项目文件 | 类 `SymbolQuoteQuality`; 类 `QuoteQualityReport`; `build_quote_quality_report`:构建对象/报告; `write_quote_quality_json`:写出文件或结果; `write_quote_quality_markdown`:写出文件或结果; `render_markdown`:渲染输出; `main`:命令入口; `_symbol_quality`:内部辅助; `_status`:内部辅助; `_next_actions`:内部辅助; `_read_rows`:内部辅助; `_float`:内部辅助; `_format_optional`:内部辅助 |
| `research/strategy_catalog.py` | 项目文件 | 类 `StrategyCatalogEntry`; 类 `StrategyCatalog`; `build_strategy_catalog`:构建对象/报告; `write_strategy_catalog_json`:写出文件或结果; `write_strategy_catalog_markdown`:写出文件或结果; `render_markdown`:渲染输出; `main`:命令入口 |
| `research/strategy_validation_plan.py` | 项目文件 | 类 `StrategyValidationPlanConfig`; `build_strategy_validation_plan`:构建对象/报告; `main`:命令入口; `_load_quote_rows`:内部辅助; `_group_rows`:内部辅助; `_market_data_from_rows`:内部辅助; `_strategy_signals`:内部辅助; `_candidate_from_signal`:内部辅助; `_validation_payload`:内部辅助; `_row_price`:内部辅助; `_spread_bps`:内部辅助; `_parse_timestamp`:内部辅助; `_optional_float`:内部辅助 |

### risk
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `risk/__init__.py` | 项目文件 | 无顶层类/函数，主要为常量、导入或包初始化 |
| `risk/core.py` | 项目文件 | 类 `OrderRiskConfig`; 类 `OrderRiskDecision`; `validate_order`:校验规则 |

### scripts
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `scripts/approve_candidate_to_universe.py` | Approve a hard-audited candidate report into the local universe CSV. | `parse_args`:解析命令行参数; `main`:命令入口; `read_rows`:读取输入; `write_rows`:写出文件或结果; `upsert_candidate`:模块辅助逻辑; `row_from_report`:模块辅助逻辑 |
| `scripts/audit_ibkr_level1_streaming.py` | Read-only IBKR Level 1 streaming capability audit. | 类 `Level1AuditClient`(__init__, nextValidId, contractDetails, contractDetailsEnd, marketDataType, tickPrice, tickSize, error, run_loop, _row); `main`:命令入口; `_stock_contract`:内部辅助 |
| `scripts/audit_paper_trading_readiness.py` | Audit local readiness for a one-share IBKR paper trial. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/auto_paper_limit_from_quote.py` | Create a paper limit order from the latest IBKR quote. | `parse_args`:解析命令行参数; `main`:命令入口; `latest_quote`:模块辅助逻辑; `order_payload`:模块辅助逻辑; `calculate_limit_price`:模块辅助逻辑; `quote_spread_bps`:模块辅助逻辑; `quote_payload`:模块辅助逻辑; `request_json`:发起请求; `read_required`:读取输入; `read_trade_session_token`:读取输入; `step`:模块辅助逻辑; `elapsed_ms`:模块辅助逻辑 |
| `scripts/benchmark_autonomous_agent_cycle.py` | Benchmark autonomous-agent cycle timings across universe sizes. | `parse_args`:解析命令行参数; `main`:命令入口; `summarize_size`:汇总信息 |
| `scripts/benchmark_ibkr_quote_batches.py` | Benchmark read-only IBKR quote request latency by batch size. | `parse_args`:解析命令行参数; `main`:命令入口; `parse_symbols`:模块辅助逻辑; `parse_batch_sizes`:模块辅助逻辑; `summarize`:汇总信息 |
| `scripts/build_account_reports.py` | Build read-only account, position, open-order, and daily summary reports. | `main`:命令入口; `latest_pnl_row`:模块辅助逻辑; `flatten_open_orders`:模块辅助逻辑; `daily_summary`:模块辅助逻辑; `audit_requests_for_date`:审计状态; `write_json`:写出文件或结果; `float_or_none`:模块辅助逻辑 |
| `scripts/build_ibkr_callback_wiring_audit.py` | Build IBKR callback wiring audit reports. | `main`:命令入口 |
| `scripts/build_market_data_audit_report.py` | 项目文件 | `main`:命令入口; `_read_json`:内部辅助; `_latest_pool_report`:内部辅助; `_code_hits`:内部辅助; `_execution_uses_delayed`:内部辅助; `_runtime_market_data_type`:内部辅助; `_symbols_with_valid_bid_ask`:内部辅助; `_symbols_with_stale_quotes`:内部辅助; `_symbols_with_no_permission`:内部辅助 |
| `scripts/build_market_data_billing_safety.py` | Audit market data billing safety for IBKR reqMktData calls. | `main`:命令入口; `build_report`:构建对象/报告; `audit_file`:审计状态; `enclosing_function`:模块辅助逻辑; `arg_value`:模块辅助逻辑; `literal`:模块辅助逻辑; `symbol_source`:模块辅助逻辑; `market_data_type_nearby`:模块辅助逻辑; `action_taken`:模块辅助逻辑; `env_bool`:模块辅助逻辑; `write_report`:写出文件或结果 |
| `scripts/build_market_data_line_report.py` | 项目文件 | `main`:命令入口; `_read_json`:内部辅助 |
| `scripts/build_mode9_execution_audit.py` | 项目文件 | `main`:命令入口; `_read_json`:内部辅助; `_read_text`:内部辅助; `_bool_env`:内部辅助 |
| `scripts/build_mode9_infrastructure_status.py` | Build unified Mode 9 infrastructure status and audit reports. | `main`:命令入口; `build_all_reports`:构建对象/报告; `seed_current_sqlite_snapshots`:模块辅助逻辑; `ensure_sqlite_tables`:确保前置条件; `build_sqlite_audit`:构建对象/报告; `build_simple_table_report`:构建对象/报告; `build_lot_protection_report`:构建对象/报告; `build_outside_rth_protection_report`:构建对象/报告; `build_fixed_symbol_audit`:构建对象/报告; `build_cycle_audit`:构建对象/报告; `build_infrastructure_status`:构建对象/报告; `feature_status`:模块辅助逻辑; `build_final_audit`:构建对象/报告; `table_exists`:模块辅助逻辑; `read_json`:读取输入; `write_json_report`:写出文件或结果; `write_extra_report`:写出文件或结果; `generated_report_paths`:生成内容; `env_bool`:模块辅助逻辑; `feature_enabled`:模块辅助逻辑; `execution_feature`:模块辅助逻辑; `implementation_state`:模块辅助逻辑; `execution_state`:模块辅助逻辑; `category_for`:模块辅助逻辑; `report_mtime`:模块辅助逻辑; `last_action`:模块辅助逻辑; `remaining_gap`:模块辅助逻辑; `next_step`:模块辅助逻辑; `lot_protection_md`:模块辅助逻辑; `outside_rth_md`:模块辅助逻辑; `fixed_symbol_md`:模块辅助逻辑; `cycle_md`:模块辅助逻辑; `infr |
| `scripts/build_paper_execution_gate.py` | 项目文件 | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/build_paper_pre_submit_review.py` | 项目文件 | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/build_paper_readiness_report.py` | Build a manual paper readiness report from a validate-only plan. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/build_paper_session_runbook.py` | Generate a paper-trial operator runbook from current reports. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/build_paper_session_status_page.py` | Generate a static HTML paper-trial status page. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/build_paper_trial_evidence_bundle.py` | Build a current-state evidence bundle for the paper-trial workflow. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/build_paper_trial_preflight_checklist.py` | Build a one-share IBKR paper-trial preflight checklist. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/build_paper_trial_reconciliation.py` | Build a post-paper-trial reconciliation report. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/build_paper_validation_plan.py` | Build a validate-only paper trading plan from diagnostics JSON. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/build_pool_architecture_audit.py` | Audit whether the six-layer pool architecture is implemented and wired. | `main`:命令入口; `build_reports`:构建对象/报告; `layer_report`:模块辅助逻辑; `membership_records`:模块辅助逻辑; `record`:记录数据; `write_outputs`:写出文件或结果; `markdown`:模块辅助逻辑; `read_universe`:读取输入; `read_json`:读取输入; `sqlite_tables`:模块辅助逻辑; `membership_schema_complete`:模块辅助逻辑 |
| `scripts/build_position_guard_report.py` | 项目文件 | `main`:命令入口 |
| `scripts/build_project_completion_audit.py` | Build the current project completion audit. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/build_quote_quality_report.py` | Build a quote quality report from recorded IBKR quote samples. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/build_security_master.py` | Build the persistent global security master. | `main`:命令入口; `load_nasdaq_trader_url`:读取/加载数据; `load_nasdaq_trader_file`:读取/加载数据; `parse_pipe_text`:模块辅助逻辑; `write_records`:写出文件或结果 |
| `scripts/build_strategy_catalog.py` | Build the strategy module catalog. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/build_strategy_extension_status.py` | Build report-only status for strategy extensions not allowed to trade yet. | `build_status`:构建对象/报告; `latest_agent_report`:模块辅助逻辑; `write_reports`:写出文件或结果; `_bool_env`:内部辅助; `main`:命令入口 |
| `scripts/build_strategy_validation_plan.py` | 项目文件 | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/check_gateway_health.command` | macOS 可双击/终端运行脚本 | 脚本式流程，无显式 shell function |
| `scripts/check_ibkr_quotes.py` | Fetch read-only IBKR quotes and print the normalized cache snapshot. | `parse_args`:解析命令行参数; `main`:命令入口 |
| `scripts/configure_feishu_webhook.command` | macOS 可双击/终端运行脚本 | 脚本式流程，无显式 shell function |
| `scripts/control_trading_mode.command` | macOS 可双击/终端运行脚本 | `vm_ssh_ready`:模块辅助逻辑; `write_trade_token_file`:写出文件或结果; `clear_trade_token_file`:清理状态; `stop_api_if_running`:停止进程/服务; `stop_pool_strategy_if_running`:停止进程/服务; `stop_autonomous_agent_if_running`:停止进程/服务; `default_universe_symbols`:模块辅助逻辑; `api_health_ok`:模块辅助逻辑; `api_health_field`:模块辅助逻辑; `detect_api_url`:模块辅助逻辑; `detect_trade_lock_api_url`:模块辅助逻辑; `load_trade_token_env`:读取/加载数据; `run_gateway_health`:运行流程; `run_auto_sequence`:运行流程; `run_pool_strategy_module`:运行流程; `start_pool_strategy_background`:启动进程/服务; `start_autonomous_agent_background`:启动进程/服务; `set_dev_lock_env`:模块辅助逻辑; `set_trade_lock_env`:模块辅助逻辑; `set_mode9_runtime_env`:模块辅助逻辑; `start_api_background`:启动进程/服务; `ensure_trade_lock_api_background`:确保前置条件; `run_monitor_on`:运行流程; `run_monitor_off`:运行流程; `run_monitor_status`:运行流程; `set_safe_report_env`:模块辅助逻辑; `run_market_session`:运行流程; `run_rollout_precheck`:运行流程; `run_full_paper_autom |
| `scripts/deploy_openclaw_gateway.command` | macOS 可双击/终端运行脚本 | 脚本式流程，无显式 shell function |
| `scripts/diagnose_market_data_channels.py` | Diagnose read-only IBKR market data channels in order. | `parse_args`:解析命令行参数; `main`:命令入口 |
| `scripts/generate_daily_feishu_update.py` | Generate a sanitized daily OpenClaw project update for Feishu. | `parse_args`:解析命令行参数; `read_json`:读取输入; `files_modified_since`:模块辅助逻辑; `universe_summary`:模块辅助逻辑; `latest_pnl`:模块辅助逻辑; `parse_timestamp`:模块辅助逻辑; `api_running`:模块辅助逻辑; `api_health_status`:模块辅助逻辑; `file_age_seconds`:模块辅助逻辑; `top_skip_reasons`:模块辅助逻辑; `explain_zero_submissions`:模块辅助逻辑; `build_status_snapshot`:构建对象/报告; `status_lines`:模块辅助逻辑; `api_running_legacy`:模块辅助逻辑; `observed_date`:模块辅助逻辑; `nth_weekday`:模块辅助逻辑; `last_weekday`:模块辅助逻辑; `easter_date`:模块辅助逻辑; `market_holidays`:模块辅助逻辑; `next_market_day`:模块辅助逻辑; `market_note`:模块辅助逻辑; `fmt_number`:模块辅助逻辑; `mask_identifier`:模块辅助逻辑; `sector_lines`:模块辅助逻辑; `pnl_lines`:模块辅助逻辑; `build_report`:构建对象/报告; `main`:命令入口 |
| `scripts/generate_strategy_dashboard.py` | Generate a local static strategy dashboard. | `parse_args`:解析命令行参数; `main`:命令入口 |
| `scripts/hunt_paper_candidate.py` | Hunt for a validate payload without paper order submission. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/list_tws_orders.py` | List current TWS open orders and recent executions. | 类 `ReadOnlyOrdersClient`(__init__, nextValidId, error, openOrder, openOrderEnd, completedOrder, completedOrdersEnd, orderStatus, execDetails, execDetailsEnd, +1); `_number`:内部辅助; `parse_args`:解析命令行参数; `main`:命令入口; `read_tws_orders`:读取输入 |
| `scripts/monitor_paper_trial_readiness.py` | Safely monitor readiness for a one-share IBKR paper trial. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/record_account_pnl.py` | Record read-only IBKR paper account P&L samples over time. | 类 `PnlSample`(as_dict); 类 `AccountPnlClient`(__init__, nextValidId, managedAccounts, accountSummary, accountSummaryEnd, pnl, updatePortfolio, error, run_loop, sample); `parse_args`:解析命令行参数; `main`:命令入口; `append_outputs`:追加记录; `_float_or_none`:内部辅助; `_first_not_none`:内部辅助; `_sum_available`:内部辅助 |
| `scripts/record_ibkr_quotes.py` | Record read-only IBKR quote snapshots to CSV for research. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/refresh_paper_trial_reports.py` | Refresh all paper-trial reports in safe order. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/refresh_position_protection_test_result.py` | Refresh position protection test result from read-only TWS open-order output. | `refresh_result`:刷新状态; `_find_order`:内部辅助; `main`:命令入口 |
| `scripts/refresh_strategy_dashboard.py` | Regenerate the static strategy dashboard on a timer. | `parse_args`:解析命令行参数; `main`:命令入口 |
| `scripts/rehearse_paper_trial_workflow.py` | Run a simulated ready-environment rehearsal of the paper-trial workflow. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/review_candidate_report.py` | Build a Python hard-audit report from an OpenClaw/Gemini candidate draft. | `parse_args`:解析命令行参数; `main`:命令入口; `fetch_quote`:拉取数据 |
| `scripts/review_t_duplicate_stops.py` | 项目文件 | `main`:命令入口 |
| `scripts/run_auto_open_discovery_news_simulation.py` | Run auto-open discovery/news/dynamic-pool/local-simulation pipeline. | `main`:命令入口 |
| `scripts/run_auto_order_sequence.py` | Run an automatic module-style order sequence from current IBKR quotes. | `parse_args`:解析命令行参数; `main`:命令入口; `fetch_quotes`:拉取数据; `require_trade_lock`:模块辅助逻辑; `evaluate_symbol`:评估决策; `calculate_limit_price`:模块辅助逻辑; `quote_spread_bps`:模块辅助逻辑; `quote_payload`:模块辅助逻辑; `endpoint_for_mode`:模块辅助逻辑; `request_json`:发起请求; `parse_symbols`:模块辅助逻辑; `read_required`:读取输入; `read_trade_session_token`:读取输入; `write_report`:写出文件或结果; `utc_now`:模块辅助逻辑; `elapsed_ms`:模块辅助逻辑 |
| `scripts/run_autonomous_paper_runtime.py` | 项目文件 | `main`:命令入口; `_replace`:内部辅助 |
| `scripts/run_autonomous_trading_agent.py` | Run the autonomous paper trading supervisor loop. | 类 `AgentCycle`(as_dict); `parse_args`:解析命令行参数; `main`:命令入口; `run_cycle`:运行流程; `failed_cycle`:模块辅助逻辑; `build_quote_readiness`:构建对象/报告; `evaluate_lifecycle_state`:评估决策; `lifecycle`:模块辅助逻辑; `sync_canonical_pool_state`:模块辅助逻辑; `pool_manager_records`:模块辅助逻辑; `quote_payloads_by_symbol`:模块辅助逻辑; `should_run_strategy_now`:模块辅助逻辑; `next_check_at`:模块辅助逻辑; `cycle_markdown`:模块辅助逻辑; `build_streaming_source`:构建对象/报告; `streaming_report_payload`:模块辅助逻辑; `select_monitor_symbols`:筛选对象; `fetch_quotes`:拉取数据; `update_market_state`:更新状态; `build_research_tasks`:构建对象/报告; `process_candidate_inbox`:模块辅助逻辑; `run_strategy_once`:运行流程; `mode9_buy_freeze`:模块辅助逻辑; `env_bool`:模块辅助逻辑; `request_json`:发起请求; `read_required`:读取输入; `append_jsonl`:追加记录; `write_json`:写出文件或结果; `write_text`:写出文件或结果; `utc_now`:模块辅助逻辑; `elapsed_ms`:模块辅助逻辑 |
| `scripts/run_full_paper_automation.py` | Run staged Mode 9 full paper automation enablement. | `main`:命令入口; `run_once`:运行流程; `configure_full_paper_env`:模块辅助逻辑; `build_preflight`:构建对象/报告; `build_trade_pool_decisions`:构建对象/报告; `build_paper_buy_report`:构建对象/报告; `build_options_execution_report`:构建对象/报告; `build_gap_escape_execution_result`:构建对象/报告; `build_full_paper_run_report`:构建对象/报告; `build_final_audit`:构建对象/报告; `write_full_report`:写出文件或结果; `write_final_audit`:写出文件或结果; `insert_cycle`:模块辅助逻辑; `insert_market_session_event`:模块辅助逻辑; `markdown_full_report`:模块辅助逻辑; `markdown_final_audit`:模块辅助逻辑; `env_bool`:模块辅助逻辑; `now`:模块辅助逻辑 |
| `scripts/run_full_paper_rollout.py` | Run gated PAPER-only Mode 9 rollout stages. | `main`:命令入口; `configure_safe_env`:模块辅助逻辑; `stage0_preflight`:模块辅助逻辑; `stage1_readiness`:模块辅助逻辑; `current_position_and_open_order_symbols`:模块辅助逻辑; `market_session_blocks_quote_wait`:模块辅助逻辑; `stage2_protective_repair`:模块辅助逻辑; `run_record_account_pnl_once`:运行流程; `stage2_precheck`:模块辅助逻辑; `stage2_blocked`:模块辅助逻辑; `build_stage2_result`:构建对象/报告; `protection_after_readback`:模块辅助逻辑; `write_position_protection_execution_result`:写出文件或结果; `write_stage`:写出文件或结果; `write_summary`:写出文件或结果; `stage_md`:模块辅助逻辑; `failed_checks`:模块辅助逻辑; `read_json`:读取输入; `env_bool`:模块辅助逻辑; `now`:模块辅助逻辑 |
| `scripts/run_full_paper_trial_pipeline.py` | Run the full read-only-to-paper-gate trial pipeline. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/run_guarded_paper_trial_session.py` | Run the guarded IBKR paper-trial session workflow. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/run_ibkr_callback_dry_run.py` | Run read-only REAL_IBKR callback bridge dry-run. | `main`:命令入口 |
| `scripts/run_ibkr_mean_reversion_pipeline.py` | Record read-only IBKR quotes and run mean-reversion diagnostics. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/run_mean_reversion_diagnostics.py` | Run lightweight mean-reversion diagnostics on a CSV price file. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/run_mode9_report_only_infrastructure_cycle.py` | Refresh Mode 9 report-only infrastructure without submitting orders. | `main`:命令入口; `run_report_only_cycle`:运行流程; `capture`:模块辅助逻辑; `summarize`:汇总信息; `mark_state_usage`:模块辅助逻辑; `write_and_return_billing_safety`:写出文件或结果 |
| `scripts/run_pool_strategy_module.py` | Run the first modular pool strategy against validate/stage/paper endpoints. | 类 `ScenarioQuoteSource`(__init__, get_quotes); `parse_args`:解析命令行参数; `main`:命令入口; `run_module`:运行流程; `build_source`:构建对象/报告; `build_universe_selection`:构建对象/报告; `monitor_symbols_from_records`:监控状态; `scenario_price_series`:模块辅助逻辑; `default_price_series`:模块辅助逻辑; `endpoint_for_mode`:模块辅助逻辑; `submit_order`:提交请求; `order_payload`:模块辅助逻辑; `decision_payload`:模块辅助逻辑; `compact_scan_report`:模块辅助逻辑; `pnl_snapshot`:模块辅助逻辑; `realized_pnl_for_decision`:模块辅助逻辑; `require_gateway_mode`:模块辅助逻辑; `request_json`:发起请求; `parse_symbols`:模块辅助逻辑; `parse_list`:模块辅助逻辑; `read_required`:读取输入; `read_trade_session_token`:读取输入; `payload_without_token`:模块辅助逻辑; `quote_payload`:模块辅助逻辑; `write_report`:写出文件或结果; `write_dashboard`:写出文件或结果; `elapsed_ms`:模块辅助逻辑 |
| `scripts/run_position_protection.py` | 项目文件 | `main`:命令入口 |
| `scripts/run_realtime_account_sync.py` | Run realtime account state bus/snapshot/BUY-SELL sync reports. | `main`:命令入口 |
| `scripts/run_strategy_simulation.py` | Run a local paper-only strategy simulation. | `parse_args`:解析命令行参数; `main`:命令入口 |
| `scripts/send_daily_feishu_update.command` | macOS 可双击/终端运行脚本 | 脚本式流程，无显式 shell function |
| `scripts/send_daily_feishu_update_if_due.command` | macOS 可双击/终端运行脚本 | `log`:模块辅助逻辑 |
| `scripts/send_feishu_report.py` | Send a Markdown/text report to a Feishu custom bot webhook. | `parse_args`:解析命令行参数; `load_env_file`:读取/加载数据; `sanitize_text`:模块辅助逻辑; `clean_display_text`:模块辅助逻辑; `report_to_post_content`:模块辅助逻辑; `build_text_payload`:构建对象/报告; `build_post_payload`:构建对象/报告; `sign_payload`:模块辅助逻辑; `main`:命令入口 |
| `scripts/serve_live_dashboard.py` | Serve the IBKR read-only dashboard from localhost. | `parse_args`:解析命令行参数; `parse_symbols`:模块辅助逻辑; 类 `LiveDataCache`(__init__, get, _with_cache_status); `fetch_data`:拉取数据; `next_client_id`:模块辅助逻辑; `build_system_status`:构建对象/报告; `fetch_trading_api_health`:拉取数据; `token_present`:模块辅助逻辑; `token_present_file_from_env`:模块辅助逻辑; `token_present_file`:模块辅助逻辑; `read_text_file`:读取输入; `make_handler`:模块辅助逻辑; `main`:命令入口 |
| `scripts/start_dev_lock_api.command` | macOS 可双击/终端运行脚本 | 脚本式流程，无显式 shell function |
| `scripts/start_live_dashboard.command` | macOS 可双击/终端运行脚本 | 脚本式流程，无显式 shell function |
| `scripts/start_trade_lock_api.command` | macOS 可双击/终端运行脚本 | 脚本式流程，无显式 shell function |
| `scripts/stop_trading_api.command` | macOS 可双击/终端运行脚本 | 脚本式流程，无显式 shell function |
| `scripts/submit_single_paper_from_readiness.py` | Gate a single explicit paper limit order from readiness artifacts. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `scripts/test_ibkr_tick_by_tick.py` | Sample IBKR tick-by-tick read-only market data. | 类 `TickByTickClient`(__init__, nextValidId, error, tickByTickAllLast, tickByTickBidAsk, tickByTickMidPoint, _append, _event_time); `parse_args`:解析命令行参数; `main`:命令入口; `stock_contract`:模块辅助逻辑 |
| `scripts/test_streaming_quotes.py` | Read-only smoke test for IBKR Level I streaming quotes. | `parse_args`:解析命令行参数; `main`:命令入口 |

### strategies
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `strategies/__init__.py` | 项目文件 | 无顶层类/函数，主要为常量、导入或包初始化 |
| `strategies/base.py` | 项目文件 | 类 `MarketData`(last, midpoint); 类 `PortfolioState`(position_for); 类 `Signal` |
| `strategies/dual_ma.py` | 项目文件 | 类 `DualMovingAverageStrategy`(__init__, generate_signal) |
| `strategies/grid.py` | 项目文件 | 类 `GridStrategy`(__init__, generate_signal) |
| `strategies/mean_reversion.py` | 项目文件 | 类 `ZScoreMeanReversionStrategy`(__init__, generate_signal) |
| `strategies/ml_baseline.py` | 项目文件 | 类 `LightGbmStyleBaselineStrategy`(__init__, generate_signal) |

### tests
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `tests/__init__.py` | Tests for the trading safeguards. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `tests/test_account_reports.py` | 项目文件 | 类 `AccountReportsTests`(test_daily_summary_counts_open_orders) |
| `tests/test_account_state_manager.py` | 项目文件 | 类 `AccountStateManagerTests`(test_state_schema_dataclasses_have_required_fields, test_stale_state_detection, test_account_state_report_generation_from_cached_inputs, test_streaming_quote_cache_feeds_account_state_manager, test_quote_state_splits_bid_ask_last_and_use_case_threshold, test_sell_execution_requires_fresh_bid_and_buy_requires_fresh_ask, test_reports_may_use_last_but_execution_blocks_without_bid, test_streaming_bid_ask_gap_uses_market_session_classifier, test_execution_requires_force_refresh_and_blocks_failure, test_require_fresh_state_for_execution_blocks_stale_state, +2) |
| `tests/test_api_service.py` | 项目文件 | 类 `FakeSettings`; 类 `FakeService`(__init__, submit_limit); 类 `FailingService`(submit_limit); 类 `CapturingHandler`(__init__, send_response, send_header, end_headers); 类 `ApiServiceTests`(test_stage_limit_route_submits_without_transmission, test_paper_limit_route_submits_with_transmission, test_error_response_includes_workflow_step) |
| `tests/test_auto_open_pipeline.py` | 项目文件 | 类 `AutoOpenPipelineTests`(test_defaults_enable_discovery_news_pool_intent_and_simulation_safely, test_unavailable_ibkr_news_does_not_fail_pipeline, test_scanner_news_and_fast_guidance_cannot_submit_orders, test_candidates_pass_pool_layers_and_have_scores, test_simulation_creates_only_local_simulated_orders, test_paper_execution_interface_defaults_false, test_safety_config_rejects_real_execution_flags, test_buy_sell_share_same_cycle_snapshot_refs) |
| `tests/test_autonomous_agent.py` | 项目文件 | 类 `AutonomousAgentTests`(lifecycle_for, test_mode9_market_closed_waits_without_execution, test_mode9_no_quotes_waits_without_execution, test_mode9_stale_ask_waits_without_execution, test_mode9_fresh_quotes_become_paper_ready, test_mode9_disconnected_waits_without_execution, test_mode9_ready_quotes_but_order_gate_blocked_by_risk, test_mode9_api_failure_is_recoverable_api_not_ready, test_quote_readiness_requires_fresh_bid_and_ask, test_waiting_lifecycle_states_do_not_run_strategy, +7) |
| `tests/test_autonomous_runtime.py` | 项目文件 | 类 `FakeScanner`(__init__, scan_once); 类 `AutonomousRuntimeTests`(test_kill_switch_blocks_runtime, test_tws_health_failure_pauses_runtime, test_runtime_submits_session_approved_bracket_order, test_runtime_blocks_event_without_protective_stop, test_live_order_remains_disabled); `_runtime`:内部辅助; `_ready_health`:内部辅助; `_event`:内部辅助 |
| `tests/test_candidate_research.py` | 项目文件 | 类 `CandidateResearchTests`(test_hard_audit_approves_structured_candidate, test_hard_audit_rejects_low_confidence, test_hard_audit_rejects_existing_universe_symbol, test_approval_upserts_candidate_row); `candidate`:模块辅助逻辑 |
| `tests/test_daily_feishu_update.py` | 项目文件 | 类 `DailyFeishuUpdateTests`(test_status_lines_include_repair_mode_and_blocked_reason, test_zero_submission_explanation_names_repair_state) |
| `tests/test_dashboard.py` | 项目文件 | 类 `DashboardTests`(test_dashboard_contains_core_sections, test_dashboard_can_auto_refresh_and_show_missing_symbols) |
| `tests/test_event_risk_control.py` | 项目文件 | 类 `EventRiskControlTests`(test_high_event_blocks_buy_and_requires_outside_rth_protection) |
| `tests/test_event_router.py` | 项目文件 | 类 `EventRouterTests`(test_routes_report_only_actions_from_risk_reports) |
| `tests/test_full_paper_trial_pipeline.py` | 项目文件 | 类 `PullbackQuoteSource`(__init__, get_quotes); 类 `FullPaperTrialPipelineTests`(test_full_pipeline_writes_all_reports_without_submitting_paper) |
| `tests/test_gap_escape_manager.py` | 项目文件 | 类 `GapEscapeManagerTests`(test_trigger_when_bid_below_stop_limit_and_marketable_lmt_price, test_blocked_when_quote_stale, test_blocked_when_spread_too_wide); `_settings`:内部辅助 |
| `tests/test_gap_risk_manager.py` | 项目文件 | 类 `GapRiskManagerTests`(test_worst_gap_loss_and_max_notional, test_over_budget_recommends_reduce_or_hedge, test_event_risk_increases_gap_shock) |
| `tests/test_guarded_paper_trial_session.py` | 项目文件 | 类 `PullbackQuoteSource`(__init__, get_quotes); `guarded_config`:模块辅助逻辑; 类 `GuardedPaperTrialSessionTests`(test_blocks_before_pipeline_when_environment_is_not_ready, test_ready_environment_runs_full_pipeline_without_paper_submit_by_default) |
| `tests/test_ibkr_callback_bridge.py` | 项目文件 | 类 `IbkrCallbackBridgeTests`(test_data_bus_architecture_has_four_logical_buses, test_bootstrap_loads_cache_then_waits_for_real_ibkr, test_real_ibkr_callback_writes_to_bus_and_replaces_cache, test_older_real_ibkr_event_is_stored_but_does_not_overwrite_newer, test_stale_field_remains_subscribed_and_new_event_returns_fresh, test_ask_freshness_independent_from_other_domains, test_dry_run_uses_no_orders_or_snapshots, test_wiring_audit_reports_bridge_separately_from_real_events) |
| `tests/test_ibkr_callback_wiring_audit.py` | 项目文件 | 类 `IbkrCallbackWiringAuditTests`(setUp, test_report_distinguishes_callback_registration_from_freshness, test_report_distinguishes_real_ibkr_simulation_fixture_and_none_sources, test_stale_ask_does_not_mark_bus_failed, test_stale_ask_blocks_real_paper_buy_but_not_local_simulation, test_safety_flags_remain_zero_or_false) |
| `tests/test_ibkr_mean_reversion_pipeline.py` | 项目文件 | 类 `OscillatingQuoteSource`(__init__, get_quotes); 类 `IbkrMeanReversionPipelineTests`(test_pipeline_records_quotes_and_writes_diagnostics) |
| `tests/test_ibkr_quote_recorder.py` | 项目文件 | 类 `FakeQuoteSource`(__init__, get_quotes); 类 `IbkrQuoteRecorderTests`(test_record_quotes_writes_research_csv_and_report, test_record_quotes_requires_symbols) |
| `tests/test_ibkr_readonly.py` | 项目文件 | 类 `IbkrReadOnlyQuoteClientTests`(test_tick_callbacks_build_normalized_quote, test_close_price_can_create_quote_when_last_is_missing, test_delayed_tick_callbacks_build_normalized_quote, test_simulation_source_can_build_ibkr_readonly_provider, test_stock_contract_can_target_iex, test_parallel_source_chunks_symbols_without_tws_connection) |
| `tests/test_ibkr_streaming.py` | 项目文件 | 类 `FakeStreamingClient`(__init__, connect, run_loop, reqMarketDataType, reqMktData, cancelMktData, isConnected, disconnect); 类 `IbkrStreamingQuoteTests`(test_req_mkt_data_uses_streaming_snapshot_disabled, test_more_than_max_symbols_is_truncated_safely, test_tick_price_updates_quote_cache, test_bid_ask_midpoint_can_create_usable_quote, test_stale_quote_is_detected, test_shutdown_cancels_subscriptions, test_streaming_errors_are_recorded_per_symbol, test_streaming_module_does_not_call_order_apis) |
| `tests/test_market_data_billing_safety.py` | 项目文件 | 类 `MarketDataBillingSafetyTests`(test_snapshot_true_is_blocked_for_automatic_quote_acquisition, test_missing_quote_does_not_trigger_paid_or_regulatory_snapshot, test_delayed_and_frozen_data_cannot_pass_execution_readiness, test_live_fresh_bid_and_ask_can_pass_quote_readiness, test_reports_can_use_last_fallback_but_execution_cannot, test_market_data_billing_safety_report_schema, test_force_refresh_dry_run_submits_and_cancels_no_orders) |
| `tests/test_market_quote_crosscheck.py` | 项目文件 | 类 `MarketQuoteCrosscheckTests`(test_closed_market_missing_bid_ask_is_normal, test_active_market_missing_bid_ask_is_quote_feed_problem, test_subscription_reason_is_subscription_problem, test_paper_automation_sqlite_tables_exist) |
| `tests/test_market_session.py` | 项目文件 | 类 `MarketSessionTests`(test_regular_session_expects_live_bid_ask, test_premarket_session_expects_live_bid_ask, test_afterhours_session_expects_live_bid_ask, test_after_afterhours_close_blocks_quote_wait, test_weekend_blocks_quote_wait, test_holiday_blocks_quote_wait, test_early_close_active_then_closed_after_1300, test_symbol_rows_report_contract_details_when_provided, test_contract_details_closed_overrides_calendar_open_for_symbol, test_unknown_calendar_blocks_execution_when_verified_calendar_required, +2) |
| `tests/test_mean_reversion_diagnostics.py` | 项目文件 | 类 `MeanReversionDiagnosticsTests`(test_oscillating_series_is_research_candidate, test_trending_series_is_rejected, test_csv_reader_groups_prices_by_symbol, test_write_report_creates_json_artifact) |
| `tests/test_mode9_infrastructure_status.py` | 项目文件 | 类 `Mode9InfrastructureStatusTests`(test_feature_status_schema_contains_required_fields, test_sqlite_tables_exist_after_ensure) |
| `tests/test_mode9_report_only_infrastructure_cycle.py` | 项目文件 | 类 `Mode9ReportOnlyInfrastructureCycleTests`(test_cycle_is_report_only_and_calls_core_modules) |
| `tests/test_monitoring_line_control.py` | 项目文件 | 类 `MonitoringLineControlTests`(test_monitor_on_keeps_safety_flags_conservative, test_market_session_and_rollout_precheck_commands_exist, test_full_paper_automation_command_keeps_hard_safety_flags, test_mode9_runtime_ensures_trade_lock_before_agent, test_interactive_menu_folds_advanced_controls, test_mode9_runtime_keeps_hard_safety_flags, test_mode9_runtime_reuses_existing_token_or_restarts_api) |
| `tests/test_openclaw_client.py` | 项目文件 | 类 `OpenClawTradingClientTests`(test_paper_submitted_is_success, test_pending_confirmation_is_not_reported_as_success, test_rejected_order_is_not_reported_as_success, test_validation_rejection_uses_rejected_exit_code, test_unknown_order_status_is_not_reported_as_success, test_client_timing_is_added_to_result, test_preflight_rejects_non_trade_lock, test_preflight_rejects_tws_not_ready, test_api_connection_failure_reports_client_http, test_fast_paper_limit_skips_client_preflight) |
| `tests/test_options_hedge_planner.py` | 项目文件 | 类 `OptionsHedgePlannerTests`(test_not_triggered_below_notional_threshold, test_triggered_above_notional_threshold, test_quantity_under_100_blocks_single_stock_option_hedge); `_settings`:内部辅助 |
| `tests/test_order_intents_and_pnl_ledger.py` | 项目文件 | 类 `OrderIntentAndPnlLedgerTests`(test_buy_intent_requires_buy_side, test_options_plan_cannot_be_submitted_in_intent_task, test_structured_pnl_tables_have_queryable_columns, test_intents_route_to_split_ledgers_without_submissions) |
| `tests/test_paper_candidate_hunt.py` | 项目文件 | 类 `SequenceQuoteSource`(__init__, get_quotes); 类 `PaperCandidateHuntTests`(test_hunt_stops_when_validate_payload_is_found, test_hunt_reports_static_quotes_without_forcing_order) |
| `tests/test_paper_environment_audit.py` | 项目文件 | `make_settings`:模块辅助逻辑; 类 `PaperEnvironmentAuditTests`(test_ready_report_requires_trade_lock_and_tws_paper_account, test_dry_run_without_health_is_blocked_with_next_steps, test_unready_tws_blocks_even_when_local_settings_are_paper) |
| `tests/test_paper_execution_gate.py` | 项目文件 | 类 `PaperExecutionGateTests`(test_build_gate_report_selects_approved_one_share_candidate, test_gate_blocks_without_ready_readiness, test_execute_requires_confirmation_phrase, test_execute_posts_paper_limit_after_health_passes, test_execute_accepts_matching_pre_submit_review, test_execute_blocks_stale_pre_submit_review, test_execute_blocks_pre_submit_review_payload_mismatch) |
| `tests/test_paper_pre_submit_review.py` | 项目文件 | 类 `PaperPreSubmitReviewTests`(test_ready_review_requires_gate_order_snapshot_and_pnl, test_open_order_blocks_review) |
| `tests/test_paper_readiness_report.py` | 项目文件 | 类 `PaperReadinessReportTests`(test_report_requires_validate_before_paper, test_report_marks_manual_review_after_all_validates_pass, test_load_and_write_report_round_trip) |
| `tests/test_paper_session_runbook.py` | 项目文件 | 类 `PaperSessionRunbookTests`(test_blocked_runbook_lists_blockers_and_safe_commands, test_ready_runbook_includes_validate_and_explicit_paper_commands, test_markdown_and_json_are_written) |
| `tests/test_paper_session_status_page.py` | 项目文件 | 类 `PaperSessionStatusPageTests`(test_render_status_page_contains_core_sections, test_write_status_page_creates_html_file) |
| `tests/test_paper_trial_evidence_bundle.py` | 项目文件 | 类 `PaperTrialEvidenceBundleTests`(test_blocked_environment_classifies_before_paper_window, test_submitted_without_reconciliation_needs_reconciliation, test_ready_execution_gate_classifies_explicit_paper_submit, test_reconciled_stage_requires_reconciled_report, test_reviewed_gate_reconciled_stage_does_not_require_guarded_session_submission, test_writers_create_json_and_markdown) |
| `tests/test_paper_trial_preflight_checklist.py` | 项目文件 | 类 `PaperTrialPreflightChecklistTests`(test_ready_checklist_allows_validate_only_window, test_blocked_audit_blocks_real_ibkr_window, test_missing_rehearsal_requires_attention_after_ready_audit) |
| `tests/test_paper_trial_readiness_monitor.py` | 项目文件 | 类 `PaperTrialReadinessMonitorTests`(test_monitor_waits_without_quote_or_order_side_effects, test_monitor_stops_when_preflight_becomes_validate_ready) |
| `tests/test_paper_trial_reconciliation.py` | 项目文件 | 类 `PaperTrialReconciliationTests`(test_missing_gate_is_no_paper_submission, test_unsubmitted_gate_is_no_paper_submission, test_submitted_gate_reconciles_required_readbacks, test_submitted_gate_without_tws_readback_is_incomplete, test_write_reconciliation_creates_json) |
| `tests/test_paper_trial_rehearsal.py` | 项目文件 | 类 `PaperTrialRehearsalTests`(test_rehearsal_runs_ready_path_without_ibkr_or_orders) |
| `tests/test_paper_trial_report_refresh.py` | 项目文件 | 类 `FailingQuoteSource`(get_quotes); 类 `PaperTrialReportRefreshTests`(test_refresh_blocked_environment_writes_reports_without_quote_source, test_refresh_reads_audit_record_for_submitted_gate_reconciliation) |
| `tests/test_paper_validation_plan.py` | 项目文件 | 类 `PaperValidationPlanTests`(test_negative_z_candidate_creates_buy_validate_payload, test_positive_z_candidate_is_watch_only_for_long_module, test_rejected_diagnostics_do_not_create_payload, test_load_and_write_plan_round_trip) |
| `tests/test_pool_architecture_audit.py` | 项目文件 | 类 `PoolArchitectureAuditTests`(test_audit_reports_six_layer_runtime_wired_but_execution_gated) |
| `tests/test_pool_manager.py` | 项目文件 | 类 `PoolManagerTests`(test_builds_six_layers_and_forces_positions_into_monitor_pool) |
| `tests/test_pool_state.py` | 项目文件 | 类 `PoolStateTests`(manager, add_ready_watch, test_normal_l1_to_l6_promotion, test_ineligible_symbol_remains_outside_l2, test_stale_ask_blocks_l5_to_l6, test_market_closed_blocks_unsupported_execution, test_spread_widening_demotes_watch_pool_symbol, test_expired_signal_is_removed, test_expired_news_event_cannot_authorize_trade, test_duplicate_order_is_blocked, +7) |
| `tests/test_position_protection.py` | 项目文件 | 类 `PositionProtectionTests`(_fresh_ok, test_missing_stop_detection, test_underprotected_detection, test_fully_protected_detection, test_overprotected_detection, test_duplicate_stop_detection, test_protective_sell_stop_quantity_calculation, test_stop_price_normalization, test_current_price_hard_stop_when_market_below_avg_stop, test_missing_stop_generates_repair_proposal, +30); `_settings`:内部辅助; `_guard_row`:内部辅助; `_stop_config`:内部辅助 |
| `tests/test_position_protection_test_result_refresh.py` | 项目文件 | 类 `PositionProtectionTestResultRefreshTests`(test_plain_stp_outside_rth_false_is_success_with_warning) |
| `tests/test_price_normalizer.py` | 项目文件 | 类 `PriceNormalizerTests`(test_buy_limit_floors_to_cent, test_sell_limit_ceils_to_cent, test_sell_stop_floors_to_valid_protective_stop, test_buy_stop_ceils_to_cent, test_custom_tick_size) |
| `tests/test_profit_protection_reports.py` | 项目文件 | 类 `ProfitProtectionReportTests`(test_profit_lock_take_profit_and_trailing_are_report_only) |
| `tests/test_project_completion_audit.py` | 项目文件 | 类 `ProjectCompletionAuditTests`(test_current_blocked_state_is_not_complete, test_reconciled_stage_can_complete_audit, test_writers_create_audit_artifacts, test_validate_attempt_without_payload_is_not_complete) |
| `tests/test_quote_quality_report.py` | 项目文件 | 类 `QuoteQualityReportTests`(test_static_last_prices_are_flagged, test_moving_prices_are_usable, test_writers_create_artifacts, _write_rows) |
| `tests/test_realtime_account_sync.py` | 项目文件 | 类 `RealtimeAccountSyncTests`(test_realtime_bus_accepts_state_events, test_cycle_snapshot_captures_latest_state_versions, test_buy_and_sell_decisions_share_same_snapshot_id, test_high_priority_sell_blocks_same_symbol_buy, test_freshness_blocks_stale_quote_pnl_and_position, test_audit_writer_is_single_writer_and_wal_enabled_append_only, test_buy_event_has_pending_protection_fields, test_position_lifecycle_state_is_written, test_strategies_and_engines_cannot_submit_orders, test_end_to_end_reports_no_real_order_or_snapshot_risk) |
| `tests/test_risk.py` | 项目文件 | 类 `RiskEngineTests`(setUp, test_disarmed_engine_rejects_every_order, test_valid_paper_proposal_is_approved_when_armed, test_order_over_value_limit_is_rejected, test_order_over_quantity_limit_is_rejected) |
| `tests/test_security_master.py` | 项目文件 | 类 `SecurityMasterTests`(test_builds_security_master_from_universe_csv, test_persistent_security_master_takes_precedence_over_seed_universe, test_nasdaq_trader_rows_build_broad_master_records) |
| `tests/test_service.py` | 项目文件 | `make_settings`:模块辅助逻辑; `valid_payload`:模块辅助逻辑; `valid_limit_payload`:模块辅助逻辑; `ready_tws_status`:读取输入; `not_ready_tws_status`:模块辅助逻辑; 类 `TradingServiceTests`(test_stage_menu_requires_explicit_confirmation, test_dry_run_validation_approves_safe_proposal, test_dry_run_mode_cannot_stage_order, test_paper_transmission_requires_explicit_switch, test_kill_switch_rejects_submission, test_paper_transmission_requires_session_token_configured, test_paper_transmission_rejects_invalid_session_token, test_paper_transmission_accepts_valid_session_token, test_duplicate_idempotency_key_is_rejected, test_outside_rth_switch_is_passed_to_broker, +10) |
| `tests/test_session_calendar.py` | 项目文件 | 类 `SessionCalendarTests`(test_regular_session_classification, test_premarket_session_classification, test_afterhours_session_classification, test_overnight_session_classification, test_weekend_offline_classification) |
| `tests/test_session_policy.py` | 项目文件 | 类 `SessionPolicyTests`(test_outside_rth_only_for_extended_sessions, test_protective_stop_required, test_stale_quote_blocks_order, test_open_order_blocks_duplicate_submit, test_max_orders_per_symbol_blocks_order); `_quote`:内部辅助 |
| `tests/test_strategy.py` | 项目文件 | 类 `StrategyFrameworkTests`(test_value_filter_approves_quality_candidate, test_value_filter_rejects_weak_candidate, test_value_filter_scores_undervaluation_quality_demand_and_safety, test_moving_average_requires_confirmation_before_entry, test_tactical_strategy_blocks_stale_quote, test_tactical_strategy_creates_bracket_style_plan, test_quote_cache_tracks_freshness, test_ring_buffer_keeps_only_recent_values, test_rotating_symbol_pool_cycles_fixed_size_batches, test_rotating_strategy_scanner_updates_cache_and_bar_ring, +1) |
| `tests/test_strategy_catalog.py` | 项目文件 | 类 `StrategyCatalogTests`(test_catalog_covers_current_strategy_modules_and_books, test_writers_create_catalog_artifacts) |
| `tests/test_strategy_extension_status.py` | 项目文件 | 类 `StrategyExtensionStatusTests`(test_status_is_report_only_and_does_not_enable_live_or_buy, test_write_reports_creates_json_and_markdown); `_settings`:内部辅助 |
| `tests/test_strategy_modules.py` | 项目文件 | 类 `ConservativeTrendModuleTests`(test_module_buys_confirmed_classic_uptrend, test_module_sells_after_profit_target, test_module_blocks_unapproved_symbol, test_portfolio_risk_gate_blocks_extra_entry_after_position_limit, test_portfolio_risk_gate_blocks_daily_loss); `bars_for`:模块辅助逻辑 |
| `tests/test_strategy_validation_plan.py` | 项目文件 | 类 `StrategyValidationPlanTests`(test_grid_pullback_creates_validate_payload, test_wide_spread_rejects_buy_signal_before_validate); `_write_quotes`:内部辅助 |
| `tests/test_tws_paper.py` | 项目文件 | 类 `TwsPaperBrokerTests`(test_us_stock_price_normalizes_to_cent_tick, test_transmitted_order_requires_order_status_ack, test_staged_order_can_ack_from_open_order, test_bracket_has_protective_stop_and_no_transmission_by_default, test_transmitted_bracket_only_transmits_on_final_stop_child, test_bracket_child_failure_requests_parent_cancel, test_outside_rth_is_configurable_for_both_bracket_legs, test_limit_order_can_transmit_outside_rth_without_stop_leg, test_stop_limit_order_is_sell_gtc_outside_rth_with_order_ref, test_order_confirmation_records_partial_ack_as_pending, +1) |
| `tests/test_unified_strategy_interface.py` | 项目文件 | 类 `UnifiedStrategyInterfaceTests`(test_dual_ma_generates_buy_signal, test_zscore_mean_reversion_generates_buy_signal, test_grid_generates_sell_signal_for_upper_band, test_ml_baseline_uses_precomputed_probability, test_risk_and_paper_order_path, test_live_order_is_disabled_by_default) |
| `tests/test_universe.py` | 项目文件 | 类 `UniverseTests`(test_default_universe_loads_large_enabled_pool, test_select_universe_intersects_gateway_allowlist, test_symbols_csv_deduplicates_and_normalizes, test_loader_respects_disabled_rows) |

### trading
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `trading/__init__.py` | Core types and safeguards for the trading service. | 无顶层类/函数，主要为常量、导入或包初始化 |
| `trading/account_state_manager.py` | 项目文件 | `build_account_state`:构建对象/报告; `force_refresh_state`:模块辅助逻辑; `build_force_refresh_dry_run`:构建对象/报告; `refresh_streaming_quote_diagnostics`:刷新状态; `overlay_streaming_quotes`:模块辅助逻辑; `symbols_from_guard`:模块辅助逻辑; `require_fresh_state_for_execution`:模块辅助逻辑; `build_quote_states`:构建对象/报告; `quote_state_from_guard`:模块辅助逻辑; `quote_execution_readiness`:模块辅助逻辑; `quote_stale_reason`:模块辅助逻辑; `actual_quote_age_for_use_case`:模块辅助逻辑; `quote_age_sec`:模块辅助逻辑; `quote_threshold`:模块辅助逻辑; `parse_market_data_type`:模块辅助逻辑; `market_data_type_label`:模块辅助逻辑; `quote_blocked_reason`:模块辅助逻辑; `position_state_from_guard`:模块辅助逻辑; `open_order_state`:模块辅助逻辑; `coverage_state`:模块辅助逻辑; `build_pnl_states`:构建对象/报告; `pnl_subscription_support`:模块辅助逻辑; `build_freshness`:构建对象/报告; `stale_status`:模块辅助逻辑; `write_account_state_reports`:写出文件或结果; `account_state_payload`:模块辅助逻辑; `account_dashboard_payload`:模块辅助逻辑; `account_execution_readin |
| `trading/audit.py` | 项目文件 | 类 `AuditLog`(__init__, _connect, _initialize, reserve, update, get, list_recent, list_for_date, paper_notional_for_date, _row_to_record); `_notional`:内部辅助 |
| `trading/audit_writer.py` | Single-writer audit queue for SQLite append-only ledgers. | 类 `AuditEvent`; 类 `AuditWriter`(__init__, submit, submit_event_store, flush, queued_count) |
| `trading/auto_open_pipeline.py` | Auto-open local discovery, news, dynamic pool, and simulation pipeline. | 类 `PipelineConfig`(from_env); `run_auto_open_pipeline`:运行流程; `assert_simulation_safety`:模块辅助逻辑; `run_discovery_orchestrator`:运行流程; `run_ibkr_scanner`:运行流程; `run_news_pipeline`:运行流程; `news_provider_status`:模块辅助逻辑; `ibkr_news_interface_tests`:模块辅助逻辑; `raw_news_fixture`:模块辅助逻辑; `structure_news_event`:模块辅助逻辑; `run_dynamic_pool`:运行流程; `run_fast_order_guidance`:运行流程; `run_order_intent_router`:运行流程; `run_local_simulation`:运行流程; `run_paper_execution_gate`:运行流程; `write_final_audit`:写出文件或结果; `consolidate_candidates`:模块辅助逻辑; `score_candidate`:计算评分; `add_pool_membership`:模块辅助逻辑; `write_report`:写出文件或结果; `load_universe_rows`:读取/加载数据; `current_position_symbols`:模块辅助逻辑; `open_order_symbols_from_reports`:模块辅助逻辑; `research_symbols`:模块辅助逻辑; `cached_scanner_symbols`:模块辅助逻辑; `scanner_symbols_for_code`:模块辅助逻辑; `env_symbols`:模块辅助逻辑; `tws_available`:模块辅助逻辑; `market_session_state`:模块辅助逻辑; `simulated_price`:模块辅助逻 |
| `trading/autonomous_runtime.py` | 项目文件 | 类 `Scanner`(scan_once); 类 `AutonomousRuntimeConfig`(from_env); 类 `RuntimeCycleReport`; 类 `AutonomousPaperRuntime`(__init__, run_once, run_forever, _cycle, _write_status, _append_events); `build_runtime`:构建对象/报告; `_read_open_orders`:内部辅助; `_report`:内部辅助; `_health_ready`:内部辅助; `_proposal_from_event`:内部辅助; `_quote_from_event`:内部辅助; `_float_or_none`:内部辅助; `_bool_env`:内部辅助 |
| `trading/buy_decision_engine.py` | BUY decision engine. Emits BUY intents only; never calls IBKR directly. | `build_buy_intent`:构建对象/报告; `can_submit_order`:模块辅助逻辑; `submit_order`:提交请求 |
| `trading/candidate_research.py` | 项目文件 | 类 `EvidenceItem`; 类 `LlmPreReview`; 类 `CandidateDraft`; 类 `HardAuditConfig`; 类 `HardAuditResult`; 类 `CandidateReport`(as_dict); `build_candidate_report`:构建对象/报告; `audit_candidate`:审计状态; `normalize_draft`:标准化数据; `load_candidate_draft`:读取/加载数据; `candidate_draft_from_dict`:模块辅助逻辑; `write_candidate_report`:写出文件或结果; `candidate_report_from_dict`:模块辅助逻辑; `load_candidate_report`:读取/加载数据; `_profile_from_dict`:内部辅助; `_pre_review_from_dict`:内部辅助; `_evidence_from_dict`:内部辅助; `_tuple_of_strings`:内部辅助; `_float_or_none`:内部辅助; `_int_or_none`:内部辅助; `_bool_or_true`:内部辅助; `_bool_or_none`:内部辅助 |
| `trading/candidate_scoring.py` | Candidate scoring helpers. | `score`:计算评分 |
| `trading/config.py` | 项目文件 | `_read_bool`:内部辅助; `_load_or_create_api_key`:内部辅助; `_load_optional_file_value`:内部辅助; `_load_allowed_symbols`:内部辅助; `_symbols_from_file`:内部辅助; `_read_symbol_tuple`:内部辅助; 类 `Settings`(load); `_read_optional_float`:内部辅助 |
| `trading/cycle_snapshot.py` | Immutable decision-time snapshots over the realtime account state bus. | 类 `CycleSnapshot`; `create_cycle_snapshot`:创建对象; `write_report`:写出文件或结果 |
| `trading/dashboard.py` | 项目文件 | `render_dashboard_html`:渲染输出 |
| `trading/data_buses.py` | Logical data bus architecture for realtime decisions. | 类 `MarketDataBus`(__init__, update_quote); 类 `NewsTriggerBus`(__init__, update); 类 `DiscoveryPoolBus`(__init__, update); `build_data_bus_architecture_report`:构建对象/报告 |
| `trading/discovery_orchestrator.py` | Unified discovery orchestrator entrypoint. | `run`:运行流程 |
| `trading/event_risk_control.py` | 项目文件 | 类 `EventRiskConfig`; `load_event_risk_config`:读取/加载数据; `build_event_risk_report`:构建对象/报告; `recommended_event_action`:模块辅助逻辑; `load_local_events`:读取/加载数据; `write_report`:写出文件或结果; `_event_for_symbol`:内部辅助; `_latest_net_liquidation`:内部辅助; `_bool_env`:内部辅助; `_float_env`:内部辅助; `_now`:内部辅助 |
| `trading/event_router.py` | 项目文件 | `build_event_router_report`:构建对象/报告; `event`:模块辅助逻辑; `write_report`:写出文件或结果; `read_json`:读取输入 |
| `trading/execution_ledger_split.py` | Build split BUY/SELL intent ledgers and structured PnL reports. | `build_execution_and_pnl_ledgers`:构建对象/报告; `buy_intents`:模块辅助逻辑; `protective_sell_intents`:模块辅助逻辑; `gap_escape_intents`:模块辅助逻辑; `profit_sell_intents`:模块辅助逻辑; `event_risk_sell_intents`:模块辅助逻辑; `_sell_plan_intents`:内部辅助; `options_plan_intents`:模块辅助逻辑; `persist_intents`:模块辅助逻辑; `build_pnl_ledger_report`:构建对象/报告; `persist_pnl`:模块辅助逻辑; `insert_direct`:模块辅助逻辑; `attribution`:模块辅助逻辑; `execution_split_report`:模块辅助逻辑; `separation_report_payload`:模块辅助逻辑; `count_intents`:模块辅助逻辑; `write_reports`:写出文件或结果; `markdown`:模块辅助逻辑; `read_json`:读取输入; `held_symbols`:模块辅助逻辑; `read_market_session_state`:读取输入; `count_values`:模块辅助逻辑; `to_float`:转换输出 |
| `trading/fast_order_guidance.py` | Fast order guidance from scanner/news events. Guidance only; no order submission. | `run`:运行流程 |
| `trading/gap_escape_manager.py` | 项目文件 | 类 `GapEscapeConfig`; `load_gap_escape_config`:读取/加载数据; `build_gap_escape_report`:构建对象/报告; `gap_escape_row`:模块辅助逻辑; `gap_escape_blocked_reason`:模块辅助逻辑; `_trigger_reason`:内部辅助; `_active_stop_price`:内部辅助; `_active_stop_limit_price`:内部辅助; `_worst_loss_by_symbol`:内部辅助; `write_report`:写出文件或结果; `_bool_env`:内部辅助; `_float_env`:内部辅助; `_float`:内部辅助; `_now`:内部辅助 |
| `trading/gap_risk_manager.py` | 项目文件 | 类 `GapRiskConfig`; `load_gap_risk_config`:读取/加载数据; `build_gap_risk_report`:构建对象/报告; `gap_risk_row`:模块辅助逻辑; `classify_symbol_shock`:分类状态; `write_report`:写出文件或结果; `_long_positions`:内部辅助; `_latest_net_liquidation`:内部辅助; `_dedupe_shocks`:内部辅助; `_float`:内部辅助; `_float_env`:内部辅助; `_now`:内部辅助 |
| `trading/ibkr_callback_bridge.py` | REAL_IBKR callback bridge into logical realtime data buses. | 类 `IbkrCallbackBridge`(__init__, nextValidId, connectionClosed, error, tickPrice, tickSize, tickString, tickGeneric, marketDataType, tickReqParams, +18); `run_ibkr_callback_dry_run`:运行流程; `stock_contract`:模块辅助逻辑 |
| `trading/ibkr_callback_wiring_audit.py` | Audit whether real IBKR callbacks are wired into RealtimeAccountStateBus. | `build_ibkr_callback_wiring_audit`:构建对象/报告; `callback_row`:模块辅助逻辑; `bus_state_sources`:模块辅助逻辑; `callback_defined`:模块辅助逻辑; `callback_wires_bus`:模块辅助逻辑; `latest_bus_timestamp_for_callback`:模块辅助逻辑; `callback_notes`:模块辅助逻辑; `callback_wired`:模块辅助逻辑; `tws_socket_available`:模块辅助逻辑; `update_realtime_reports`:更新状态; `write_report`:写出文件或结果; `read_json`:读取输入; `utc_now`:模块辅助逻辑 |
| `trading/ibkr_news.py` | IBKR news interface diagnostics. | `run_interface_tests`:运行流程 |
| `trading/ibkr_readonly.py` | 项目文件 | 类 `_QuoteState`(to_quote); 类 `IbkrReadOnlyQuoteClient`(__init__, nextValidId, run_loop, error, tickPrice, tickSize, tickSnapshotEnd, _state, _mark_ready_if_possible); 类 `IbkrReadOnlyQuoteSource`(__init__, get_quotes, _stock_contract, _wait_for_quotes); 类 `ParallelIbkrReadOnlyQuoteSource`(__init__, get_quotes, _source_for); `_chunks`:内部辅助; `_env_bool`:内部辅助 |
| `trading/ibkr_scanner.py` | IBKR scanner diagnostics and local discovery fallback. | `run`:运行流程 |
| `trading/ibkr_streaming.py` | 项目文件 | 类 `StreamingQuoteState`(to_quote, age_ms, field_age_ms, market_data_type_name); 类 `IbkrStreamingQuoteClient`(__init__, nextValidId, run_loop, error, tickPrice, tickSize, tickString, marketDataType, _state); 类 `IbkrStreamingQuoteSource`(__init__, start, stop, get_latest_quotes, get_quote, quote_age_ms, is_stale, stale_symbols, errors, active, +3); `_clean_symbols`:内部辅助; `_log_event`:内部辅助; `streaming_blocked_reason`:模块辅助逻辑 |
| `trading/market_data.py` | 项目文件 | 类 `Quote`(age_ms, midpoint, spread); 类 `Bar`; 类 `QuoteSource`(get_quotes); 类 `InMemoryQuoteCache`(__init__, update, update_many, get, is_fresh, snapshot); 类 `RingBuffer`(__init__, append, replace_latest, latest, values); 类 `SymbolRingBuffers`(__init__, append, replace_latest, latest, values, snapshot, _buffer); 类 `RotatingSymbolPool`(__init__, symbols, next_batch); 类 `BarBuilder`(__init__, update, active_bar, _new_bar); 类 `SimulatedQuoteSource`(__init__, get_quotes); 类 `StooqDelayedQuoteSource`(__init__, get_quotes, _row_to_quote); 类 `YahooDelayedQuoteSource`(__init__, get_quotes, _quote_from_chart_payload, _quotes_from_chart_payload); 类 `YahooChartReplayQuoteSource`(__init__, get_quotes, _load_symbol); `quote_stream`:模块辅助逻辑; `_bucket_start`:内部辅助; `_float_or_none`:内部辅助; `_int_or_none`:内部辅助 |
| `trading/market_data_line_manager.py` | 项目文件 | 类 `MarketDataLineConfig`; 类 `MarketDataLinePlan`; 类 `MarketDataLineManager`(__init__, plan, write_report); `_unique`:内部辅助 |
| `trading/market_quote_crosscheck.py` | Cross-validate market session expectations against received quotes. | `build_market_quote_crosscheck_report`:构建对象/报告; `crosscheck_row`:模块辅助逻辑; `classify_cross_validation_result`:分类状态; `summarize`:汇总信息; `write_report`:写出文件或结果; `_markdown`:内部辅助; `_read_json`:内部辅助; `_now`:内部辅助 |
| `trading/market_session.py` | US equity market-session classification and reporting. | 类 `MarketSessionState`; 类 `MarketSessionConfig`; 类 `CalendarStatus`; 类 `MarketSessionSnapshot`(to_dict); `config_from_env`:模块辅助逻辑; `current_market_session`:模块辅助逻辑; `write_market_session_report`:写出文件或结果; `fetch_ibkr_contract_details`:拉取数据; `market_session_md`:模块辅助逻辑; `classify_streaming_bid_ask_gap`:分类状态; `parse_ibkr_trading_hours`:模块辅助逻辑; 类 `_ContractDetailsClient`(__init__, nextValidId, contractDetails, contractDetailsEnd, error); `_stock_contract`:内部辅助; `calendar_status`:模块辅助逻辑; `_state_for_time`:内部辅助; `_symbol_rows`:内部辅助; `_hours_today`:内部辅助; `_hours_allow_now`:内部辅助; `_hhmm_to_minutes`:内部辅助; `_calendar_status_from_package`:内部辅助; `_calendar_status_from_local_file`:内部辅助; `_inactive_reason`:内部辅助; `_next_regular_open`:内部辅助; `_holiday_dates`:内部辅助; `_early_close_dates`:内部辅助; `_observed`:内部辅助; `_nth_weekday`:内部辅助; `_last_weekday`:内部辅助; `_good_friday`:内部辅助; `_time_env`:内部辅助; `_parse_time`:内部辅 |
| `trading/models.py` | 项目文件 | 类 `TradeProposal`; 类 `RiskDecision` |
| `trading/module_interfaces.py` | 项目文件 | 类 `StateFreshness`; 类 `QuoteState`; 类 `PnLState`; 类 `ProtectionCoverageState`; 类 `OpenOrderState`; 类 `PositionState`; 类 `ForceRefreshResult`; 类 `AccountState` |
| `trading/news_candidate_router.py` | Route structured news into candidate/risk events. | `run`:运行流程 |
| `trading/news_event_monitor.py` | News event monitor entrypoint. | `run`:运行流程 |
| `trading/news_event_structurer.py` | Normalize raw news events into structured news events. | `normalize`:标准化数据 |
| `trading/news_provider_registry.py` | Unified news provider registry for IBKR, RSS, SEC, earnings, cache, and fixtures. | `build_registry`:构建对象/报告 |
| `trading/options_hedge_planner.py` | 项目文件 | 类 `OptionHedgeConfig`; `load_option_hedge_config`:读取/加载数据; `build_options_hedge_report`:构建对象/报告; `option_hedge_plan`:模块辅助逻辑; `write_report`:写出文件或结果; `_markdown`:内部辅助; `_bool_env`:内部辅助; `_float_env`:内部辅助; `_now`:内部辅助 |
| `trading/order_intent_router.py` | Order intent router. Emits synchronized intent events only. | `route_synchronized_intents`:路由事件/候选; `write_conflict_report`:写出文件或结果; `run`:运行流程 |
| `trading/order_intents.py` | Unified order intent model for Mode 9 paper automation ledgers. | 类 `OrderIntent`(to_dict, sqlite_values); `make_intent_id`:模块辅助逻辑; `utc_now`:模块辅助逻辑 |
| `trading/order_rejections.py` | 项目文件 | `log_order_rejection`:模块辅助逻辑; `rejection_result`:模块辅助逻辑; `_parse_ib_error`:内部辅助 |
| `trading/paper_audit_db.py` | SQLite logging helpers for Mode 9 paper automation. | `ensure_paper_automation_tables`:确保前置条件; `insert_event`:模块辅助逻辑; `generic_decision_event`:模块辅助逻辑; `sqlite_table_summary`:模块辅助逻辑; `utc_now`:模块辅助逻辑; `_column_definitions`:内部辅助 |
| `trading/paper_environment_audit.py` | 项目文件 | 类 `PaperEnvironmentAuditItem`; 类 `PaperEnvironmentAuditReport`; `build_environment_audit`:构建对象/报告; `write_environment_audit`:写出文件或结果; `main`:命令入口; `fetch_health`:拉取数据; `_audit_items`:内部辅助; `_health_items`:内部辅助; `_item`:内部辅助; `_report_status`:内部辅助; `_next_steps`:内部辅助; `_settings_snapshot`:内部辅助; `_load_json_object`:内部辅助; `_dedupe`:内部辅助 |
| `trading/paper_execution_gate.py` | Future paper execution gate. Report-only and default false. | `run`:运行流程 |
| `trading/paper_order_executor.py` | Future IBKR paper order executor interface. Disabled by default. | `submit_order_if_enabled`:提交请求 |
| `trading/pool_builder.py` | Dynamic six-layer pool builder. | `run`:运行流程 |
| `trading/pool_manager.py` | 项目文件 | 类 `PoolMembership`; `build_pool_manager_report`:构建对象/报告; `discovery_eligibility`:发现候选; `architecture_report`:模块辅助逻辑; `write_reports`:写出文件或结果; `read_json`:读取输入 |
| `trading/pool_state.py` | Canonical six-layer symbol pool state. | 类 `PoolTransition`; 类 `SymbolPoolState`; 类 `PoolStateManager`(__init__, upsert_master, evaluate_eligibility, nominate_scan, promote_to_watch, evaluate_signal, enter_execution_pool, apply_order_callback, expire, save, +8); `quote_readiness`:模块辅助逻辑; `signal_failures`:模块辅助逻辑; `expired_signal`:模块辅助逻辑; `has_active_order`:布尔判断; `normalize_status`:标准化数据; `state_to_dict`:模块辅助逻辑; `state_from_dict`:模块辅助逻辑; `normalize_symbol`:标准化数据; `to_float`:转换输出; `age_seconds`:模块辅助逻辑; `iso_add`:模块辅助逻辑; `parse_time`:模块辅助逻辑 |
| `trading/position_guard.py` | 项目文件 | 类 `PositionRecord`; 类 `ProtectionStatus`; 类 `ReadOnlyPositionsClient`(__init__, nextValidId, managedAccounts, updatePortfolio, accountDownloadEnd, error, run_loop); `read_positions`:读取输入; `build_position_guard_report`:构建对象/报告; `write_report`:写出文件或结果; `evaluate_protection_status`:评估决策; `_read_quotes`:内部辅助; `_read_streaming_quote_cache`:内部辅助; `_parse_timestamp`:内部辅助; `_float`:内部辅助; `_market_data_type_from_name`:内部辅助; `_env_bool`:内部辅助; `_recommended_action`:内部辅助; `_order_details`:内部辅助 |
| `trading/position_lifecycle_manager.py` | Position lifecycle manager for simulation, paper, and live-forbidden modes. | 类 `PositionLifecycle`; 类 `PositionLifecycleManager`(__init__, transition, write_report, _archive_transition) |
| `trading/position_protection.py` | 项目文件 | 类 `ProtectionRepairRecord`; 类 `RepairPreviewProposal`; 类 `StopConfig`; 类 `RepairConfig`; 类 `TestThenBulkSelection`; `run_position_protection`:运行流程; `_repair_record_for_row`:内部辅助; `calculate_uncovered_qty`:模块辅助逻辑; `calculate_raw_stop_price`:模块辅助逻辑; `load_stop_config`:读取/加载数据; `load_repair_config`:读取/加载数据; `paper_operation_mode`:模块辅助逻辑; `build_repair_execution_plan`:构建对象/报告; `latest_test_repair_result`:模块辅助逻辑; `build_test_repair_result`:构建对象/报告; `write_test_repair_result`:写出文件或结果; `calculate_dynamic_stop`:模块辅助逻辑; `select_reference_price`:筛选对象; `build_repair_preview_report`:构建对象/报告; `select_test_then_bulk_symbol`:筛选对象; `build_repair_preview_proposal`:构建对象/报告; `write_preview_report`:写出文件或结果; `write_report`:写出文件或结果; `_blocked_reason`:内部辅助; `_preview_safety`:内部辅助; `_is_test_symbol_eligible`:内部辅助; `_is_run_symbol_eligible`:内部辅助; `_test_symbol_row`:测试对应行为; `_manual_test_symbol_rejection`:内部辅助; ` |
| `trading/price_normalizer.py` | 项目文件 | 类 `PriceNormalization`; `normalize_order_price`:标准化数据; `normalize_order_price_record`:标准化数据; `rounding_direction`:模块辅助逻辑; `log_normalization`:模块辅助逻辑; `_decimal_tick`:内部辅助; `_round_to_tick`:内部辅助 |
| `trading/process_guard.py` | 项目文件 | 类 `ProcessInfo`(process_name); 类 `ExecutionLock`(__init__, heartbeat); `current_execution_processes`:模块辅助逻辑; `stop_duplicate_autonomous_processes`:停止进程/服务; `write_process_guard_report`:写出文件或结果; `append_history`:追加记录; `read_lock`:读取输入; `process_cwd`:模块辅助逻辑; `process_belongs_to_project`:模块辅助逻辑; `_inherited_owner`:内部辅助; `_parent_mode9_owner`:内部辅助; `_pid_alive`:内部辅助; `_current_command`:内部辅助; `_utc_now`:内部辅助 |
| `trading/profit_lock.py` | 项目文件 | `build_profit_lock_report`:构建对象/报告; `profit_lock_row`:模块辅助逻辑; `common_row`:模块辅助逻辑; `write_report`:写出文件或结果; `read_json`:读取输入; `now`:模块辅助逻辑 |
| `trading/realtime_account_state_bus.py` | Near real-time account-centered state bus. | 类 `StateUpdate`; 类 `RealtimeAccountStateBus`(__init__, update, snapshot_payload, write_report, _archive_state_update); `bootstrap_bus_from_reports`:模块辅助逻辑; `update_to_dict`:更新状态; `read_json`:读取输入; `utc_now`:模块辅助逻辑 |
| `trading/realtime_account_sync.py` | Realtime account sync orchestration for BUY/SELL synchronized decisions. | `run_realtime_account_sync`:运行流程; `sqlite_ledger_integrity_report`:模块辅助逻辑; `write_report`:写出文件或结果 |
| `trading/risk.py` | 项目文件 | 类 `RiskLimits`; 类 `RiskEngine`(__init__, validate, _reject) |
| `trading/scanner_universe_builder.py` | Build scanner candidates for the discovery universe. | `build_scanner_universe`:构建对象/报告 |
| `trading/security_master.py` | 项目文件 | 类 `SecurityMasterRecord`; `build_security_master_report`:构建对象/报告; `load_seed_records`:读取/加载数据; `load_security_master_records`:读取/加载数据; `record_from_universe_row`:记录数据; `record_from_security_master_row`:记录数据; `records_from_nasdaq_trader_rows`:记录数据; `exchange_name`:模块辅助逻辑; `write_report`:写出文件或结果 |
| `trading/sell_decision_engine.py` | SELL decision engine. Emits SELL intents only; never calls IBKR directly. | `build_sell_intent`:构建对象/报告; `priority`:模块辅助逻辑; `can_submit_order`:模块辅助逻辑; `submit_order`:提交请求 |
| `trading/service.py` | 项目文件 | 类 `TradingService`(__init__, health, audit_orders, audit_order, validate, validate_limit, _validate_proposal, submit, submit_limit, _submit_bracket, +16) |
| `trading/session_calendar.py` | 项目文件 | 类 `TradingSession`; 类 `SessionSnapshot`; `classify_trading_session`:分类状态; `_session_for_eastern`:内部辅助; `_as_utc`:内部辅助 |
| `trading/session_policy.py` | 项目文件 | 类 `SessionRiskPolicy`; 类 `SessionOrderContext`; 类 `PolicyDecision`; `default_session_policies`:模块辅助逻辑; `policy_for_session`:模块辅助逻辑; `validate_session_order`:校验规则; `_policy`:内部辅助; `_bool_env`:内部辅助; `_int_env`:内部辅助; `_float_env`:内部辅助 |
| `trading/simulated_order_executor.py` | Local simulated order executor. | `run`:运行流程 |
| `trading/simulated_pnl.py` | Local simulated PnL helpers. | `refresh`:刷新状态 |
| `trading/simulated_position_ledger.py` | Local simulated position ledger helpers. | `refresh`:刷新状态 |
| `trading/simulation.py` | 项目文件 | 类 `StrategySimulationConfig`; `run_strategy_simulation`:运行流程; `quote_source`:模块辅助逻辑; `default_prices`:模块辅助逻辑; `default_profiles`:模块辅助逻辑; `value_pool_record`:模块辅助逻辑 |
| `trading/sqlite_event_store.py` | Append-only SQLite event store with WAL enabled. | 类 `SQLiteEventStore`(__init__, enable_wal, journal_mode, append, append_many, _insert_with_connection) |
| `trading/state_bootstrap_manager.py` | Bootstrap buses from local cache, then keep REAL_IBKR subscriptions available. | 类 `StateBootstrapManager`(__init__, bootstrap); `source_timestamp`:模块辅助逻辑; `write_report`:写出文件或结果; `read_json`:读取输入 |
| `trading/state_freshness_policy.py` | Freshness policy for simulation and future IBKR paper execution readiness. | 类 `FreshnessThresholds`(from_env); `evaluate_freshness`:评估决策; `is_stale`:布尔判断; `write_report`:写出文件或结果 |
| `trading/state_timestamp_reconciler.py` | Timestamp reconciliation for cache, simulation, and REAL_IBKR events. | 类 `ReconciledField`; 类 `TimestampReconciler`(__init__, reconcile, write_report); `should_accept`:模块辅助逻辑; `parse_time`:模块辅助逻辑 |
| `trading/strategy.py` | 项目文件 | 类 `CandidateProfile`; 类 `ValueFilterConfig`; 类 `FilterResult`; 类 `ValuePoolFilter`(__init__, evaluate, score, approved_symbols); 类 `MovingAverageConfig`; 类 `SignalDecision`; 类 `MovingAverageSignalEngine`(__init__, update); 类 `TacticalRiskConfig`; 类 `StrategyPlan`; 类 `StrategyScannerConfig`; 类 `StrategyScanEvent`(as_dict); 类 `RotatingStrategyScanner`(__init__, cache, bar_history, scan_once, _record_bar); 类 `TacticalLongStrategy`(__init__, plan_entry); `_average_available`:内部辅助; `_lower_is_better`:内部辅助; `_higher_is_better`:内部辅助 |
| `trading/strategy_modules.py` | 项目文件 | 类 `ConservativeTrendConfig`; 类 `ModulePosition`; 类 `ModuleDecision`(is_order); 类 `PortfolioRiskConfig`; 类 `PortfolioRiskDecision`; 类 `PortfolioRiskGate`(__init__, evaluate); 类 `ConservativeTrendModule`(__init__, positions, evaluate, record_order_decision, _exit_decision, _common_block_reason, _averages); `_position_market_value`:内部辅助; `_is_regular_session`:内部辅助 |
| `trading/strategy_signals.py` | Strategy signal only architecture. | 类 `StrategySignal`; `create_strategy_signal`:创建对象; `write_report`:写出文件或结果; `submit_order`:提交请求 |
| `trading/subscription_health.py` | Always-listening subscription state reporting. | `build_subscription_health_report`:构建对象/报告; `default_streams`:模块辅助逻辑; `stream`:模块辅助逻辑 |
| `trading/take_profit.py` | 项目文件 | `build_take_profit_report`:构建对象/报告; `take_profit_row`:模块辅助逻辑; `write_report`:写出文件或结果; `read_json`:读取输入; `now`:模块辅助逻辑 |
| `trading/trailing_profit.py` | 项目文件 | `build_trailing_profit_report`:构建对象/报告; `trailing_profit_row`:模块辅助逻辑; `write_report`:写出文件或结果; `read_json`:读取输入; `now`:模块辅助逻辑 |
| `trading/tws_paper.py` | 项目文件 | `normalize_us_stock_price`:标准化数据; 类 `OrderConfirmation`(acknowledged_ids, pending_confirmation, details); 类 `TwsConnectionStatus`(as_dict); 类 `TwsPaperClient`(__init__, nextValidId, run_loop, managedAccounts, error, openOrder, openOrderEnd, orderStatus); 类 `TwsPaperBroker`(__init__, check_status, submit_bracket, submit_limit, submit_stop, submit_stop_limit, _cancel_parent_order, _fatal_order_errors, _order_errors, _is_fatal_order_error, +7) |
| `trading/universe.py` | 项目文件 | 类 `UniverseEntry`; 类 `UniverseSelectionConfig`; 类 `UniverseSelection`; `load_universe`:读取/加载数据; `select_universe`:筛选对象; `default_universe_symbols`:模块辅助逻辑; `symbols_csv`:模块辅助逻辑; `_entry_from_row`:内部辅助; `_clean_symbol_set`:内部辅助; `_float_or_none`:内部辅助; `_int_or_none`:内部辅助; `_bool_or_true`:内部辅助; `_bool_or_none`:内部辅助 |
| `trading/workflow.py` | 项目文件 | `attach_workflow_step`:模块辅助逻辑; `workflow_step`:模块辅助逻辑; `workflow_error_payload`:模块辅助逻辑 |

### .codex/hooks
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `.codex/hooks/secret_scan_stop.py` | 项目文件 | `respond`:模块辅助逻辑; `run`:运行流程; `main`:命令入口 |

### backtest
| 文件 | 作用 | 关键函数/类 |
|---|---|---|
| `backtest/.gitkeep` | 项目文件 | 无函数 |

### 运行生成目录
| 目录 | 作用 | 维护规则 |
|---|---|---|
| `reports/` | JSON/MD/HTML 运行报告、paper evidence、agent cycle、审计摘要。 | 可归档；不要在交易复盘前删除最新证据。 |
| `logs/` | API、agent、pool strategy 运行日志。 | 排错保留；不应写入 secret。 |
| `dashboard/` | 静态 dashboard HTML。 | 由脚本生成，可重新生成。 |
| `.runtime/` | 后台进程 pid 和本地运行状态。 | 进程控制用，不作为业务事实来源。 |
| `trading_audit.sqlite3` | SQLite 审计库。 | 不要手工编辑；用 API 或脚本读取。 |

## 7. Appendix A: API 与安全文件
| 文件/API | 作用 | 安全要求 |
|---|---|---|
| `LICENSE` | 专有版权条款。 | 发给用户或协作者时保留。 |
| `SECURITY_MODEL.md` | 信任边界、角色权限、secret handling。 | 任何扩大权限前先更新。 |
| `TRADING_LOCK.md` | 交易锁和人工确认语义。 | 不要绕过 STOP/DEV/TRADE_LOCK。 |
| `AGENTS.md` | Codex 工作约束和 secret scan 要求。 | 提交前跑 gitleaks。 |
| `api_service.py` | HTTP API handler。 | 所有请求必须带 `X-API-Key`。 |
| `GET /health` | API/TWS/lock/token/account readiness。 | 只读状态，可用于前置检查。 |
| `POST /v1/orders/validate/limit` | 校验 limit order。 | 不进 TWS，不代表成交。 |
| `POST /v1/orders/stage/limit` | 创建 TWS untransmitted order。 | 危险；可能需要手动取消。 |
| `POST /v1/orders/paper/limit` | 创建 transmitted paper limit order。 | 必须 TRADE_LOCK、token、TWS ready、风控通过。 |
| `GET /v1/orders/audit` | 读取审计记录。 | 不要直接改 SQLite。 |
| `.secrets/` | 本地 secret 文件。 | 必须 gitignore；不能提交真实凭证。 |
| `config/autonomous_paper.env.example` | 自动 paper 环境变量示例。 | 只放占位和默认值。 |

## 8. Appendix B: 术语表
| 术语 | 简明解释 |
|---|---|
| `API key` | 调用本地 Trading API 的认证密钥。 |
| `Audit ledger` | 记录请求、拒绝、提交、TWS 回执和耗时的审计账本。 |
| `Bar` | 按时间聚合的一根行情 K 线/价格条。 |
| `Bracket order` | 父限价单加子止损单的一组保护性订单。 |
| `Candidate` | AI、扫描器或规则发现的潜在标的。 |
| `Cooldown` | 同一标的下单后的冷却步数/时间，避免重复触发。 |
| `Daily trade token` | 当天 TRADE_LOCK 生成的短期交易令牌。 |
| `DEV_LOCK` | 开发锁，允许检查和验证，禁止 paper transmit。 |
| `Execution gate` | 执行前的最终安全门，包括 token、TWS、风控、审计。 |
| `Fast SMA / Slow SMA` | 快/慢简单移动平均线，用于趋势确认。 |
| `IBKR` | Interactive Brokers，券商接口来源。 |
| `Idempotency key` | 幂等键，避免同一请求重复提交。 |
| `Limit order` | 限定最高买入价或最低卖出价的订单。 |
| `Live trading` | 真实资金交易；本项目当前没有安全启用路径。 |
| `Market data type 1/3/4` | IBKR 行情类型：1 实时，3 延迟，4 延迟冻结。 |
| `MODE9_RUNTIME` | 推荐自动运行入口，确保 TRADE_LOCK API 后启动 autonomous agent。 |
| `NBBO` | 美国多交易所最佳买卖报价汇总。 |
| `OpenClaw` | AI 分析/客户端层，可提 proposal，不直连 IBKR。 |
| `Paper trading` | 模拟账户交易，不使用真实资金。 |
| `Proposal` | 结构化交易意图，提交给 Trading API 审核。 |
| `Quote` | 统一行情对象，包含 last/bid/ask/close/volume/timestamp/source。 |
| `Quote freshness` | 行情新鲜度；过期行情不能用于下单。 |
| `Read-only adapter` | 只读取行情/账户/订单状态，不提交订单。 |
| `RTH` | Regular Trading Hours，美股常规交易时段。 |
| `Security master` | 证券主数据表，记录 symbol、交易所、类型等。 |
| `Slippage` | 预期价格和实际成交价格的差异。 |
| `Spread` | ask 与 bid 的差额。 |
| `Stage order` | 已进入 TWS 但 `transmit=False` 的未传输订单。 |
| `STOP` | 最安全状态，停止 API/agent/策略并清 token。 |
| `TRADE_LOCK` | 允许 paper transmit 的前置锁状态。 |
| `Transmit` | TWS 是否真正提交订单。 |
| `TWS` | Trader Workstation，IBKR 本地交易终端。 |
| `Universe` | 策略可观察的股票池。 |
| `Validate` | 只校验请求，不进 TWS。 |
| `Value pool` | 按估值、质量、成长、安全性筛出的候选池。 |

## 维护规则
- 新增源文件后，同步更新本手册或重新生成第 6 节索引。
- 新增交易路径时，先更新 `SECURITY_MODEL.md`、`TRADING_LOCK.md` 和 Appendix A。
- 新增策略时，按“独立模块 -> 单元测试 -> simulated quote -> validate -> paper”的顺序推进。
- 提交或对外发送前运行 `pre-commit run gitleaks --all-files`；任何 secret finding 都是阻塞项。
