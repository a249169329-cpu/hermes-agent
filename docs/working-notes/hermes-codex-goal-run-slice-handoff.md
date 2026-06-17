# `codex_goal_run` Slice Handoff

> 状态：Slice 1-3 mock driver 已实现并本地提交；真实 Codex TUI 尚未接入。
> 日期：2026-06-16
> 关联设计：`docs/working-notes/hermes-codex-goal-run-design.md`
> 关联实现：`tools/codex_goal_run_tool.py`、`tests/tools/test_codex_goal_run_tool.py`

## 1. 当前边界结论

```text
Slice 1-3 = official Codex /goal driver 的 mock-first 骨架。
它证明 API、artifact、launch lifecycle、monitor state machine 可以被 Hermes 编排。
它没有启动真实 Codex TUI，也没有执行真实 `codex-yuna --enable goals`。
```

核心边界：

- `completion_trusted` 始终为 `false`。
- `Codex Goal achieved / completed` 只代表 candidate 进入 Hermes review，不代表任务验收通过。
- `launch_goal` 默认 launcher 是 disabled/mock-only。
- `monitor_goal` 默认 poll hook 是 side-effect-free mock。
- `prepare_goal` / `launch_goal` 仍要求 clean worktree。
- `monitor_goal` 允许 dirty candidate worktree，但 dirty 只作为 evidence，不作为 final success。
- 不 push / deploy / restart / merge。
- 不读 secret，不跑真实 provider / 真实数据 / 真实媒体。

## 2. Slice 1-3 对照表

| Slice | 已有 mode / 能力 | 当前行为 | 已验证点 | 不做什么 |
|---|---|---|---|---|
| Slice 1 | `dry_run_plan`、`prepare_goal` | 校验输入、repo、dirty policy、Codex goals preflight；生成 rich goal + one-line goal 到 `/tmp` | schema/toolset 暴露；missing goals feature blocker；artifact 不写 repo；artifact path 必须在 `/tmp` 且不在 repo 内；单行 `/goal` 包含 scope/non-goals/tests/stop conditions | 不启动 TUI；不提交 goal；不改 repo；不自动 enable goals |
| Slice 2 | `launch_goal` mock lifecycle | 读取 `/tmp` 单行 goal；构造 `codex-yuna --enable goals` PTY/background/notify 参数；调用 mockable hooks；默认返回 `launch_unavailable` | 单行 goal 校验；多行/空目标/多余空行 rejected；`pty=True`、`background=True`、`notify_on_complete=True`；submit 后 raw `\r`；不使用 `codex-yuna exec` | 默认不启动真实 TUI；不调用 terminal/process tool；不提交真实 Codex |
| Slice 3 | `monitor_goal` mock state machine | 按 wait-window 调用 `_poll_goal_session`；分类 `idle_wait` / `running` / `completed` / `failed` / `missing_session_id` | idle composer message；持续有输出返回 `running`；completed/failed 都不 trusted；missing session 先 blocked；dirty candidate worktree 可作为 evidence 继续 monitor | 不读取真实 process/log；不收集真实 git diff evidence；不关闭 TUI；不做 candidate review handoff |

## 3. Mode 当前状态对照

| mode | 输入重点 | clean worktree 要求 | 输出重点 | candidate disposition | 当前限制 |
|---|---|---:|---|---|---|
| `dry_run_plan` | required fields + scope/non-goals/tests | 是 | bounded plan + preflight | `planning_only` | 只计划，不写 artifact |
| `prepare_goal` | `goal_artifact_dir` / optional explicit file paths | 是 | `goal_files.rich_goal_file` + `goal_files.one_line_goal_file` | `needs_review` | artifact 必须 `/tmp` 且 repo 外 |
| `launch_goal` | `one_line_goal_file` | 是 | mock process + submit/raw_enter evidence | `needs_review` if mocked launch succeeds; default `planning_only` | 默认 launcher disabled；真实 TUI 未接入 |
| `monitor_goal` | `session_id`、`monitor_interval_seconds`、`max_wait_windows` | 否，dirty 作为 evidence | `monitor.state` + wait-window summary | `running` 或 `needs_review` | 默认 poll hook 不读真实 process/log/git diff |

## 4. 当前提交证据

```text
6ac1dbfb1 feat(codex): add goal run prepare driver
35f0bfbaf feat(codex): add mock goal launch lifecycle
65dccf854 feat(codex): add mock goal monitor lifecycle
```

测试证据来自最近实现收口：

```text
python3 -m pytest tests/tools/test_codex_goal_run_tool.py -q -o addopts=''
19 passed

python3 -m py_compile tools/codex_goal_run_tool.py tests/tools/test_codex_goal_run_tool.py
py_compile_exit_0

git diff --check / git diff --check HEAD~1..HEAD
exit 0
```

安全扫描证据：

```text
terminal_tool_call False
process_tool_call False
enable_goals_command_count 1
poll_hook_default_side_effect_free True
monitor_impl_side_effect_free True
```

说明：`enable_goals_command_count 1` 是 command 字符串，不是本轮真实执行。

## 5. Slice 4 建议：real adapter design，不接真实 TUI

Slice 4 的目标不是“跑起来”，而是把真实 adapter 的输入/输出契约设计清楚，并用 replay/mock transcript tests 锁住行为。

### 5.1 Slice 4 目标

```text
定义真实 terminal/process adapter 的 evidence shape，
把真实 process poll/log/git evidence 映射成 monitor states，
但仍不调用真实 terminal/process，不启动 `codex-yuna --enable goals`。
```

### 5.2 建议新增的内部边界

| 内部函数 / 数据结构 | 作用 | Slice 4 是否真实调用外部工具 |
|---|---|---:|
| `_collect_goal_process_snapshot(session_id)` | 描述真实 process 状态的 adapter contract | 否，先 mock/replay |
| `_collect_goal_git_evidence(repo)` | 描述 git status/diff/untracked/staged evidence 的 contract | 否，先用 fixture/replay |
| `_classify_goal_snapshot(snapshot)` | 纯函数：把 process/log/git evidence 映射为 state | 否 |
| `_bounded_log_tail(raw)` | 限制 raw TUI log 尾部和 metadata，防止 flood | 否 |

### 5.3 Slice 4 状态映射草案

| 真实证据组合 | 目标状态 | next_action | 说明 |
|---|---|---|---|
| process running + new output | `running` | `continue_monitoring_goal` | 有活动，不是 idle |
| process running + N 个窗口无输出 + no diff | `idle_wait` / `needs_attention` | `continue_monitoring_or_inspect_tui` | 可能卡住或等输入 |
| process exited 0 + diff/staged/untracked 非空 | `completed` | `collect_candidate_for_hermes_review` | 仍需 Hermes review |
| process exited nonzero | `failed` | `inspect_goal_failure` | 不 trusted |
| process missing / session unknown | `process_missing` | `inspect_process_registry` | 需要人工判断，不猜 |
| log contains `Goal achieved` + candidate diff | `completed` | `collect_candidate_for_hermes_review` | Goal achieved 只是 candidate evidence |
| log contains `[Pasted Content]` + no diff + running | `needs_attention` | `send_raw_enter_or_ask` | 不自动乱杀进程 |
| diff exists but scope unknown/untracked unexpected | `needs_review` | `inspect_candidate_diff` | 后续 Slice 收集/审查 |

### 5.4 Slice 4 测试建议

| 测试 | fixture 输入 | 期望 |
|---|---|---|
| running output | replay snapshot: running + output chunks | `status=running`，不是 idle |
| idle no diff | N 个 wait windows: running + no output + clean git | `status=idle_wait` / recommendation inspect |
| process exit with diff | exited 0 + tracked diff | `status=completed`，`completion_trusted=false` |
| process exit no diff | exited 0 + clean git | `status=needs_attention` 或 `failed_or_noop` |
| pasted content suspected | log has `[Pasted Content]` + no diff | `status=needs_attention`，`next_action=send_raw_enter_or_ask` |
| process missing | no process found for session id | `status=process_missing` |
| untracked evidence | untracked-only candidate | untracked files present in evidence，不能丢 |

### 5.5 Slice 4 明确非目标

- 不启动真实 TUI。
- 不调用 `terminal(...)` 或 `process(...)` tool。
- 不执行真实 `codex-yuna --enable goals`。
- 不做 `collect_candidate` 完整 review packet。
- 不自动 commit/push/deploy/restart。
- 不把 raw TUI log 全量写入模型上下文。

## 6. Slice 4 之后才考虑 Slice 5

Slice 5 才是 behind explicit authorization 的真实 TUI smoke：

```text
用户明确授权
→ clean/isolated worktree
→ prepare one-line goal
→ launch real `codex-yuna --enable goals` PTY background
→ submit `/goal`
→ monitor bounded wait windows
→ collect evidence
→ Hermes review
```

Slice 5 之前必须先有：

- Slice 4 adapter contract 和 replay tests。
- 真实 TUI launch 的 stop conditions。
- process/session registry 的最小记录方式。
- raw log bounded tail 规则。
- candidate diff/staged/untracked evidence contract。

## 7. 下一步执行建议

推荐下一步仍然做文档/测试优先：

```text
Slice 4A：写 replay fixture tests + pure classifier contract。
Slice 4B：实现纯函数 classifier，不接外部工具。
Slice 4C：设计真实 adapter wrapper，但默认 disabled/mock-only。
```

不要直接进入真实 TUI。
