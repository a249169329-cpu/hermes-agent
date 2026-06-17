# Hermes Codex Orchestrator Phase 1 Decision Record

> 状态：Phase 1 docs-only decision record；不是实现计划，不是 runtime 已实现能力。
> 日期：2026-06-17
> 原文件名保留为 `hermes-codex-orchestrator-decision-draft.md`，但本文内容已从草案收口为 Phase 1 决策记录。
> 上游依据：
> - `docs/working-notes/hermes-codex-division-of-labor.md`
> - `docs/working-notes/hermes-codex-driver-selection-guarded-vs-goal.md`
> - `docs/working-notes/hermes-codex-goal-run-design.md`
> - `docs/working-notes/hermes-codex-goal-run-slice-handoff.md`

## 0. 本文结论

Phase 1 先确认方向，不进入 runtime 实现。

```text
orchestrator = Hermes 的交通规则和调度台；
Codex = 候选产物生产者；
Hermes = 需求、边界、授权、验收、最终结论负责人。
```

本阶段要固定四件事：

1. driver 怎么选；
2. 什么时候必须停下问人；
3. 两条 Codex lane 产物如何统一验收；
4. QQ / WebUI 怎么短句汇报，避免把 candidate 说成完成。

## 1. 命名决策

本阶段建议命名为：

```text
Orchestrator Phase 1
```

不要默认叫 `Slice 8A`。

原因：`Slice 1-7G` 已经完成的是 `codex_goal_run` 单工具底座；本文讨论的是更高一层的调度决策，属于新阶段。后续如果再拆实现 slice，可以在 Orchestrator Phase 1 下面另起 `1A / 1B / 1C`，而不是把它直接接到 `codex_goal_run` 的 Slice 编号后面。

## 2. 大白话目标

现在已有两条 Codex 施工路线：

```text
1. ordinary guarded lane
   小而窄，像“安全壳里的打工人”。

2. official TUI /goal lane
   大而长，像“阶段型自主工人”。
```

orchestrator 不再发明第三条 Codex 路线。它只负责在任务开始前判断：

```text
这次要不要用 Codex？
如果用，是小安全壳，还是官方 /goal？
如果不用，是 Hermes 直接做，还是必须停下问用户？
Codex 产物回来后，Hermes 怎么验收？
下一步是不是涉及 push / deploy / restart / real provider / secret / real data？
```

## 3. 当前已确认边界

- Hermes 负责需求、阶段、边界、风险、授权、最终验收。
- Codex 输出永远只是 candidate，不拥有最终完成权。
- `codex_goal_run` Slice 1-7G 已收口：默认 mock / replay / disabled-first。
- `adapter_enabled` / `allow_real_adapter` 等真实路径仍是 disabled-first。
- 选择 official TUI lane 只代表候选路线，不等于自动启动真实 TUI。
- 真实 TUI 需要新授权。
- 真实 review subprocess 需要新授权，且仍在四重 gate 后：
  - `review_runner_enabled=True`
  - `allow_real_review=True`
  - `review_guard_enabled=True`
  - `review_guard_subprocess_enabled=True`
- push / PR / deploy / restart / real provider / secret / real data 都是独立授权门。
- dirty worktree 不是“小问题”；它会影响 driver 选择，默认先归因或隔离。

## 4. 非目标

Phase 1 不做这些：

- 不改 runtime code。
- 不启动真实 Codex TUI。
- 不启动真实 review subprocess。
- 不把 ordinary guarded lane 和 official `/goal` 混成一个黑箱入口。
- 不让 Codex 自己决定下一阶段。
- 不把 `Goal achieved` 当成完成。
- 不把 review unavailable 说成 review passed。
- 不 push / PR / deploy / restart。
- 不读 secret，不跑真实 provider，不碰真实数据。
- 不把完整 Hermes skills / memory / runtime ops 规则整包塞给 Codex。

## 5. Driver 选择总表

| 场景 | 推荐 driver | 为什么 | 必须停下的情况 |
|---|---|---|---|
| 极小文档/单点修正 | Hermes direct edit | Codex 开销大，风险不值 | 影响范围不确定、触碰 runtime/code path |
| 明确文件范围的小实现 | ordinary guarded lane | allowlist 强、diff 小、易验收 | 需要越过 allowlist、dirty baseline 不明、测试无法解释 |
| review blocker 修复 | ordinary guarded lane 或 Hermes direct | blocker 通常窄且可验证 | blocker 牵出新需求或跨模块设计 |
| 只读 review | Hermes manual review / bounded Codex review packet | 只看 diff/packet，不写文件 | review flood / unavailable / packet 不完整 |
| stage 级长任务 | official TUI `/goal` lane | 需要 Codex 在 bounded stage 内多轮计划/执行/测试/修正 | 未授权真实 TUI、无法隔离 worktree、目标不够 bounded |
| 验证 Goal 本身行为 | official TUI `/goal` lane | 只有官方 TUI 才是真 Goal | 没有明确 smoke 目标或 stop condition |
| 高风险真实操作 | Human/manual authorization gate | 真实副作用不能交给 Codex 默认处理 | push / PR / deploy / restart / secret / real data / real provider |

## 6. 决策流程

```text
User task
  ↓
Hermes classify:
  - tiny docs/copy?
  - bounded implementation?
  - stage-level goal?
  - review-only?
  - real side effect?
  - dirty baseline?
  - tool/runtime schema stale?
  - context/memory pressure?
  ↓
Select driver:
  - Hermes direct
  - ordinary guarded lane
  - official TUI /goal lane
  - human/manual gate
  ↓
Run only inside selected boundary
  ↓
Collect candidate evidence
  ↓
Review gate
  ↓
Verification gate
  ↓
Local checkpoint only if authorized and verified
  ↓
Stop before push/PR/deploy/restart/real provider/secret/real data unless separately authorized
```

## 7. Driver 选择规则

### 7.1 Hermes direct

用在：

- 明确低风险文档改动；
- 单点 typo / copy / docs-only 决策记录；
- 不需要 Codex 自主搜索或多文件实现；
- 用户要求只读审查或轻量说明。

仍然要做：

- git status 前后检查；
- diff review；
- docs lint / grep assertions / `git diff --check` 级别验证；
- 明确未 push / 未部署 / 未重启。

### 7.2 ordinary guarded lane

用在：

- 文件范围明确；
- 任务应该一次退出；
- 小 bug、小测试、小实现、review blocker；
- 需要强 allowlist / dirty baseline / fail-closed。

必须有：

- explicit `allowed_files` / `allowed_globs`；
- clean 或可解释 baseline；
- Codex 输出作为 candidate；
- Hermes 读 diff + 跑 focused tests；
- 不允许 raw `codex-yuna exec` 做实现。

### 7.3 official TUI `/goal` lane

用在：

- 用户明确授权 Codex Goal / official `/goal`；
- stage 级长目标；
- 需要 Codex 在 bounded stage 内多轮自我推进；
- 需要验证 Goal 模式自身行为。

必须有：

- isolated clean worktree；
- one-line `/goal` objective；
- docs/files to read；
- scope / non-goals / required tests / stop conditions；
- monitor window；
- Goal 结束后进入同一个 Hermes 验收出口。

注意：Goal lane 不是 fail-closed guard。`/goal` prompt 不能替代 allowlist，也不能替代 Hermes review。

### 7.4 human/manual authorization gate

用在：

- push / PR；
- deploy / restart；
- secret / real data；
- real provider / costly model/media run；
- conflict / reset / revert / delete unknown dirty；
- unclear ownership or unclear failure；
- runtime schema stale 需要重启/刷新才能生效。

这些不因“前面实现授权”自动放行。

## 8. 统一出口：两条 Codex lane 都必须走同一验收门

| 统一出口项 | 要求 |
|---|---|
| candidate evidence | changed files、staged/unstaged/untracked、diff stat、关键日志摘要 |
| baseline evidence | branch、HEAD、upstream、ahead/behind、dirty status、worktree path |
| scope check | 是否只改允许范围，是否偷跑下一阶段 |
| review | Hermes manual review 或 bounded Codex review packet；真实 subprocess review 仍需显式四重 gate |
| verification | focused tests、compile/check、doc assertions、diff check、缓存残留检查 |
| completion wording | 只能说“candidate verified by Hermes”，不能说“Codex 自己证明完成” |
| next action | commit / push / PR / deploy / restart 全部单独授权 |

统一出口的核心原则：

```text
Codex 说完成 ≠ 完成。
Hermes review + verification 支撑后，才能说本地 candidate 可接受。
真实副作用仍另问。
```

## 9. Evidence schema 首版草案

后续实现 orchestrator 时，每个阶段应至少记录这些字段。

```text
orchestrator_phase:
  name: Orchestrator Phase 1 / later slice id
  driver: hermes_direct | guarded_lane | official_goal_lane | human_gate
  reason: why this driver
  worktree:
    path:
    branch:
    head:
    upstream:
    dirty_state:
    dirty_owner:
  authorization:
    user_authorized:
    scope:
    expires_when:
    side_effects_allowed:
  candidate:
    changed_files:
    diff_stat:
    staged:
    unstaged:
    untracked:
    logs_summary:
  review:
    method:
    status:
    blockers:
    unavailable_reason:
  verification:
    commands:
    exit_codes:
    artifacts_checked:
    residue_cleanup:
  final_disposition:
    local_candidate_accepted:
    completion_trusted:
    next_action_requires_authorization:
```

首版不要求立刻落 runtime schema；这里只固定后续实现时不能缺的证据形状。

## 10. 状态机首版草案

```text
planned
  ↓
preflight
  ↓
blocked | driver_selected
  ↓
running
  ↓
candidate_ready | no_candidate_diff | failed | needs_attention
  ↓
reviewing
  ↓
review_passed | review_blocked | review_unavailable
  ↓
verifying
  ↓
verified_local | verification_failed
  ↓
awaiting_authorization | stopped
```

重点：

- `candidate_ready` 不是完成。
- `review_unavailable` 不是通过。
- `verified_local` 不是 push / deploy / restart。
- `awaiting_authorization` 只说明下一步需要用户授权，不代表已执行。

## 11. 失败分类表

| 失败/停下状态 | 大白话 | 下一步 |
|---|---|---|
| `preflight_blocked` | 起跑条件不满足 | 补条件或换 driver |
| `dirty_baseline_unknown` | 工作区脏且归属不明 | 分类、隔离 worktree、或问用户 |
| `driver_unavailable` | 目标 driver 当前不能用 | 降级到安全路径，不裸跑 Codex |
| `context_or_memory_pressure` | 上下文/压缩/记忆压力会污染判断 | 停下做状态核对，必要时拆阶段 |
| `tool_schema_stale` | 源码已变但当前运行态工具 schema 未刷新 | 不宣称运行态已生效；需要单独重启/刷新授权 |
| `wait_window_expired` | 等待窗口到了，不等于失败 | 查 process/log/git evidence |
| `tui_submit_unclear` | `/goal` 可能没真正提交 | 查 TUI/log/diff，必要时 raw `\r` 或停下 |
| `no_candidate_diff` | Codex 说完成但没产物 | 不算完成，回到人工判断 |
| `candidate_out_of_scope` | 改了不该改的东西 | 停止，review 后决定修/弃/问用户 |
| `review_unavailable` | review 没跑成或不可信 | Hermes manual review + 记录缺口 |
| `verification_failed` | 测试/检查没过 | 修复或回滚，不说完成 |
| `side_effect_requested` | 需要 push/PR/deploy/restart/真实服务 | 单独问用户授权 |

## 12. 授权矩阵

| 操作 | 默认 | 需要什么 |
|---|---|---|
| Hermes direct docs edit | 可在明确 docs-only 阶段使用 | scope 明确 + diff/status 验证 |
| ordinary guarded implementation | 可在明确实现阶段使用 | clean/可控 worktree + allowlist + Hermes 验证 |
| official TUI `/goal` | 默认不跑 | 用户明确授权 + isolated/clean worktree + bounded goal + stop condition |
| real review subprocess | 默认不跑 | 用户明确授权 + 四重 gate + packet-only review |
| local commit | 不默认等同于实现授权 | 已验证 + 本阶段允许本地 checkpoint |
| push / PR | 默认不做 | 用户明确 push/PR 授权 + 远端 SHA 验证 |
| deploy / restart | 默认不做 | 用户明确部署/重启授权 + runtime 验证计划 |
| secret / real data / real provider | 默认不碰 | 用户明确授权 + 最小暴露 + 不打印 secret |
| reset / revert / delete unknown dirty | 默认不做 | 用户明确授权 + 先说明影响 |

## 13. QQ 状态汇报模板

| 状态 | QQ 短句 |
|---|---|
| 准备阶段 | 准备执行：选择 driver 和边界；不跑真实副作用。 |
| dirty baseline | 当前 worktree 不干净，先归因/隔离；不让 Codex 直接写。 |
| ordinary lane 运行中 | 运行 guarded lane：只允许指定文件，Codex 产物只是 candidate。 |
| Goal lane 运行中 | 运行 official `/goal`：这是授权 TUI 目标，等待窗口不等于失败。 |
| candidate ready | candidate 已产出，进入 Hermes review/验证，不等于完成。 |
| review unavailable | review 没有可靠完成，改由 Hermes manual review；不冒充通过。 |
| verification failed | 验证失败，停止；先修或回滚，不继续下一阶段。 |
| verified local | 本地验证通过；未 push、未部署、未重启。 |
| schema stale | 本地源码有变化，但当前运行态工具可能没刷新；不宣称已上线。 |
| authorization needed | 这一步有真实副作用，需要你单独授权。 |

## 14. Phase 1A 可落地内容

如果用户继续推进，建议 Phase 1A 只做 docs-only 收口：

1. 保留本文为 orchestrator decision record；
2. 不改 runtime；
3. 不启动 Codex；
4. 不 push / deploy / restart；
5. 下一轮再决定是否进入实现前设计：state machine / evidence schema / authorization matrix 的 runtime mapping。

## 15. Phase 1B runtime mapping（只读补充）

> 状态：Phase 1B 只读 mapping；本节不是 runtime 实现，不代表工具已经统一编排。
> 本节只把 Phase 1A 的设计问题映射到现有 runtime surface，方便后续实现前拆 slice。

### 15.1 已观察到的 runtime surface

| surface | 现有职责 | 对 orchestrator 的含义 |
|---|---|---|
| `tools/codex_workflow_run_tool.py` | 高层 dirty recovery + guarded lane 调度；可在授权下清 cache-only residue 或创建 isolated worktree；再委派 `codex_staged_implement` | 最接近 ordinary guarded lane 的 workflow orchestrator；适合作为后续 driver-selection 的上层入口之一 |
| `tools/codex_staged_implement_tool.py` | 窄范围候选实现；要求显式 `allowed_files` / `allowed_globs`；`dirty_baseline_policy=require-clean`；`completion_trusted` 只说明 runner 没触发已知异常 | 适合小 slice / review blocker；不拥有最终完成权；必须进入 Hermes diff review + verification |
| `tools/codex_goal_run_tool.py` | official `/goal` 的 prepare/launch/monitor/collect/review skeleton；默认 mock/disabled；`collect_candidate` / `review_candidate` 生成 candidate evidence 和 review handoff | 适合 official TUI `/goal` lane；Goal 输出仍只是 candidate；review subprocess 仍默认关闭 |
| `scripts/runtime/codex_impl_guard.py` | implementation guard；dirty baseline、allowlist、candidate path、输出限制等底层保护 | 这是底层 fail-closed guard，不应承担高层 orchestration/授权生命周期 |
| `scripts/runtime/codex_review_guard.py` + `codex_review_packet.py` | bounded packet-only review；避免全量日志/源码 flood；原始 runner 可返回 passed/failed/unusable，经 adapter 映射为 passed/blocked/unavailable 语义 | 适合统一 review packet 形状；`review_unavailable` 不能算 pass |
| `session_search` current-scope/current-mode 方向 | 用于“本会话/这个会话开头”类恢复，避免 broad FTS 串旧会话 | 属于 context recovery 支撑层；orchestrator ledger 不能只靠 FTS 召回 |

### 15.2 六个实现前问题的当前答案

1. **dirty worktree gate 放哪层？**

   答案：两边都有，但职责不同。

   - 底层 guard：继续 fail-closed，例如 `codex_staged_implement` / `codex_impl_guard.py` 的 `require-clean` 和 allowlist 检查。
   - 高层 workflow：由 `codex_workflow_run` / 未来 orchestrator 先归因、清理 safe cache、或创建 isolated worktree。
   - official `/goal`：启动前仍偏向 isolated clean worktree；`collect_candidate` / `review_candidate` 阶段可以读取 dirty candidate evidence，但不能把 dirty 本身当成功。

   结论：dirty recovery 不应塞进 `codex_goal_run` 底层；应由上层 orchestrator 先处理 driver 选择和 worktree 策略。

2. **authorization record 生命周期怎么定义？**

   建议首版只支持三档：

   ```text
   one_turn: 只对当前一次工具/阶段动作有效
   phase: 只对当前 stage_id / phase 有效
   session: 只在当前会话上下文可信时有效
   ```

   遇到这些情况应自动失效或降级为重新确认：

   - context compaction 后 evidence 不完整；
   - worktree dirty ownership 不明；
   - `tool_schema_stale`；
   - scope 扩大；
   - review/verification 失败；
   - push / PR / deploy / restart / secret / real data / real provider / destructive cleanup。

   `standing_authorization` 只能覆盖本地、非破坏性、已列明的动作；不能覆盖真实副作用。

3. **`tool_schema_stale` 怎么检测和汇报？**

   需要一个 preflight probe：

   ```text
   expected runtime source/schema fields
   ↔ active tool schema visible to current session
   ```

   如果源码已经有某字段，但当前会话 tool schema 没暴露，应返回：

   ```text
   status: preflight_blocked
   reason: tool_schema_stale
   next_action: refresh/restart/new-session authorization
   ```

   QQ 汇报口径：

   ```text
   本地源码有这个字段，但当前会话工具 schema 可能还没刷新；不宣称已上线。
   ```

4. **context compaction 后如何恢复当前 phase？**

   不能靠 broad keyword search 自动猜。

   最小恢复顺序：

   ```text
   preserved todo / current phase marker
   → git status + touched files
   → orchestrator ledger last state
   → session_search(mode="current") 或等价 current-scope recall
   → 仍不确定则停下问用户
   ```

   ledger 必须记录：当前 phase、driver、worktree、dirty state、last verified evidence、authorization mode、next action、明确 out-of-scope。

5. **official `/goal` lane 与 ordinary guarded lane 的 evidence 如何统一？**

   不要求底层工具输出完全一样；先用 adapter mapping 统一到最小 envelope：

   ```text
   driver:
   reason:
   worktree:
   authorization:
   candidate:
   review:
   verification:
   final_disposition:
   ```

   guarded lane 的 `completion_trusted` 只能映射成“runner 没触发已知异常”；Goal lane 的 `Goal achieved` 只能映射成“candidate_ready”。两者都不能直接映射成 done。

6. **review subprocess 是否保持四重 gate？**

   答案：是。

   真实 review subprocess 仍必须同时满足：

   ```text
   review_runner_enabled=True
   allow_real_review=True
   review_guard_enabled=True
   review_guard_subprocess_enabled=True
   ```

   并且只允许 packet-only review。`review_unavailable` / `aggregated_output_flood` / `packet_truncated` / non-json 都必须保留为 blocked/unavailable，不得冒充通过。

### 15.3 Phase 1C 建议切分

如果继续推进，下一步仍建议 docs-first，而不是直接 runtime 实现：

1. 写 `orchestrator recovery ledger` 最小 schema；
2. 写 driver-selection preflight pseudo-code；
3. 明确 `tool_schema_stale` probe 的输入/输出；
4. 再决定是否进入 runtime slice。

Phase 1C 仍不应做：真实 TUI、真实 review subprocess、push / deploy / restart、secret / real data / real provider。

## 16. Phase 1C recovery ledger 最小 schema（docs-only）

> 状态：Phase 1C docs-only recovery ledger 草案；不是 runtime 实现，也不是当前运行态已经记录这些字段。
> 目的：让 context compaction、session resume、QQ “继续/按你建议来”之后，Hermes 能先恢复当前阶段和证据边界，而不是复活旧任务或误把摘要当成事实。

### 16.1 大白话目标

`orchestrator recovery ledger` 是一张“交接卡”。

它不替代 git、测试、review、工具输出；它只告诉下一轮 Hermes：

```text
现在做的是哪一阶段；
上一次真正验证到哪里；
哪些只是摘要线索；
哪些动作没授权；
下一步只能做什么；
哪些事明确不能顺手做。
```

核心原则：

```text
ledger helps recovery, but fresh evidence still wins.
```

### 16.2 最小 schema

```yaml
orchestrator_recovery_ledger:
  schema_version: orchestrator_recovery_ledger.v1
  phase:
    name: Orchestrator Phase 1C
    stage_id: phase-1c-recovery-ledger
    status: planned | in_progress | verified_local | awaiting_authorization | stopped | blocked
    source_of_truth_doc: docs/working-notes/hermes-codex-orchestrator-decision-draft.md
  current_user_intent:
    latest_user_message:
    interpreted_action:
    confidence: high | medium | low
  driver:
    selected: hermes_direct | guarded_lane | official_goal_lane | human_gate | none
    reason:
    not_selected:
      guarded_lane:
      official_goal_lane:
      human_gate:
  worktree:
    path:
    branch:
    head:
    upstream:
    ahead_behind:
    dirty_state: clean | expected_dirty | unknown_dirty | not_checked
    expected_dirty_paths:
    dirty_owner: current_phase | previous_phase | other_session | unknown | none
  authorization:
    mode: none | one_turn | phase | session
    scope:
    side_effects_allowed:
    expires_when:
    must_reconfirm_before:
  evidence_boundary:
    current_turn_verified:
    same_session_verified:
    subagent_claims_unverified:
    context_summary_hints:
    unknown_or_not_proven:
  checks:
    commands_run:
    files_read:
    files_changed:
    review_status: not_run | passed | blocked | unavailable
    verification_status: not_run | passed | failed | partial
    residue_status:
  next_action:
    recommended:
    allowed_without_new_auth:
    requires_user_auth:
    stop_conditions:
  explicit_out_of_scope:
    - real TUI
    - real review subprocess
    - push / PR
    - deploy / restart
    - secret / real data / real provider
    - memory / skill cleanup
    - CodeGraph repair
    - browser repair
    - memory / Swap operations
  recovery_notes:
    compaction_happened:
    tool_schema_stale:
    codegraph_available:
    session_search_mode_current_available:
```

### 16.3 证据分层规则

恢复时必须把证据分层，不允许混说：

| 层级 | 能不能直接信 | 用法 |
|---|---:|---|
| fresh tool output | 高 | 当前轮刚跑的 `git status` / diff / test / remote SHA 等，可以作为报告证据 |
| same-session verified evidence | 中高 | 同一会话刚验证过，但关键结论最好用轻量 fresh check 补强 |
| subagent review | 中 | 可作为 reviewer input；主代理必须复核关键 git/status/diff 后才能说通过 |
| context summary | 中低 | 只作恢复线索，不可单独证明已完成、已 push、已部署、已重启 |
| memory/profile | 低到中 | 只提供长期偏好/环境事实，不证明当前状态 |
| old search result / broad FTS | 低 | 可能串旧会话；当前阶段恢复应优先 `mode="current"` 或明确 doc/git evidence |

### 16.4 恢复流程

在 context compaction、API 中断、或用户说“继续/按你建议来”之后，先走这个顺序：

```text
1. 读取 latest user message。
2. 读取 active todo / preserved task list。
3. 读取 ledger 的 phase/status/next_action。
4. 跑轻量 fresh check：git status、HEAD、upstream、expected dirty paths。
5. 如果用户问“前面说的/本会话开头”，用 current-scope/current-mode recall；不要 broad FTS。
6. 若 ledger、git、用户最新消息冲突，以用户最新消息 + fresh evidence 为准。
7. 若仍不确定，停下问用户；不要自动切到内存/CodeGraph/browser/cleanup 等邻近任务。
```

### 16.5 QQ 汇报模板

| 状态 | QQ 短句 |
|---|---|
| 恢复中 | 我先恢复阶段边界：只查 ledger + git 状态，不写文件。 |
| 证据不足 | 当前只有摘要线索，不足以证明完成；我先做 fresh status check。 |
| 串旧会话风险 | 这个问题容易被 broad search 串旧会话；我用当前会话范围查。 |
| 可继续 | 阶段、worktree、next action 对上了；继续当前小阶段。 |
| 需确认 | ledger 和当前状态冲突；停下等你确认，不自动扩范围。 |

### 16.6 Phase 1C 验收标准

Phase 1C docs-only 完成标准：

- ledger schema 覆盖 phase、driver、worktree、authorization、evidence boundary、checks、next action、out-of-scope；
- 明确 fresh evidence 优先于 summary/memory；
- 明确 subagent 结论必须主代理复核；
- 明确 compaction 后不得复活旧任务；
- 明确 `session_search(mode="current")` / current-scope recall 用途；
- 明确不做真实 TUI、真实 review subprocess、push / deploy / restart、secret / real data / real provider、CodeGraph/browser/memory/Swap 修复；
- `git diff --check` 通过；
- worktree 状态只显示预期 docs 改动。

## 17. 本文验收标准

本文作为 Phase 1 docs-only decision record，完成标准是：

- 只改本文件或最多同一 working-note 范围；
- 明确“设计记录，不是 runtime 已实现”；
- 明确 Hermes / Codex 职责；
- 明确四类 driver；
- 明确统一出口；
- 明确授权矩阵；
- 明确 state machine / evidence schema 首版；
- 明确非目标：不真实 TUI、不真实 review subprocess、不 push/deploy/restart；
- `git diff --check` 通过；
- worktree 状态只显示预期 docs 改动。
