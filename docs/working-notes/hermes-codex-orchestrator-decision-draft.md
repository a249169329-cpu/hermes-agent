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

## 15. Phase 1B 进入实现前必须补齐

实现前需要先有明确答案：

- dirty worktree gate 放在哪一层：tool guard、workflow orchestrator，还是两边都有？
- authorization record 的生命周期：一次性、阶段性、会话性，何时失效？
- `tool_schema_stale` 怎么检测和汇报？
- context compaction 后如何恢复当前 phase，而不是复活旧任务？
- official `/goal` lane 的 evidence schema 与 ordinary guarded lane 如何最小统一？
- review subprocess 真实路径是否仍保持单独四重 gate？默认答案：是。

## 16. 本文验收标准

本文作为 docs-only Phase 1A，完成标准是：

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
