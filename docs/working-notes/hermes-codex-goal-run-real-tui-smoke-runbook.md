# `codex_goal_run` Real TUI Smoke Runbook

> 状态：Slice 4F runbook；仅用于审查和未来授权执行。
> 日期：2026-06-17
> 关联 handoff：`docs/working-notes/hermes-codex-goal-run-slice-handoff.md`
> 关联设计：`docs/working-notes/hermes-codex-goal-run-design.md`
> 关联实现：`tools/codex_goal_run_tool.py`、`tests/tools/test_codex_goal_run_tool.py`

## 0. 当前结论

```text
本文件不是执行记录。
本文件不会启动真实 Codex TUI。
本文件不会执行 `codex-yuna --enable goals`。
本文件只定义未来 Slice 5 的最小 smoke 步骤、授权门、停止条件、证据清单和回滚边界。
```

## 1. 适用范围

目标：在用户单独授权后，用最小真实 TUI smoke 验证 `codex_goal_run` 的 official Codex `/goal` driver 可被 Hermes 安全编排。

只验证一条最小链路：

```text
clean repo / isolated worktree
→ prepare one-line goal
→ launch real Codex TUI in PTY/background/notify
→ submit `/goal`
→ bounded monitor windows
→ collect evidence
→ stop for Hermes review
```

非目标：

- 不验证大型真实开发任务。
- 不 push / deploy / restart。
- 不自动 merge。
- 不读取 secrets。
- 不跑真实 provider / 真实数据 / 真实媒体。
- 不把 full raw TUI log 塞进模型上下文。
- 不把 `Goal achieved` 当作最终通过；它只代表 candidate 进入 Hermes review。

## 2. 执行前授权门

真实 smoke 必须有用户在当前会话明确说出类似：

```text
授权执行 Slice 5 最小真实 TUI smoke。
允许启动一次真实 `codex-yuna --enable goals` PTY background。
允许在指定 worktree 内生成 candidate diff，但不 push、不部署、不重启。
```

没有这条授权时：

```text
不得启动真实 TUI。
不得调用真实 `terminal(..., pty=True, background=True)` 去跑 Codex。
不得调用真实 process registry 接管 Codex 会话。
只能继续做 mock/replay/docs。
```

## 3. 前置条件

执行前必须新鲜确认：

| 检查 | 命令 / 证据 | 通过标准 |
|---|---|---|
| 当前分支 | `git status --short --branch --untracked-files=all` | 明确分支，且只在用户授权范围内 |
| worktree 干净 | `git status --short --branch --untracked-files=all` | clean，或 isolated worktree clean |
| Codex binary | `codex-yuna features list` 或既有 preflight | `goals` feature 可用 |
| one-line goal 文件 | `prepare_goal` 输出 | 位于 `/tmp`，repo 外，单行 `/goal ...` |
| 禁止事项 | 本 runbook 第 1 节 | 不 push/deploy/restart/secret/provider |

建议优先使用 isolated worktree，避免污染 live checkout。

## 4. 最小 smoke 目标建议

目标应非常小，避免真实长任务：

```text
在临时 isolated worktree 中只修改一个 throwaway 文档或测试 fixture。
要求 Codex 完成后停止，等待 Hermes review。
不要 push、deploy、restart。
```

示例 one-line goal 内容应包括：

```text
/goal In this isolated smoke worktree, make the smallest possible docs-only marker change under docs/working-notes/..., then stop for Hermes review. Do not push, deploy, restart, access secrets, or run real providers/data/media. Required verification: git diff --check. Stop after candidate diff is ready.
```

如果目标无法做到 docs-only 或会触发真实外部服务，停止，不执行 smoke。

## 5. 推荐执行步骤（未来 Slice 5）

### Step 1：准备 isolated worktree

```bash
git status --short --branch --untracked-files=all
git worktree add /tmp/hermes-codex-goal-smoke-$(date +%Y%m%d-%H%M%S) HEAD
```

通过标准：新 worktree clean，且路径记录到结果中。

### Step 2：运行 `prepare_goal`

使用 `codex_goal_run`：

```json
{
  "mode": "prepare_goal",
  "dirty_baseline_policy": "require-clean",
  "goal_artifact_dir": "/tmp/hermes-codex-goals",
  "objective": "minimal real TUI smoke only",
  "allowed_files": ["docs/working-notes/<smoke-marker>.md"],
  "non_goals": ["do not push", "do not deploy", "do not restart", "do not access secrets"],
  "required_verification": ["git diff --check"],
  "stop_conditions": ["candidate diff ready", "timeout", "needs attention", "process missing"]
}
```

通过标准：`status=prepared`，`goal_files.one_line_goal_file` 在 `/tmp` 且 repo 外。

### Step 3：启动真实 TUI（只在授权后）

真实命令必须通过 Hermes tracked background process 启动，形状应等价于：

```text
codex-yuna --enable goals
pty=True
background=True
notify_on_complete=True
```

通过标准：返回可追踪 `session_id` / process handle，并记录 launch evidence。

### Step 4：提交 one-line `/goal`

提交时必须：

- 读取 `/tmp` one-line goal。
- 确认只有一行。
- 向 TUI 写入该行。
- 发送 raw Enter fallback：`\r`。

通过标准：submit evidence 记录成功；若 TUI 没响应，停止为 `needs_attention`。

### Step 5：bounded monitor

监控上限建议：

```text
monitor_interval_seconds = 10
max_wait_windows = 3
max_total_seconds <= 60
log_tail max_lines <= 40
log_tail max_chars <= 4000
```

每个窗口只收集：

- process found / running / exit_code
- bounded log tail
- changed/staged/untracked files
- diff_stat / staged_diff_stat

不得把 full raw log 输入模型上下文。

### Step 6：stop for Hermes review

任何一个条件满足都必须停止：

| 条件 | 状态 | 后续 |
|---|---|---|
| `Goal achieved` + candidate diff | `completed` | collect candidate for Hermes review |
| process exited 0 + candidate diff | `completed` | collect candidate for Hermes review |
| process exited nonzero | `failed` | inspect failure，不自动重试 |
| process missing | `process_missing` | inspect registry，不猜 |
| `[Pasted Content]` + no diff | `needs_attention` | ask / manual inspect，不自动乱发输入 |
| idle windows exhausted | `idle_wait` | ask / inspect TUI |
| timeout | `timeout` | stop and report |

## 6. 必要证据包

最终报告必须包含：

```text
worktree_path
branch / HEAD
launch session_id / process handle
one_line_goal_file
submit evidence
monitor windows count
bounded log tail metadata
candidate evidence: changed/staged/untracked/diff_stat/staged_diff_stat
classification result
stop_condition
completion_trusted=false
git status after smoke
cleanup status
```

如果缺任一关键证据，不得说 smoke 成功。

## 7. 回滚 / 清理边界

允许清理：

- smoke isolated worktree（仅在用户同意或确认无保留价值后）。
- `.pytest_cache` / `__pycache__` / `*.pyc` / `.codegraph` / `core.*` 本轮副作用。
- 真实 Codex TUI background process（仅针对本次 smoke session_id）。

不允许自动清理：

- 用户未授权的 worktree。
- 不属于本次 smoke 的 background process。
- 未确认的 candidate diff。
- 任何远端分支/tag/release/deploy 状态。

## 8. 失败报告模板

```text
Slice 5 smoke 未完成。
阶段：<launch / submit / monitor / collect / cleanup>
状态：<failed / needs_attention / timeout / process_missing>
证据：<bounded log tail metadata + status + exit code>
未执行：push/deploy/restart/secret/provider
下一步：<ask user / inspect TUI / cleanup smoke worktree>
```

## 9. 成功报告模板

```text
Slice 5 最小真实 TUI smoke 已完成 candidate 阶段。
completion_trusted=false。
Codex 结果仅为 candidate evidence，仍需 Hermes review。
未 push、未部署、未重启、未访问 secrets。
证据：<worktree/session/goal/log_tail/diff/status>
```

## 10. 当前 Slice 4F 验收

本轮 Slice 4F 只要求：

- 本 runbook 落盘。
- handoff/design 链接到本 runbook。
- 文档断言通过。
- `git diff --check` 通过。
- 工作区最终 clean。

明确不要求、也不允许真实 TUI smoke。
