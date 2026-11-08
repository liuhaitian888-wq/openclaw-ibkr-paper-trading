# task-completion-gate Specification

## Purpose
任务收尾门禁在登记的五个项目及其linked worktree内识别源码或设计变化，使相关文档、规格及图表在当前授权任务内同步，同时避免无活动时运行和维护自身的递归接续。

## Requirements
### Requirement: Changed task closeout
The gate SHALL request at most one maintenance continuation when registered project source or design content changes during an authorized task or since its last completed turn.

#### Scenario: Authorized task changes content
- **WHEN** a registered project's task changes source or design
- **THEN** one continuation requests scoped OpenSpec, context and affected diagram synchronization

#### Scenario: Maintenance changes more files
- **WHEN** a continuation reaches another Stop event
- **THEN** no further continuation is requested and semantic verification remains separately evidenced

### Requirement: No idle maintenance
The gate SHALL perform no periodic wakeups and SHALL request no continuation for unchanged source, context-only edits or unrelated workspaces.

#### Scenario: Question without changes
- **WHEN** a registered project conversation ends with no source or design changes
- **THEN** the turn ends without a maintenance continuation

#### Scenario: No active user task
- **WHEN** no development task is running
- **THEN** no hourly or daily maintenance job starts

### Requirement: Scoped private evidence
The gate SHALL retain bounded project and event metadata without storing prompts or assistant messages, and SHALL preserve dirty or unborn source and existing business permissions.

#### Scenario: Linked worktree
- **WHEN** a task runs in a registered project's linked worktree
- **THEN** source evidence refers to that checkout and does not overwrite the primary checkout

#### Scenario: Private input
- **WHEN** hook input contains prompt or final-answer fields
- **THEN** those fields are not persisted to engineering state
