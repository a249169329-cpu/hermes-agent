# `codex_goal_run` Runtime Driver Design

> 状态：设计文档 / implementation plan；Slice 1-7B mock-first/replay/gated runtime skeleton、real TUI smoke runbook、一次授权 smoke、smoke hardening、`collect_candidate` review handoff、以及 `review_candidate` replay review lane 已实现；真实 adapter 仍未接入 runtime 默认路径。
> 日期：2026-06-17
> 关联文档：
> - `docs/working-notes/hermes-codex-division-of-labor.md`
> - `docs/working-notes/hermes-codex-driver-selection-guarded-vs-goal.md`
> - `docs/working-notes/hermes-codex-goal-run-slice-handoff.md`
> - `docs/working-notes/hermes-codex-goal-run-real-tui-smoke-runbook.md`
> - skill：`autonomous-ai-agents/codex-goal-stage-workflow`
> - skill reference：`codex` / `references/official-goal-mode-codex-cli.md`（通过 `skill_view` 读取，不是 repo 内文件）

## 0. 当前实现快照

截至 2026-06-17，本设计已分片落地 mock-first/replay 骨架：

| Slice | commit | 覆盖范围 | 真实 TUI |
|---|---|---|---|
| Slice 1 | `6ac1dbfb1 feat(codex): add goal run prepare driver` | `dry_run_plan` / `prepare_goal`、schema、preflight、`/tmp` goal artifacts | 否 |
| Slice 2 | `35f0bfbaf feat(codex): add mock goal launch lifecycle` | `launch_goal` mock lifecycle、one-line goal validation、PTY/background/notify 参数、raw `\r` hook | 否 |
| Slice 3 | `65dccf854 feat(codex): add mock goal monitor lifecycle` | `monitor_goal` wait-window / idle composer 状态机、dirty candidate evidence、completed/failed/running/idle 分类 | 否 |
| Slice 4A/4B | `3990f8e68 feat(codex): add goal snapshot classifier` | `_bounded_log_tail` + `_classify_goal_snapshot` replay classifier；process/log/git evidence → monitor states | 否 |
| Slice 4C | `a43dc5684 feat(codex): add disabled goal adapter wrappers` | `_collect_goal_process_snapshot` / `_collect_goal_git_evidence` / `_compose_goal_snapshot` disabled/replay wrappers | 否 |
| Slice 4D | `f55af62e5 feat(codex): add gated goal adapter runner` | `_goal_adapter_stop_condition` / `_run_goal_adapter_once` gated runner interface，默认 disabled | 否 |
| Slice 4E | `00a576d51 feat(codex): wire gated adapter call-site` | `monitor_goal` adapter call-site；schema 暴露 `adapter_enabled` / `allow_real_adapter`；默认旧 mock poll | 否 |
| Slice 4F | `docs(codex): add goal TUI smoke runbook` | 最小真实 TUI smoke runbook：授权门、前置检查、stop condition、证据包、失败/成功模板 | 否 |
| Slice 5 | authorized real TUI smoke | 在 isolated `/tmp` worktree 启动一次 `codex-yuna --enable goals`；产出 untracked marker candidate；TUI exit 0 | 是，仅一次授权 smoke |
| Slice 6 | `test/docs(codex): harden goal TUI smoke learnings` | 固化 smoke 经验：`Goal blocked` + candidate evidence => candidate ready；测试通过 monkeypatched `_TMP_ROOT` 不再假设 `Path.cwd()` outside `/tmp` | 否 |
| Slice 7A | `collect_candidate` review handoff | dirty candidate worktree 可收集 tracked/staged/untracked/diff_stat/status evidence；生成 bounded `review_handoff.review_packet` | 否 |
| Slice 7B | `review_candidate` replay review lane | 复用 candidate packet；接收 `review_replay`；分类 passed / blocked / unavailable；默认 review runner disabled | 否 |

详细对照表与 Slice 4 边界计划见：

```text
docs/working-notes/hermes-codex-goal-run-slice-handoff.md
```

当前仍然不做：

```text
不启动真实 Codex TUI。
不执行真实 `codex-yuna --enable goals`。
不调用 terminal/process tool 作为 monitor adapter。
不执行 review guard / review packet runner。
不 push / deploy / restart。
```

## 1. 目标

设计一个 Hermes runtime driver：`codex_goal_run`。

它负责把 **official Codex TUI `/goal`** 纳入 Hermes 阶段编排，但不替代现有 guarded lane。

一句话：

```text
codex_goal_run = Hermes 对 Codex 官方 /goal TUI 的受控启动、提交、监控、取证、收口入口。
```

它解决的问题：

1. 官方 `/goal` 必须走 interactive TUI，不是 `codex exec "goal-style prompt"`。
2. QQ/WebUI PTY 提交 `/goal` 有特殊坑：多行 paste、`[Pasted Content]`、需要 raw `\r`。
3. `process(wait)` timeout 不是失败，必须按 wait-window 语义处理。
4. `Goal achieved` 不等于 Hermes 验收通过，只代表 candidate 完成。
5. `git diff` 不覆盖 untracked，必须统一收集 changed files / untracked / staged / status。
6. Goal 不是 fail-closed guard，必须显式 stop 条件和授权边界。

## 2. 非目标

`codex_goal_run` 不做这些事：

- 不替代 `codex_staged_implement` / `codex_workflow_run`。
- 不把 ordinary guarded lane 和 official `/goal` 混成一个入口。
- 不用 `codex-yuna exec` 模拟 `/goal`。
- 不自动 push / deploy / restart / merge。
- 不自动读取、打印或传递 secret。
- 不运行真实 provider / 真实数据 / 真实媒体，除非用户另行明确授权。
- 不把 Codex self-report 当最终成功。
- 不把 TUI raw log 大段塞回模型上下文。
- 不在 shared dirty worktree 里直接开跑。

## 3. 当前证据

2026-06-16 只读核对结果：

```text
当前 repo 已有 guarded lane：
- tools/codex_workflow_run_tool.py
- tools/codex_staged_implement_tool.py
- scripts/runtime/codex_review_guard.py
- scripts/runtime/codex_review_packet.py
- scripts/runtime/codex_impl_guard.py
- scripts/runtime/codex_stage_runner.py
- tests/tools/test_codex_workflow_run_tool.py
- tests/tools/test_codex_staged_implement_tool.py
- tests/scripts/test_codex_review_guard.py
- tests/scripts/test_codex_review_packet.py
- tests/scripts/test_codex_impl_guard.py
- tests/scripts/test_codex_stage_runner.py
```

只读搜索结果：

```text
codex_goal_run: 0
codex-yuna --enable goals: 0
--enable goals: 0
features list: 0
```

说明：

```text
当前 runtime 有 ordinary guarded Codex lane。
当前 runtime 没有 official Codex TUI /goal driver。
```

注意：仓库里有 Hermes 自己的 `/goal` 状态/判定逻辑，但那不是 Codex TUI `/goal` driver。

## 4. 与现有 guarded lane 的关系

| 场景 | 用哪个 driver |
|---|---|
| 小修、窄文件、一次性 bounded implementation | `codex_staged_implement` / `codex_workflow_run` |
| read-only diff review | `codex_review_guard` / `codex_review_packet` |
| 官方 Codex TUI `/goal` | `codex_goal_run` |
| tiny docs/copy/CSS 小改 | Hermes direct edit |
| push/deploy/restart/真实 provider | 停下问用户，不由 driver 自动做 |

`codex_goal_run` 的产物仍然进入同一 Hermes 验收出口：

```text
candidate diff
→ Hermes inspect changed files
→ focused verification
→ optional bounded review packet
→ Hermes final decision
```

## 5. 建议 tool API

### 5.1 Tool name

```text
codex_goal_run
```

### 5.2 Modes

建议分阶段实现，不要一口气做全自动。

| mode | Driver 自身写 repo？ | 启动 TUI？ | 用途 |
|---|---:|---:|---|
| `dry_run_plan` | 否 | 否 | 校验输入、生成 bounded `/goal` 计划和风险清单 |
| `prepare_goal` | 否，默认写 `/tmp` | 否 | 写 rich goal file + one-line goal file，返回路径 |
| `launch_goal` | 否；但启动后的 Codex TUI 可能修改 repo | 是 | 启动 `codex-yuna --enable goals`，提交单行 `/goal`，返回 process session id |
| `monitor_goal` | 否 | 不新启 | 读取 process/log + git evidence，分类状态 |
| `collect_candidate` | 否 | 不新启 | 在 Goal 停止后收集 candidate diff/status/untracked evidence |

首版建议只做：

```text
dry_run_plan → prepare_goal → launch_goal → monitor_goal → collect_candidate
```

不要首版就做自动 commit / 自动 follow-up goal。

### 5.3 Input schema 草案

```json
{
  "workdir": "/path/to/repo",
  "stage_id": "stage-1",
  "objective": "Complete one bounded stage objective",
  "docs_to_read": ["docs/...md"],
  "allowed_files": ["path/file.py"],
  "allowed_globs": ["src/foo/**", "tests/foo/**"],
  "non_goals": ["Do not implement next stage"],
  "required_verification": ["python3 -m pytest ... -q -o addopts=''"],
  "stop_conditions": ["Need push/deploy/restart", "Need secret", "Scope conflict"],
  "mode": "dry_run_plan",
  "dirty_baseline_policy": "require-clean",
  "allow_isolated_worktree": false,
  "goal_artifact_dir": null,
  "rich_goal_file": null,
  "one_line_goal_file": null,
  "session_id": null,
  "timeout_seconds": 600,
  "monitor_interval_seconds": 60,
  "max_wait_windows": 10,
  "standing_authorization": false
}
```

### 5.4 Required fields

```text
workdir
stage_id
objective
mode
dirty_baseline_policy
```

### 5.5 Optional but recommended fields

```text
docs_to_read
allowed_files / allowed_globs
non_goals
required_verification
stop_conditions
allow_isolated_worktree
timeout_seconds
```

### 5.6 Mode-specific fields

不同 mode 需要的额外字段不同，不能只靠 `stage_id` 猜。

| mode | 额外输入 | 说明 |
|---|---|---|
| `dry_run_plan` | 无 | 只校验和返回计划，不写 artifact |
| `prepare_goal` | `goal_artifact_dir` 可选 | 默认写 `/tmp/hermes-codex-goals/...` |
| `launch_goal` | `one_line_goal_file` 或完整 `goal_text` | 首选读取 `prepare_goal` 产出的单行文件；启动后 Codex TUI 可能改 repo |
| `monitor_goal` | `session_id` | 首版不要靠 stage 自动猜 process；后续可加 stage→process registry |
| `collect_candidate` | `session_id` 可选 | 有 session 时补 process 状态；无 session 时只收集 git evidence |

`standing_authorization` 只能覆盖本地非破坏性动作，例如：读取状态、写 `/tmp` goal artifact、等待/轮询、收集 evidence、运行已列明的轻量验证。它不能覆盖 push / deploy / restart / secret / real provider / 真实数据 / 真实媒体 / destructive cleanup / scope expansion。

## 6. Output schema 草案

所有模式都返回 JSON-like dict，不返回大段 TUI raw log。

```json
{
  "status": "dry_run_plan|prepared|launched|running|wait_window_expired|goal_achieved|idle_goal_achieved|pasted_content_suspected|no_diff_idle|process_exited_with_diff|process_exited_no_diff|blocked|review_needed|failed|unavailable",
  "mode": "...",
  "workdir": "...",
  "stage_id": "...",
  "driver": "codex_tui_goal",
  "goal_files": {
    "rich_goal_file": "/tmp/...md",
    "one_line_goal_file": "/tmp/...txt"
  },
  "process": {
    "session_id": "...",
    "started": true,
    "still_running": true,
    "exit_code": null
  },
  "preflight": {
    "repo_found": true,
    "workdir_clean": true,
    "codex_bin_found": true,
    "goals_feature": "stable true|unknown|missing",
    "pty_required": true,
    "blockers": []
  },
  "candidate_evidence": {
    "git_status_short": "...",
    "diff_stat": "...",
    "changed_files": [],
    "untracked_files": [],
    "staged_files": []
  },
  "classification": {
    "state_reason": "running|goal_achieved|idle_goal_achieved|pasted_content_suspected|no_diff_idle|process_exited_with_diff|process_exited_no_diff|blocked_by_codex|unknown",
    "goal_achieved_seen": false,
    "pasted_content_suspected": false,
    "wait_timeout_kind": "wait_window_expired|hard_deadline|none",
    "needs_human_decision": false
  },
  "next_action": "inspect_diff|monitor_again|send_raw_enter_or_ask|close_idle_tui|ask_user|run_verification|collect_candidate|failed_or_noop|blocked"
}
```

## 7. Preflight 设计

### 7.1 Repo / workdir

必须检查：

```text
workdir exists
workdir is git repo
git status --short --branch --untracked-files=all
```

默认要求：

```text
dirty_baseline_policy=require-clean
```

如果 worktree dirty：

- dirty 是 cache/generated 且 standing authorization 覆盖：可以建议清理，但首版不自动清理。
- dirty 是未知/用户改动：fail closed。
- 如果 `allow_isolated_worktree=true`：可以返回 “would create isolated worktree” 的计划；首版可只 dry-run，不实际创建。

### 7.2 Codex CLI / Goal feature

只读检查：

```bash
export PATH="$HOME/.local/node-v22.21.1-linux-x64/bin:$HOME/.local/bin:$PATH"
codex-yuna --version
codex-yuna features list
```

要求证据形状：

```text
codex-cli 0.128.0+
goals stable true
```

如果 `goals` 缺失：

- 不自动 `features enable goals`，因为这是用户级 Codex config 改动。
- 返回 blocker：`goals_feature_not_enabled`。
- 给出建议命令，但等待用户授权。

### 7.3 PTY / terminal 能力

官方 `/goal` 必须 interactive TUI：

```text
pty=true
background=true
notify_on_complete=true
```

如果当前 runtime 无法创建 PTY / background process：返回 `tui_runtime_unavailable`。

## 8. Goal artifact 设计

`prepare_goal` 生成两个文件。

### 8.1 Rich goal file

路径建议：

```text
/tmp/hermes-codex-goals/<repo-name>-<stage-id>-goal.md
```

内容：

```text
# Codex Goal Handoff: <stage_id>

Objective
Scope
Allowed files/globs
Docs to read first
Non-goals
Required verification
Stop conditions
Reporting requirements
```

### 8.2 One-line goal file

路径建议：

```text
/tmp/hermes-codex-goals/<repo-name>-<stage-id>-goal-one-line.txt
```

内容必须单行：

```text
/goal Complete <stage_id> only. Read <docs>. Objective: <objective>. Scope: <allowed>. Required tests: <commands>. Must not: <non-goals>. Stop if: <stop conditions>. Done only when: changed files and verification evidence are ready for Hermes review.
```

规则：

- 单行，避免 QQ/WebUI PTY 多行 paste 问题。
- 不能包含 secret。
- 不能包含全量长 diff。
- 太长时压缩为 “Read rich goal file at /tmp/...md”，但 Codex TUI 是否能读该文件取决于 repo/sandbox，因此仍要把关键约束放进单行。

## 9. TUI launch / submit 生命周期

### 9.1 Launch

内部等价行为：

```python
terminal(
  command='export PATH="$HOME/.local/node-v22.21.1-linux-x64/bin:$HOME/.local/bin:$PATH"; codex-yuna --enable goals',
  workdir='<workdir>',
  pty=True,
  background=True,
  notify_on_complete=True,
)
```

### 9.2 Submit

提交顺序：

```text
process.submit(session_id, one_line_goal)
process.write(session_id, "\r")
```

为什么要 `\r`：

```text
QQ/WebUI PTY 下 process.submit 可能只是粘贴文本，不一定真正提交 composer。
```

### 9.3 Paste failure detection

如果满足这些条件，分类为 `pasted_content_suspected`：

```text
TUI log 出现 [Pasted Content]
或 goal text 留在 composer
且 git status/diff 长时间无变化
且 process 仍在运行
```

处理：

1. 再发一次 raw `\r`。
2. 如果仍无变化，返回 `needs_human_decision`。
3. 不自动杀进程，除非已确认 idle 且无 candidate diff。

## 10. Monitor 语义

`process(wait)` timeout 必须解释为：

```text
wait window expired, not task failure
```

每个 wait window 后收集：

```bash
git status --short --branch --untracked-files=all
git diff --stat
git diff --name-only
git diff --cached --stat
git diff --cached --name-only
git ls-files --others --exclude-standard
```

分类：

| 状态 | 条件 | next_action |
|---|---|---|
| `running` | process 仍在跑，可能有或没有 diff | `monitor_again` |
| `goal_achieved` | log 看到 `Goal achieved` | `collect_candidate` |
| `idle_goal_achieved` | `Goal achieved` 后 TUI composer 仍开着 | `close_idle_tui` 后 collect |
| `pasted_content_suspected` | paste 未提交迹象 | `send_raw_enter_or_ask` |
| `no_diff_idle` | 长时间无 diff 且 TUI idle | `ask_user` |
| `process_exited_with_diff` | process 退出且有 diff | `collect_candidate` |
| `process_exited_no_diff` | process 退出且无 diff | `failed_or_noop` |
| `blocked_by_codex` | Codex 明确说缺信息/越界/需要授权 | `ask_user` |

`close_idle_tui` 的顺序必须固定：

```text
1. 先记录 `Goal achieved` evidence 和 bounded log tail metadata；
2. 再收集 git status / diff / staged / untracked evidence；
3. 确认 TUI 处于 idle composer，不是仍在工作；
4. 优先发送 `/quit` + Enter；
5. 如果无法优雅退出，只能在 evidence 已保存后终止 tracked idle process；
6. 不能在 candidate evidence 收集前 kill 仍可能工作的 TUI。
```

## 11. Candidate evidence model

Goal lane 结束后，不能只用 Codex summary。

必须返回：

```text
git status short
diff stat
changed tracked files
staged files
untracked files
raw log bounded tail metadata
Goal achieved seen? yes/no
process exit code / still running
```

重要：

```text
git diff 不显示 untracked，新文件必须额外列出。
```

Slice 7A 已落地的 `collect_candidate` mode：

```text
dirty candidate worktree allowed
Codex goals preflight not run
candidate_evidence.changed_files / staged_files / untracked_files collected via git
diff_stat / staged_diff_stat / status_short bounded by tool output limiter
review_handoff.review_packet carries stage_id/objective/scope/required_verification/candidate_evidence
completion_trusted=false
```

如果发现 unexpected untracked/staged files：

```text
status=review_needed
next_action=inspect_untracked_files
```

## 12. Review / verification 出口

`codex_goal_run` 不直接宣布完成。

它只把 candidate 交给 Hermes 后续流程：

```text
candidate evidence
→ Hermes inspect source/tests/docs
→ run focused verification
→ optional codex_review_packet / codex_review_guard
→ fix blockers or ask user
→ local commit only after explicit authorization / agreed checkpoint policy
```

如果需要 Codex review：

- 先 build bounded packet。
- packet 必须包含 staged / unstaged / untracked。
- 若 review 出现 `aggregated_output_flood` / `review_unusable`，改用更小 packet，不算 pass。

## 13. 安全与授权边界

### 13.1 永远 stop-and-ask

以下情况必须停：

```text
push
deploy
restart
merge/rebase conflict
secret / token / auth file
real provider
real data
real media/model runs
destructive cleanup
scope expansion
修改 allowlist 外文件
```

### 13.2 Goal 不是硬 guard

必须在 user-facing output 里保持这个说法：

```text
Official /goal 只是 TUI 目标机制，不是 allowlist guard。
```

因此：

- 不能把 Goal lane 标记成 `completion_trusted=true`。
- 只能标记成 `candidate_disposition=needs_review`。
- 如果要强 allowlist，需要外部 Hermes evidence 检查和后续 runtime guard，不靠 Codex 自觉。

### 13.3 非 secret 行为配置不要进 `.env`

若后续需要配置：

- credential/key：`.env`。
- 行为开关/timeout/threshold：`config.yaml`。
- 临时 runtime artifact：`/tmp/hermes-codex-goals/...`。

## 14. 错误分类

建议错误 code：

```text
workdir_not_found
git_repo_not_found
workdir_dirty
codex_bin_missing
codex_goals_missing
pty_unavailable
goal_artifact_write_failed
tui_launch_failed
goal_submit_uncertain
wait_window_expired
hard_deadline_exceeded
goal_achieved_but_no_diff
unexpected_untracked_files
out_of_scope_changes
codex_requested_forbidden_action
candidate_needs_review
review_unavailable
```

## 15. 首版实现切片建议

### Slice 1：dry-run / prepare only

文件建议：

```text
tools/codex_goal_run_tool.py
tests/tools/test_codex_goal_run_tool.py
```

功能：

- schema 注册；
- 输入校验；
- repo/git clean preflight；
- Codex binary / goals feature 检查可 mock；
- 生成 rich + one-line goal artifacts 到 `/tmp`；
- 不启动 TUI。

验证：

```bash
python3 -m pytest tests/tools/test_codex_goal_run_tool.py -q -o addopts=''
python3 -m py_compile tools/codex_goal_run_tool.py tests/tools/test_codex_goal_run_tool.py
git diff --check HEAD
```

### Slice 2：launch / submit lifecycle

功能：

- 启动 `codex-yuna --enable goals`；
- `pty=true background=true notify_on_complete=true`；
- submit 单行 `/goal`；
- raw `\r` fallback；
- 返回 `process.session_id`。

测试：

- mock terminal/process handler；
- 断言 pty/background/notify；
- 断言 command 不使用 `codex-yuna exec`；
- 断言 submit 后有 raw `\r`。

### Slice 3：monitor / candidate evidence（当前已实现 mock 状态机，candidate evidence 尚未完整实现）

功能：

- wait-window timeout 分类；（已实现 mock `idle_wait`）
- running output 不误报 idle；（已实现）
- completed / failed / missing session 分类；（已实现）
- dirty candidate worktree 作为 monitor evidence，不阻塞 monitor；（已实现）
- `Goal achieved` idle composer 分类；（待 Slice 4/5 接真实 transcript/log evidence）
- git status/diff/untracked evidence；（待 Slice 4+，当前只暴露 dirty_check evidence）
- no raw log flood。（待 Slice 4 定义 bounded log tail）

测试：

- process running + diff；
- timeout but still running；
- goal achieved + TUI idle；
- process exited with diff；
- untracked files included。

### Slice 4：real adapter contract / replay classifier，不接真实 TUI（4A/4B/4C/4D/4E/4F 已实现）

功能：

- 定义真实 terminal/process adapter 的 snapshot/evidence shape；（已完成 classifier contract）
- 用 replay/mock transcript tests 覆盖 process/log/git evidence → monitor state 映射；（已完成）
- 新增纯函数 classifier，例如 process running/output、idle no diff、process exited with diff、pasted content suspected、process missing；（已完成）
- 新增默认 disabled/replay-only adapter wrappers：`_collect_goal_process_snapshot` / `_collect_goal_git_evidence` / `_compose_goal_snapshot`；（已完成）
- 新增 gated runner interface 和 stop condition：`_run_goal_adapter_once` / `_goal_adapter_stop_condition`；（已完成）
- 新增 `monitor_goal` call-site：默认旧 mock poll，显式 `adapter_enabled=True` 才进入 gated adapter path；（已完成）
- 新增最小真实 TUI smoke runbook：授权门、证据包、stop condition、失败/成功模板；（已完成，未执行）
- 默认仍 disabled/mock-only，不调用真实 terminal/process，不启动 `codex-yuna --enable goals`。

测试：

- running output 不误报 idle；
- idle no diff 返回 inspect/continue recommendation；
- process exited 0 + diff 返回 completed + `completion_trusted=false`；
- process missing 返回 explicit status，不猜；
- `[Pasted Content]` + no diff 返回 needs_attention / raw enter or ask；
- untracked-only evidence 不丢；
- historical paste warning 不覆盖后续 `Goal achieved` + diff；
- nonzero exit 始终 failed，不能被 `Goal achieved` 覆盖；
- default disabled adapters 不读真实 process/git，missing repo 安全；
- replay process/log/git evidence 被规范化并可喂给 classifier；
- default runner disabled 不调用 runner；
- unauthorized runner 不调用 runner；
- authorized path 当前只调用 injected fake runner；
- failed / needs_attention / process_missing stop reason 不被泛化成 blocked；
- schema 暴露 `adapter_enabled` / `allow_real_adapter`；
- `monitor_goal` 默认路径仍走 `_poll_goal_session` mock；
- `monitor_goal` adapter path 不走 `_poll_goal_session`，未授权/无 runner 都 fail-closed；
- runbook 明确没有用户单独授权前不得启动真实 TUI；
- runbook 明确 smoke 成功也只能产生 candidate evidence，`completion_trusted=false`。
- authorized smoke observed `Goal blocked (/goal resume)` with untracked-only candidate; classifier treats that as `completed` + `collect_candidate_for_hermes_review`, still untrusted.
- tests use a monkeypatched fake `_TMP_ROOT` for artifact rejection so `/tmp` smoke worktrees do not invalidate the suite and no fixed system path is touched.

### Slice 7A：collect_candidate review handoff（已实现）

功能：

- 新增 `collect_candidate` mode；
- dirty candidate worktree 不走 `dirty_worktree` blocker，而是作为 candidate evidence；
- 收集 unstaged tracked、staged、untracked、diff_stat、staged_diff_stat、status_short；
- 生成 bounded `review_handoff.review_packet`，供 Hermes 后续 review/verification 使用；
- clean repo 返回 `no_candidate_changes`，不假装成功。

测试：

- schema enum 暴露 `collect_candidate`；
- dirty repo 同时包含 tracked/staged/untracked 时返回 `candidate_ready_for_review`；
- clean repo 返回 `no_candidate_changes`；
- `collect_candidate` 不触发 Codex preflight、TUI launch、TUI poll hooks；
- `completion_trusted=false`。

### Slice 7B：review_candidate replay review lane（已实现）

功能：

- 新增 `review_candidate` mode；
- 复用 Slice 7A 的 candidate evidence 与 `review_handoff.review_packet`；
- 默认 `review_runner_disabled`，不执行真实 review guard / review packet runner；
- `review_replay.status=passed` 且无 `must_fix`、无 `blockers` 时返回 `review_passed`，但仍需要 verification，`completion_trusted=false`；
- `review_replay.reason=aggregated_output_flood` / `review_unusable` / `packet_truncated` 时返回 `review_unavailable`，不算 pass；
- review blocked 时返回 `review_blocked` / `fix_review_blockers`。

测试：

- replay passed 不 trusted，下一步仍要求 verification；
- `aggregated_output_flood` / `review_unusable` / `packet_truncated` 显示 `review_unavailable`，不算 pass；
- `status=passed` 但含普通 blockers / `must_fix` 时仍返回 `review_blocked`；
- 默认 disabled 与 replay path 都不触发 Codex preflight / TUI launch / TUI poll hooks。

### Slice 7C（后续）：real review runner adapter call-site

功能：

- 将 `review_candidate` 的 replay/fake contract 接到真实 review runner adapter 前的 fail-closed call-site；
- 真实 runner 默认 disabled；
- 授权前只返回 `real_review_not_authorized` / `review_runner_missing`，不执行 Codex。

测试：

- unauthorized path 不调用 runner；
- `allow_real_review=True` 但缺 runner 返回 missing；
- fake injected runner 只接收 bounded packet，不接收 raw TUI log。

## 16. 不建议首版做的事

```text
不自动创建 isolated worktree。
不自动 commit。
不自动 push/deploy/restart。
不自动 enable Codex goals feature。
不把 raw TUI log 全量持久塞入 session。
不和 codex_workflow_run 合并成一个大 tool。
```

这些可以作为后续版本。

## 17. 最小验收标准

首版 `codex_goal_run` 可认为设计达标，当它能做到：

1. dry-run 明确告诉用户将启动 official TUI `/goal`，不是 `codex exec`。
2. 能生成可读 rich goal 和可靠 one-line goal。
3. 能 fail-closed 于 dirty worktree / missing goal feature / PTY unavailable。
4. 启动时强制 PTY + background + notify。
5. 提交时使用 one-line `/goal` + raw `\r` fallback。
6. wait timeout 不被误报成失败。
7. `Goal achieved` 只产生 candidate evidence，不算 final success。
8. 收集 staged / unstaged / untracked 文件证据。
9. push/deploy/restart/secret/real provider 全部 stop-and-ask。
10. 有 focused tests 覆盖上述行为。

## 18. 开放问题

1. `codex_goal_run` 应该是独立 tool，还是作为 `codex_workflow_run` 的 `driver="goal"` 子模式？
   - 当前建议：先独立 tool，避免污染已有 guarded lane。
2. Goal artifacts 放 `/tmp` 还是 repo-local `.local/`？
   - 当前建议：默认 `/tmp`，避免 repo dirty；需要留档时再写 docs。
3. 是否允许自动创建 isolated worktree？
   - 当前建议：首版只 dry-run 说明，后续再加。
4. 是否允许自动关闭 idle TUI？
   - 当前建议：只在 `Goal achieved` 已记录且 candidate evidence 已收集后关闭。
5. 是否需要 gateway/QQ 专门状态通知？
   - 当前建议：后续再设计，首版返回 structured status 即可。

## 19. 下一步建议

若继续进入实现，下一步建议是 **Slice 7C：real review runner adapter call-site**，默认不再跑真实 TUI。

理由：

```text
Slice 1-7B 已完成 mock/replay/disabled-wrapper/gated-runner/call-site skeleton、smoke runbook、一次授权真实 smoke、smoke hardening、collect_candidate review handoff 和 review_candidate replay lane。
下一步才考虑把 review_candidate 的 fake/replay contract 接到真实 review runner adapter call-site。
默认不再启动真实 TUI；只有用户重新明确授权时才重跑 smoke。
```

下一阶段应停止在：

```text
real review runner adapter call-site
default disabled/fail-closed
do not repeat real TUI smoke
```

不要直接做真实 `launch_goal` / `codex-yuna --enable goals`。
