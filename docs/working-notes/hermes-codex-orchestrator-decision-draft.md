# Hermes Codex Orchestrator Decision Draft

> 状态：新阶段草案 / working note；不是实现计划，不是 runtime 已实现能力。
> 日期：2026-06-17
> 上游依据：
> - `docs/working-notes/hermes-codex-division-of-labor.md`
> - `docs/working-notes/hermes-codex-driver-selection-guarded-vs-goal.md`
> - `docs/working-notes/hermes-codex-goal-run-design.md`
> - `docs/working-notes/hermes-codex-goal-run-slice-handoff.md`

## 0. 命名说明

本文先叫 **Orchestrator Decision Draft**。

不要默认叫 `Slice 8A`。

原因：`Slice 1-7G` 已经完成的是 `codex_goal_run` 单工具底座；本文讨论的是更高一层的调度决策，属于新阶段。后续是否命名为 `Slice 8A`、`Orchestrator Phase 1` 或别的名字，需要用户确认。

## 1. 大白话目标

现在已有两条 Codex 施工路线：

```text
1. ordinary guarded lane：小而窄，像“安全壳里的打工人”。
2. official TUI /goal lane：大而长，像“阶段型自主工人”。
```

下一层 orchestrator 要做的不是再发明一条路，而是回答：

```text
这次任务该走哪条路？
什么时候必须停下问人？
Codex 产出的东西怎么统一验收？
QQ 上该怎么短句汇报状态？
```

一句话：

```text
orchestrator = Hermes 的交通规则和调度台；Codex 仍然只是候选产物生产者。
```

## 2. 当前已确认

- Hermes 负责需求、阶段、边界、风险、授权、最终验收。
- Codex 输出永远只是 candidate，不拥有最终完成权。
- `codex_goal_run` Slice 1-7G 已收口：默认 mock/replay/disabled-first。
- `adapter_enabled` / `allow_real_adapter` 等真实路径仍是 disabled-first；选择 official TUI lane 只代表候选路线，不等于自动启动。
- 真实 TUI 需要新授权。
- 真实 review subprocess 需要新授权，且仍在四重 gate 后：
  - `review_runner_enabled=True`
  - `allow_real_review=True`
  - `review_guard_enabled=True`
  - `review_guard_subprocess_enabled=True`
- push / deploy / restart / real provider / secret / real data 都是独立授权门。

## 3. Driver 选择总表

| 场景 | 推荐 driver / 候选 driver | 为什么 | 必须停下的情况 |
|---|---|---|---|
| 极小文档/单点修正 | Hermes direct edit | Codex 开销大，风险不值 | 不确定影响范围、触碰 runtime/code path |
| 明确文件范围的小实现 | ordinary guarded lane | allowlist 强、diff 小、易验收 | 需要越过 allowlist、dirty baseline 不明、测试无法解释 |
| review blocker 修复 | ordinary guarded lane 或 Hermes direct | blocker 通常窄且可验证 | blocker 牵出新需求或跨模块设计 |
| 只读 review | Hermes manual review / bounded Codex review packet；真实 subprocess review 仅在四重 gate + 用户授权后可用 | 只看 diff/packet，不写文件 | review flood / unavailable / packet 不完整 |
| stage 级长任务 | official TUI `/goal` lane | 需要 Codex 自己计划/执行/自测多轮推进 | 未授权真实 TUI、无法隔离 worktree、目标不够 bounded |
| 验证 Goal 本身行为 | official TUI `/goal` lane | 只有官方 TUI 才是真 Goal | 没有明确 smoke 目标或 stop condition |
| 高风险真实操作 | Human/manual authorization gate | 真实副作用不能交给 Codex 默认处理 | push / deploy / restart / secret / real data / real provider |

## 4. 推荐决策流程

```text
User task
  ↓
Hermes classify:
  - tiny?
  - bounded implementation?
  - stage-level goal?
  - real side effect?
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
Stop before push/deploy/restart unless separately authorized
```

## 5. 两条 Codex lane 的统一出口

两条 lane 虽然启动方式不同，但结束后必须进入同一个 Hermes 出口。

| 统一出口项 | 要求 |
|---|---|
| candidate evidence | changed files、staged/unstaged/untracked、diff stat、关键日志摘要 |
| scope check | 是否只改允许范围，是否偷跑下一阶段 |
| review | Hermes manual review 或 bounded Codex review packet |
| verification | focused tests、compile/check、doc assertions、diff check |
| completion wording | 只能说“candidate verified by Hermes”，不能说“Codex 自己证明完成” |
| next action | commit / push / deploy / restart 全部单独授权 |

## 6. 失败分类表

| 失败/停下状态 | 大白话 | 下一步 |
|---|---|---|
| `preflight_blocked` | 起跑条件不满足 | 补条件或换 driver |
| `dirty_baseline_unknown` | 工作区脏且归属不明 | 分类、隔离 worktree、或问用户 |
| `driver_unavailable` | 目标 driver 当前不能用 | 降级到安全路径，不裸跑 Codex |
| `wait_window_expired` | 等待窗口到了，不等于失败 | 查 process/log/git evidence |
| `tui_submit_unclear` | `/goal` 可能没真正提交 | 查 TUI/log/diff，必要时 raw `\r` 或停下 |
| `no_candidate_diff` | Codex 说完成但没产物 | 不算完成，回到人工判断 |
| `candidate_out_of_scope` | 改了不该改的东西 | 停止，review 后决定修/弃/问用户 |
| `review_unavailable` | review 没跑成或不可信 | Hermes manual review + 记录缺口 |
| `verification_failed` | 测试/检查没过 | 修复或回滚，不说完成 |
| `side_effect_requested` | 需要 push/deploy/restart/真实服务 | 单独问用户授权 |

## 7. 授权门

| 操作 | 默认 | 需要什么 |
|---|---|---|
| ordinary guarded implementation | 可在明确阶段内使用 | clean/可控 worktree + allowlist + Hermes 验证 |
| official TUI `/goal` | 默认不跑 | 用户明确授权 + isolated/clean worktree + bounded goal + stop condition |
| real review subprocess | 默认不跑 | 用户明确授权 + 四重 gate + packet-only review |
| local commit | 不默认等同于实现授权 | 已验证 + 本阶段允许本地 checkpoint |
| push / PR | 默认不做 | 用户明确 push/PR 授权 |
| deploy / restart | 默认不做 | 用户明确部署/重启授权 + runtime 验证计划 |
| secret / real data / real provider | 默认不碰 | 用户明确授权 + 最小暴露 + 不打印 secret |

## 8. QQ 状态汇报模板

| 状态 | QQ 短句 |
|---|---|
| 准备阶段 | 准备执行：选择 driver 和边界；不跑真实副作用。 |
| ordinary lane 运行中 | 运行 guarded lane：只允许指定文件，Codex 产物只是 candidate。 |
| Goal lane 运行中 | 运行 official `/goal`：这是授权 TUI 目标，等待窗口不等于失败。 |
| candidate ready | candidate 已产出，进入 Hermes review/验证，不等于完成。 |
| review unavailable | review 没有可靠完成，改由 Hermes manual review；不冒充通过。 |
| verification failed | 验证失败，停止；先修或回滚，不继续下一阶段。 |
| verified local | 本地验证通过；未 push、未部署、未重启。 |
| authorization needed | 这一步有真实副作用，需要你单独授权。 |

## 9. 暂不做

- 不把 ordinary guarded lane 和 official `/goal` 混成一个黑箱入口。
- 不让 Codex 自己决定下一阶段。
- 不默认打开真实 TUI。
- 不默认打开真实 review subprocess。
- 不在本草案里改 runtime code。
- 不 push / deploy / restart。

## 10. 建议下一小步

如果用户认可本文方向，下一小步可以二选一：

| 选项 | 内容 | 产物 |
|---|---|---|
| A. 继续设计 | 把本文扩成正式 orchestrator design | 仍只改 docs |
| B. 停下 review | 用户先审本文，确认命名和范围 | 无新增改动 |

我的建议：先选 **B**。

原因：这层是“交通规则”，比单个工具更容易影响后续架构。先审清楚，再决定是否正式命名为 Slice 8A / Orchestrator Phase 1。
