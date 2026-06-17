# `codex_goal_run` Slice Handoff

> 状态：Slice 1-7F mock/replay/gated driver、real TUI smoke runbook、一次授权真实 TUI smoke、smoke 经验回归、`collect_candidate` review handoff、`review_candidate` replay review lane、真实 review runner adapter call-site、bounded packet review guard adapter、subprocess-backed guard runner wrapper、以及显式 opt-in runtime subprocess gate 已实现；真实 guard subprocess runner 仍默认关闭。
> 日期：2026-06-17
> 关联设计：`docs/working-notes/hermes-codex-goal-run-design.md`
> 关联 runbook：`docs/working-notes/hermes-codex-goal-run-real-tui-smoke-runbook.md`
> 关联实现：`tools/codex_goal_run_tool.py`、`tests/tools/test_codex_goal_run_tool.py`

## 1. 当前边界结论

```text
Slice 1-7F = official Codex /goal driver 的 mock-first + replay classifier + disabled/gated adapter runner 骨架 + real TUI smoke runbook + 一次授权真实 TUI smoke + smoke 经验回归 + collect_candidate review handoff + review_candidate replay review lane + real review runner adapter call-site + bounded packet review guard adapter + subprocess-backed guard runner wrapper + 显式 opt-in runtime subprocess gate。
它证明 API、artifact、launch lifecycle、monitor state machine、process/log/git snapshot classifier、disabled adapter wrapper、gated runner interface、monitor_goal call-site、最小真实 smoke 边界和 smoke 后硬化可以被 Hermes 编排。
Slice 5 曾在用户明确授权下启动一次真实 Codex TUI；Slice 6 不再启动真实 TUI，只固化测试和文档。
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
- Slice 4F 只新增 runbook；它不是执行记录，不授权真实 TUI。
- Slice 5 的真实 TUI smoke 只在 isolated worktree `/tmp/hermes-codex-goal-smoke-20260617-072947` 中产生 untracked marker candidate。
- Slice 6 固化经验：`Goal blocked` + candidate evidence 应视为 candidate ready；`/tmp` worktree 不应让 tests 使用 `Path.cwd()` 假设 outside `/tmp`。
- Slice 7A 新增 `collect_candidate`：允许 dirty candidate worktree，仅读 git evidence，生成 bounded `review_handoff` / `review_packet`，不跑 Codex preflight、不启动真实 TUI。
- Slice 7B 新增 `review_candidate`：消费同一 candidate packet，默认 review runner disabled；只接受 replay/fake review 结果，不执行真实 Codex review runner。
- Slice 7C 新增真实 review runner adapter call-site：`allow_real_review=True` 才会调用注入 runner；默认 runner 为空，缺失时 fail-closed。
- Slice 7D 新增 bounded packet review guard adapter：`review_guard_enabled=True` 才走 packet-only prompt；guard runner 仍需注入，默认不执行真实 subprocess。
- Slice 7E 新增 subprocess-backed guard runner wrapper：可写 packet/prompt artifact 并调用 `codex_review_guard.py --review-packet-file`，但默认仍不注入 runtime path。
- Slice 7F 新增 `review_guard_subprocess_enabled`：只有 `review_runner_enabled=True` + `allow_real_review=True` + `review_guard_enabled=True` + `review_guard_subprocess_enabled=True` 四重 opt-in 时才接入 7E subprocess wrapper；默认和未授权路径都不调用 subprocess。
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
| Slice 4F | real TUI smoke runbook | 写明未来 Slice 5 最小 smoke 的授权门、前置条件、stop condition、证据包、失败/成功模板 | runbook 落盘并链接；明确不执行真实 TUI；明确 `completion_trusted=false` | 不启动真实 TUI；不执行 runbook；不创建真实 worktree；不调用 terminal/process adapter |
| Slice 5 | authorized real TUI smoke | 在 isolated worktree 启动一次真实 `codex-yuna --enable goals`，提交 one-line `/goal`，收集 bounded evidence | TUI session `proc_b89d474584b7` exit 0；产生 untracked marker；`git diff --check` 通过；source focused tests 45 passed | 不 push；不部署；不重启；不 commit；不 merge；不接 runtime 默认真实 adapter |
| Slice 6 | smoke hardening docs + regression tests | 把 Slice 5 经验写回 classifier/tests/docs | `Goal blocked` + untracked candidate → `completed`/collect; outside tmp test 改用 monkeypatched fake `_TMP_ROOT`，避免 `/tmp` worktree 假设且不触碰固定系统路径 | 不启动真实 TUI；不删除 smoke worktree；不 push/deploy/restart |
| Slice 7A | `collect_candidate` review handoff | dirty candidate worktree 不阻塞；收集 tracked/staged/untracked/diff_stat/status evidence；生成 bounded `review_handoff.review_packet` | schema 暴露 `collect_candidate`；dirty repo 可返回 `candidate_ready_for_review`；clean repo 返回 `no_candidate_changes` | 不启动真实 TUI；不跑 Codex preflight；不调用 terminal/process；不执行 review；不 push/deploy/restart |
| Slice 7B | `review_candidate` replay review lane | 复用 collect candidate evidence + review handoff；接收 `review_replay`；把 passed / blocked / unavailable 分类成后续动作 | schema 暴露 `review_candidate` / `review_runner_enabled` / `allow_real_review` / `review_replay`；`aggregated_output_flood` => `review_unavailable`；默认 disabled | 不执行真实 review guard/packet runner；不启动真实 TUI；不调用 terminal/process；不 push/deploy/restart |
| Slice 7C | real review runner adapter call-site | `review_candidate` 在 `review_runner_enabled=True` + `allow_real_review=True` 时才调用注入 runner；runner 缺失 fail-closed | unauthorized path 不调用 runner；missing runner 返回 `review_runner_missing`；fake injected runner 只收到 `review_packet`，不收 raw TUI log | 不提供真实 runner 实现；不执行 review guard/packet runner；不启动真实 TUI；不 push/deploy/restart |
| Slice 7D | bounded packet review guard adapter | `review_guard_enabled=True` 时把 bounded `review_packet` 包成 packet-only prompt 交给注入 guard runner；guard output 映射 passed/blocked/unavailable | schema 暴露 `review_guard_enabled`；guard disabled 不调用；fake guard 只收 packet-only prompt；`aggregated_output_flood`/unusable => `review_unavailable` | 不注入真实 subprocess guard runner；不执行真实 Codex review；不启动真实 TUI；不 push/deploy/restart |
| Slice 7E | subprocess-backed guard runner wrapper | `_run_candidate_review_guard_subprocess` 写 prompt/packet/raw/final artifacts，用 `codex_review_guard.py --review-packet-file` 调 guarded review；输出只保留 bounded metadata | fake subprocess runner 验证命令参数含 `--review-packet-file` 且 `shell=False`；missing script / non-json / unusable flood 均 fail-closed | 默认不注入 `_REAL_CANDIDATE_REVIEW_GUARD_RUNNER`；不执行真实 Codex review；不启动真实 TUI；不 push/deploy/restart |
| Slice 7F | explicit subprocess runtime gate | schema 暴露 `review_guard_subprocess_enabled`；`review_candidate` 四重 opt-in 才把 7E wrapper 接到 guard adapter | 默认 false 不调用 subprocess；未授权不调用 subprocess；fake subprocess runner 验证 packet-only + `shell=False` + 不启动 TUI | 默认不执行真实 Codex review；需要显式四重 gate；不启动真实 TUI；不 push/deploy/restart |

## 3. Mode 当前状态对照

| mode | 输入重点 | clean worktree 要求 | 输出重点 | candidate disposition | 当前限制 |
|---|---|---:|---|---|---|
| `dry_run_plan` | required fields + scope/non-goals/tests | 是 | bounded plan + preflight | `planning_only` | 只计划，不写 artifact |
| `prepare_goal` | `goal_artifact_dir` / optional explicit file paths | 是 | `goal_files.rich_goal_file` + `goal_files.one_line_goal_file` | `needs_review` | artifact 必须 `/tmp` 且 repo 外 |
| `launch_goal` | `one_line_goal_file` | 是 | mock process + submit/raw_enter evidence | `needs_review` if mocked launch succeeds; default `planning_only` | 默认 launcher disabled；真实 TUI 未接入 |
| `monitor_goal` | `session_id`、`monitor_interval_seconds`、`max_wait_windows` | 否，dirty 作为 evidence | `monitor.state` + wait-window summary | `running` 或 `needs_review` | 默认 poll hook 不读真实 process/log/git diff |
| `collect_candidate` | optional `session_id` + scope/verification metadata | 否，dirty 是 candidate evidence | `candidate_evidence` + `review_handoff.review_packet` | `needs_review` when evidence exists | 只读 git evidence；不跑 TUI/preflight/review |
| `review_candidate` | candidate worktree + optional `review_replay` / gated runner flags / `review_guard_enabled` / `review_guard_subprocess_enabled` | 否，dirty 是 candidate evidence | `review` + `review_handoff.review_packet` | `needs_verification` / `needs_revision` / `needs_review` | 默认 disabled；subprocess wrapper 只有四重 opt-in 才接入；默认不跑真实 review |
| pure classifier | replay/mock `snapshot` | 不适用 | `result_status` + `monitor` + `candidate_evidence` | always untrusted | 只被测试/后续 adapter 调用；当前不接真实工具 |
| disabled adapters | replay/default params | 不适用 | composed process/log/git snapshot | untrusted evidence only | 默认 disabled；只支持 replay/default，不读真实系统 |
| gated runner | `adapter_enabled` / `allow_real_adapter` / injected runners | 不适用 | status + snapshot + classification + stop_condition | always untrusted | 默认 disabled；未授权 blocked；当前无真实 runner |
| monitor adapter call-site | `adapter_enabled` / `allow_real_adapter` | 不适用 | top-level result + nested `adapter` evidence | always untrusted | default = old mock poll；explicit adapter path still fail-closed |
| smoke runbook | future explicit user authorization | 不适用 | execution checklist + evidence template | `completion_trusted=false` | docs-only；not an execution record |
| real smoke evidence | explicit user authorization only | 不适用 | bounded log/process/git evidence | `completion_trusted=false` | isolated worktree only；candidate evidence, not final success |

## 4. 当前提交证据

```text
6ac1dbfb1 feat(codex): add goal run prepare driver
35f0bfbaf feat(codex): add mock goal launch lifecycle
65dccf854 feat(codex): add mock goal monitor lifecycle
3990f8e68 feat(codex): add goal snapshot classifier
a43dc5684 feat(codex): add disabled goal adapter wrappers
f55af62e5 feat(codex): add gated goal adapter runner
00a576d51 feat(codex): wire gated adapter call-site
Slice 4F docs commit: docs(codex): add goal TUI smoke runbook
Slice 6 commit: test/docs(codex): harden goal TUI smoke learnings
Slice 7A candidate: collect_candidate review handoff
Slice 7B candidate: review_candidate replay review lane
Slice 7C candidate: real review runner adapter call-site
Slice 7D candidate: bounded packet review guard adapter
Slice 7E candidate: subprocess-backed guard runner wrapper
Slice 7F candidate: explicit subprocess runtime gate
```

测试证据来自最近实现收口：

```text
python3 -m pytest tests/tools/test_codex_goal_run_tool.py -q -o addopts=''
79 passed after Slice 7F

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

## 5. Slice 4 当前状态：real adapter contract / replay classifier / disabled wrapper / gated runner / monitor call-site / smoke runbook，未接真实 TUI

Slice 4A/4B/4C/4D/4E/4F 已完成：把真实 adapter 的输入/输出契约设计清楚，用 replay/mock snapshot tests 锁住分类行为，提供默认 disabled 的 adapter wrapper contract，定义 gated runner interface / stop condition，把 `monitor_goal` call-site 接到 gated path，并新增最小真实 TUI smoke runbook。

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
| real TUI smoke runbook | 未来 Slice 5 的授权门、步骤、stop condition、证据包 | 否，已实现 docs-only runbook |

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
| smoke runbook | future explicit authorization only | 当前不执行；只定义 runbook |
| real smoke `Goal blocked` | `Goal blocked (/goal resume)` + untracked candidate | 不是失败；视作 candidate ready for Hermes review |
| `/tmp` smoke worktree | tests run with `Path.cwd()` under `/tmp` | tests 不应把 `Path.cwd()` 当 outside `/tmp`；outside tmp 用 monkeypatched fake `_TMP_ROOT` |

### 5.5 Slice 4 明确非目标

- 不启动真实 TUI。
- 不调用 `terminal(...)` 或 `process(...)` tool。
- 不执行真实 `codex-yuna --enable goals`。
- 不做 `collect_candidate` 完整 review packet。
- 不自动 commit/push/deploy/restart。
- 不把 raw TUI log 全量写入模型上下文。

## 6. Slice 5/6 真实 smoke 与硬化结论

2026-06-17 授权 smoke 结果：

```text
worktree: /tmp/hermes-codex-goal-smoke-20260617-072947
branch: codex-goal-smoke-20260617-072947
session: proc_b89d474584b7
exit_code: 0
candidate: docs/working-notes/hermes-codex-goal-tui-smoke-marker-20260617-072947.md
classification: candidate evidence only; completion_trusted=false
```

学到的 runtime contract：

- TUI can emit high-volume output; Hermes process containment kept context-safe summary.
- `Goal blocked (/goal resume)` plus candidate evidence means Codex is waiting for Hermes review, not a task failure.
- untracked-only candidate is valid evidence and must not be dropped.
- smoke worktree may live under `/tmp`; tests must not assume `Path.cwd()` is outside `/tmp`.
- `/quit` + raw Enter can close the idle/blocked TUI session.

## 7. Slice 4 之后才考虑 Slice 5

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

## 8. 下一步执行建议

推荐下一步仍然不进真实 TUI：

```text
Slice 7G / closeout：收口验收、独立 review、确认是否需要进入更高层 orchestrator 汇总；仍默认不跑真实 TUI，不自动执行真实 review。
```

不要重复真实 TUI smoke，除非用户重新明确授权。
