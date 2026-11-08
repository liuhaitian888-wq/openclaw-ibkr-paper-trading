# 买der 项目维护规范

## Purpose
保留本项目独立身份、证据适用范围及开发任务收尾规则。维护把历史设计、当前实现和未来提案分别记录，使规格、文档和受影响图表能随实际变更同步；本规范不表示历史产品架构已经全部融合或真实验收。

## Requirements
### Requirement: Independent project evidence
The project SHALL retain its own source, offline verification, deployment and acceptance evidence under project ID `buy-der`.

#### Scenario: Historical record has no current verification
- **WHEN** a historical digest claims completion without current source or runtime evidence
- **THEN** maintenance retains the record and marks current verification UNKNOWN

### Requirement: Task completion maintenance
The project SHALL synchronize relevant specs, context and affected diagram provenance when an authorized development task changes source or design, while preserving existing permissions and unrelated work.

#### Scenario: No project change
- **WHEN** a conversation ends without source or design content changes
- **THEN** no maintenance continuation is requested and no timer is created

#### Scenario: Changed project source
- **WHEN** an authorized task changes project source or design
- **THEN** task closeout checks OpenSpec deltas, context and affected diagrams once and records actual verification limits
