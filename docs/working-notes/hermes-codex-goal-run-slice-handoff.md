# `codex_goal_run` Slice Handoff

> 状态：Slice 1-4E mock/replay/gated driver 已实现并本地提交；真实 Codex TUI 尚未接入。
> 日期：2026-06-16
> 关联设计：`docs/working-notes/hermes-codex-goal-run-design.md`
> 关联实现：`tools/codex_goal_run_tool.py`、`tests/tools/test_codex_goal_run_tool.py`

## 1. 当前边界结论

```text
Slice 1-4E = official Codex /goal driver 的 mock-first + replay classifier + disabled/gated adapter runner 骨架。
它证明 API、artifact、launch lifecycle、monitor state machine、process/log/git snapshot classifier、disabled adapter wrapper、gated runner interface 和 monitor_goal call-site 可以被 Hermes 编排。
它没有启动真实 Codex TUI，也没有执行真实 `codex-yuna --enable goals`。
```

核心边界：

- `completion_trusted` 始终为 `false`。
- `Codex Goal achieved / completed` 只代表 candidate 进入 Hermes review，不代表任务验收通过。
- `launch_goal` 默认 launcher 是 disabled/mock-only。
- `monitor_goal` 默认 poll hook 是 side-effect-free mock。
- `prepare_goal` / `launch_goal` 仍要求 clean worktree。
- `monitor_goal` 允许 dirty candidate worktree，但 dirty 只作为 evidence，不作为 final success。
- `_classify_goal_snapshot` 是纯函数，只吃 replay/mock snapshot。
- `_collect_goal_process_snapshot` / `_collect_goal_git_evidence` / `_compose_goal_snapshot` 默认 disabled/replay-only。
- `_run_goal_adapter_once` 默认 disabled，只有显式 `adapter_enabled=True` 且 `allow_real_adapter=True` 才调用注入 runner；当前测试只用 fake injected runner。
- `monitor_goal` 默认继续走旧 mock poll；只有显式 `adapter_enabled=True` 才进入 gated adapter call-site。
- 不 push / deploy / restart / merge。
- 不读 secret，不跑真实 provider / 真实数据 / 真实媒体。

## 2. Slice 1-4 对照表

| Slice | 已有 mode / 能力 | 当前行为 | 已验证点 | 不做什么 |
|---|---|---|---|---|
| Slice 1 | `dry_run_plan`、`prepare_goal` | 校验输入、repo、dirty policy、Codex goals preflight；生成 rich goal + one-line goal 到 `/tmp` | schema/toolset 暴露；missing goals feature blocker；artifact 不写 repo；artifact path 必须在 `/tmp` 且不在 repo 内；单行 `/goal` 包含 scope/non-goals/tests/stop conditions | 不启动 TUI；不提交 goal；不改 repo；不自动 enable goals |
| Slice 2 | `launch_goal` mock lifecycle | 读取 `/tmp` 单行 goal；构造 `codex-yuna --enable goals` PTY/background/notify 参数；调用 mockable hooks；默认返回 `launch_unavailable` | 单行 goal 校验；多行/空目标/多余空行 rejected；`pty=True`、`background=True`、`notify_on_complete=True`；submit 后 raw `\r`；不使用 `codex-yuna exec` | 默认不启动真实 TUI；不调用 terminal/process tool；不提交真实 Codex |
| Slice 3 | `monitor_goal` mock state machine | 按 wait-window 调用 `_poll_goal_session`；分类 `idle_wait` / `running` / `completed` / `failed` / `missing_session_id` | idle composer message；持续有输出返回 `running`；completed/failed 都不 trusted；missing session 先 blocked；dirty candidate worktree 可作为 evidence 继续 monitor | 不读取真实 process/log；不收集真实 git diff evidence；不关闭 TUI；不做 candidate review handoff |
| Slice 4A/4B | replay snapshot classifier | `_bounded_log_tail` 限制 raw log；`_classify_goal_snapshot` 纯函数把 process/log/git evidence 映射成状态 | process missing 保留 candidate evidence；running output 不误报 idle；`[Pasted Content]` + no diff 走 attention；`Goal achieved` + diff 走 collect；nonzero exit 始终 failed；untracked-only evidence 不丢 | 不调用 terminal/process/subprocess；不启动真实 TUI；不执行真实 `codex-yuna --enable goals`；不做完整 adapter wrapper |
| Slice 4C | disabled adapter wrapper contract | `_collect_goal_process_snapshot` / `_collect_goal_git_evidence` / `_compose_goal_snapshot` 默认 disabled，可吃 replay fixture | missing repo 也安全；default adapters 不读真实进程/git；process replay 和 git replay 被规范化；composed replay snapshot 可直接喂 classifier | 不接真实 terminal/process/git adapter；不启动真实 TUI；不执行真实 `codex-yuna --enable goals` |
| Slice 4D | gated adapter runner contract | `_goal_adapter_stop_condition` / `_run_goal_adapter_once` 定义 runner gate 和 stop reason | default disabled 不调用 runner；未授权不调用 runner；授权路径只调用注入 runner；candidate ready 停止；failed/attention/process_missing 保留具体 stop reason | 不接真实 terminal/process/git runner；不启动真实 TUI；不执行真实 `codex-yuna --enable goals` |
| Slice 4E | `monitor_goal` call-site contract | schema 暴露 `adapter_enabled` / `allow_real_adapter`；`monitor_goal` 可进入 gated adapter path | 默认仍旧 mock poll；`adapter_enabled=True` 不用 `_poll_goal_session`；未授权 blocked；授权但无 runner fail-closed | 不接真实 runner；不调用 terminal/process；不启动真实 TUI；不执行真实 `codex-yuna --enable goals` |

## 3. Mode 当前状态对照

| mode | 输入重点 | clean worktree 要求 | 输出重点 | candidate disposition | 当前限制 |
|---|---|---:|---|---|---|
| `dry_run_plan` | required fields + scope/non-goals/tests | 是 | bounded plan + preflight | `planning_only` | 只计划，不写 artifact |
| `prepare_goal` | `goal_artifact_dir` / optional explicit file paths | 是 | `goal_files.rich_goal_file` + `goal_files.one_line_goal_file` | `needs_review` | artifact 必须 `/tmp` 且 repo 外 |
| `launch_goal` | `one_line_goal_file` | 是 | mock process + submit/raw_enter evidence | `needs_review` if mocked launch succeeds; default `planning_only` | 默认 launcher disabled；真实 TUI 未接入 |
| `monitor_goal` | `session_id`、`monitor_interval_seconds`、`max_wait_windows` | 否，dirty 作为 evidence | `monitor.state` + wait-window summary | `running` 或 `needs_review` | 默认 poll hook 不读真实 process/log/git diff |
| pure classifier | replay/mock `snapshot` | 不适用 | `result_status` + `monitor` + `candidate_evidence` | always untrusted | 只被测试/后续 adapter 调用；当前不接真实工具 |
| disabled adapters | replay/default params | 不适用 | composed process/log/git snapshot | untrusted evidence only | 默认 disabled；只支持 replay/default，不读真实系统 |
| gated runner | `adapter_enabled` / `allow_real_adapter` / injected runners | 不适用 | status + snapshot + classification + stop_condition | always untrusted | 默认 disabled；未授权 blocked；当前无真实 runner |
| monitor adapter call-site | `adapter_enabled` / `allow_real_adapter` | 不适用 | top-level result + nested `adapter` evidence | always untrusted | default = old mock poll；explicit adapter path still fail-closed |

## 4. 当前提交证据

```text
6ac1dbfb1 feat(codex): add goal run prepare driver
35f0bfbaf feat(codex): add mock goal launch lifecycle
65dccf854 feat(codex): add mock goal monitor lifecycle
3990f8e68 feat(codex): add goal snapshot classifier
a43dc5684 feat(codex): add disabled goal adapter wrappers
f55af62e5 feat(codex): add gated goal adapter runner
00a576d51 feat(codex): wire gated adapter call-site
```

测试证据来自最近实现收口：

```text
python3 -m pytest tests/tools/test_codex_goal_run_tool.py -q -o addopts=''
45 passed

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
_bounded_log_tail True
_classify_goal_snapshot True
_collect_goal_process_snapshot True
_collect_goal_git_evidence True
_compose_goal_snapshot True
_goal_adapter_stop_condition True
_run_goal_adapter_once True
monitor_goal_adapter_call_site True
```

说明：`enable_goals_command_count 1` 是 command 字符串，不是本轮真实执行。

## 5. Slice 4 当前状态：real adapter contract / replay classifier / disabled wrapper / gated runner / monitor call-site，未接真实 TUI

Slice 4A/4B/4C/4D/4E 已完成：把真实 adapter 的输入/输出契约设计清楚，用 replay/mock snapshot tests 锁住分类行为，提供默认 disabled 的 adapter wrapper contract，定义 gated runner interface / stop condition，并把 `monitor_goal` call-site 接到 gated path。

### 5.1 Slice 4 目标

```text
定义真实 terminal/process adapter 的 evidence shape，
把真实 process poll/log/git evidence 映射成 monitor states，
但仍不调用真实 terminal/process，不启动 `codex-yuna --enable goals`。
```

### 5.2 内部边界

| 内部函数 / 数据结构 | 作用 | Slice 4 是否真实调用外部工具 |
|---|---|---:|
| `_bounded_log_tail(raw)` | 限制 raw TUI log 尾部和 metadata，防止 flood | 否，已实现 |
| `_classify_goal_snapshot(snapshot)` | 纯函数：把 process/log/git evidence 映射为 state | 否，已实现 |
| `_collect_goal_process_snapshot(session_id)` | 描述真实 process 状态的 adapter contract | 否，已实现 disabled/replay wrapper |
| `_collect_goal_git_evidence(repo)` | 描述 git status/diff/untracked/staged evidence 的 contract | 否，已实现 disabled/replay wrapper |
| `_compose_goal_snapshot(...)` | 组合 process/log/git snapshot 并喂给 classifier | 否，已实现 disabled/replay wrapper |
| `_goal_adapter_stop_condition(classification)` | 将 classifier result 转为 runner stop condition | 否，已实现纯函数 |
| `_run_goal_adapter_once(...)` | gated runner interface；默认 disabled；授权时只调用注入 runner | 否，已实现 gated/injected-only wrapper |
| `monitor_goal` adapter call-site | 用户传 `adapter_enabled=True` 时进入 gated adapter path | 否，已实现 fail-closed call-site |

### 5.3 Slice 4 状态映射

| 真实证据组合 | 目标状态 | next_action | 说明 |
|---|---|---|---|
| process running + new output | `running` | `continue_monitoring_goal` | 有活动，不是 idle |
| process running + N 个窗口无输出 + no diff | `idle_wait` | `continue_monitoring_or_inspect_tui` | 可能卡住或等输入 |
| process exited 0 + diff/staged/untracked 非空 | `completed` | `collect_candidate_for_hermes_review` | 仍需 Hermes review |
| process exited nonzero | `failed` | `inspect_goal_failure` | 不 trusted，不能被 `Goal achieved` 覆盖 |
| process missing / session unknown | `process_missing` | `inspect_process_registry` | 需要人工判断，不猜；candidate evidence 仍保留 |
| log contains `Goal achieved` + candidate diff | `completed` | `collect_candidate_for_hermes_review` | Goal achieved 只是 candidate evidence |
| log contains `[Pasted Content]` + no diff + running | `needs_attention` | `send_raw_enter_or_ask` | 不自动乱杀进程 |
| historical `[Pasted Content]` + later `Goal achieved` + diff | `completed` | `collect_candidate_for_hermes_review` | 后续完成证据优先于历史 paste warning |

### 5.4 Slice 4 已覆盖测试

| 测试 | fixture 输入 | 期望 |
|---|---|---|
| bounded log tail | long raw log | only bounded tail + metadata |
| running output | replay snapshot: running + output chunks | `status=running`，不是 idle |
| idle no diff | N 个 wait windows: running + no output + clean git | `status=idle_wait` / recommendation inspect |
| process exit with diff | exited 0 + tracked diff | `status=completed`，`completion_trusted=false` |
| process exit no diff | exited 0 + clean git | `status=needs_attention` |
| process exit nonzero | exited nonzero with/without diff | `status=failed` |
| pasted content suspected | log has `[Pasted Content]` + no diff | `status=needs_attention`，`next_action=send_raw_enter_or_ask` |
| process missing | no process found for session id | `status=process_missing`，candidate evidence 不丢 |
| untracked evidence | untracked-only candidate | untracked files present in evidence，不能丢 |
| historical paste + later goal achieved diff | log 同时有 `[Pasted Content]` 和 `Goal achieved` + diff | completed/collect candidate 优先 |
| default disabled adapters | missing repo + no replay | safe disabled snapshot，不读 repo/process |
| process replay adapter | process/log replay fixture | normalized process/log snapshot |
| git replay adapter | git replay fixture | changed/staged/untracked/diff_stat 不丢 |
| default gated runner | adapter disabled + injected forbidden runners | 不调用 runner，返回 `adapter_disabled` |
| unauthorized gated runner | `adapter_enabled=True` but `allow_real_adapter=False` | 不调用 runner，返回 `real_adapter_not_authorized` |
| authorized injected runner | fake process/git runners | 只调用 injected runner，结果喂 classifier + stop condition |
| stop condition reason | failed/attention/process_missing | 保留具体 reason，不泛化成 blocked |
| monitor default path | no adapter flags | 继续使用 `_poll_goal_session` mock，不进入 adapter |
| monitor unauthorized adapter | `adapter_enabled=True`, `allow_real_adapter=False` | 不 poll，不跑 runner，返回 `real_adapter_not_authorized` |
| monitor authorized without runner | `adapter_enabled=True`, `allow_real_adapter=True`, no runner | 不 poll，返回 `real_adapter_runner_missing` |

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

推荐下一步仍然不进真实 TUI：

```text
Slice 4F：准备最小真实 TUI smoke runbook，不执行。
Slice 5：只有用户单独授权后，才做真实 TUI smoke。
```

不要直接进入真实 TUI。
