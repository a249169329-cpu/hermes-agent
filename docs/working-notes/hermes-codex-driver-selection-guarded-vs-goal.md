# Hermes Codex Driver Selection：Guarded Lane vs Official Goal Lane

> 状态：工作笔记 / 设计对照文档，不是 Hermes skill，也不是 Codex skill。
> 日期：2026-06-16
> 关联文档：`docs/working-notes/hermes-codex-division-of-labor.md`
> 目的：明确 Hermes 调度 Codex 时，两条不同 driver 线路的边界、适用场景、风险门控和后续落点。

## 1. 核心结论

Hermes 调用 Codex 时，不应把所有场景压成一条路。

应明确分成两条 driver：

```text
A. Ordinary Codex guarded lane
   = 受控候选补丁 worker，适合小 slice、窄范围、强 guard。

B. Official Codex /goal lane
   = 官方交互式目标模式，适合 stage 级、长目标、多轮自我推进。
```

一句话：

```text
小而窄，用 guarded lane。
大而长，用 official /goal lane。
Hermes 永远负责拆阶段、定边界、验收、测试、授权门控。
Codex 永远只产出 candidate，不直接拥有最终决定权。
```

## 2. 对照表

| 维度 | Ordinary Codex guarded lane | Official Codex `/goal` lane |
|---|---|---|
| 大白话定位 | 受控打工人，一次做一个小 slice | 阶段型自主工人，围绕一个目标持续推进 |
| 本质 | Hermes 包一层安全壳调用 Codex 做候选 diff | 官方 Codex TUI 里的 `/goal` 功能 |
| 典型入口 | `codex_staged_implement` / `codex_workflow_run` / `codex_stage_runner.py` / `codex_impl_guard.py` / `codex_review_guard.py` | `codex-yuna --enable goals` 后，在 TUI composer 里输入 `/goal ...` |
| 是否等于官方 Goal | 不是 | 是 |
| 适合任务 | 小修、明确文件范围、补测试、修 review blocker、窄实现、只读 review | 阶段开发、模块级任务、需要 Codex 自己计划/执行/测试/修正的多轮目标 |
| 不适合 | 需要长时间目标保持、需要 Codex 持续自我推进的阶段任务 | 很小改动、安全敏感 live 配置、只读诊断、明确单文件小修 |
| 文件范围控制 | 强制显式 `allowed_files` / `allowed_globs` | 通过 `/goal` 文本约束范围，后续靠 Hermes diff review 收口 |
| dirty worktree 策略 | 可强制 `require-clean` / allowlist / isolated worktree | 启动前也应先隔离；Goal 结束后必须重新检查 diff/status |
| 安全边界 | 强：allowlist、dirty baseline、guard、review stop contract、output containment | 中：goal prompt + PTY 监控 + git diff/status + Hermes review；不等于 guard 替代品，也不能当成 fail-closed |
| 执行形态 | 非交互或半自动，通常一次运行结束 | 交互式 TUI，可能在 Hermes 给出的 bounded stage 内多轮推进，可能 `Goal achieved` 后仍停在 composer |
| QQ/WebUI 主要坑 | raw `codex-yuna exec` 可能被 terminal policy / guard 拦截；应走 guarded tool | 多行粘贴可能变 `[Pasted Content]` 或未提交；优先单行 `/goal`，必要时补 `\r` |
| 等待语义 | 看 tool 返回、guard 状态、git diff | `process(wait)` timeout 只是等待窗口到，不等于失败；看 log + git status + diff |
| 输出可信度 | Codex 输出是 candidate evidence，不能直接信 | `Goal achieved` 也是 candidate evidence，不能直接信 |
| Review 方式 | 直接走 bounded review / packet review / Hermes manual review | Goal 结束后也必须走 bounded review / Hermes manual review |
| 完成标准 | Hermes 读 diff + 跑验证 + 无 blocker | 同左；不能只看 Codex 自述完成 |
| push/deploy/restart | 必须另行授权 | 必须另行授权 |
| 适合写入 `AGENTS.md` | 是：默认不要裸跑 Codex；优先 guarded route；候选 diff 必须验收 | 是：官方 `/goal` 只用于 stage；目标必须 bounded；Goal 产物仍需 Hermes 验收 |
| 适合 runtime orchestrator | 已有一部分工具链 | 需要单独设计 TUI Goal driver，不能和 guarded exec 混成一个入口 |

## 3. Driver 选择规则

### 3.1 用 guarded lane，当满足这些条件

- 任务边界清楚，能列出文件范围；
- 目标应一次退出，不需要长期目标记忆；
- 只是修一个 bug、补一个测试、改一段文档、处理一个 review blocker；
- 需要强 allowlist / dirty baseline / fail-closed；
- 当前任务不值得启动完整 TUI Goal。

推荐形态：

```text
Hermes plan
→ codex_staged_implement / codex_workflow_run
→ candidate diff
→ Hermes inspect diff
→ focused tests / docs checks
→ optional read-only Codex review
→ Hermes final decision
```

### 3.2 用 official `/goal` lane，当满足这些条件

- 用户明确说 Codex Goal、官方 `/goal`、Goal mode；
- 任务是 stage 级，不是小修；
- 需要 Codex 在 Hermes 给出的 bounded stage 内自己计划、实现、测试、修正；
- 需要验证 Goal 模式自身行为；
- 一个阶段内可能有多轮“发现问题 → 自修 → 再测”。

推荐形态：

```text
Hermes stage planner
→ isolated worktree / clean baseline
→ one-line /goal objective
→ codex-yuna --enable goals PTY
→ submit /goal
→ monitor process + git diff/status
→ Goal achieved / stop condition
→ Hermes inspect diff
→ tests + review
→ optional follow-up /goal only for blockers
→ local checkpoint after proof and explicit Hermes/user authorization
```

## 4. Hermes / Codex 职责边界

| 角色 | 主责 | 不做 |
|---|---|---|
| Hermes | 需求澄清、阶段拆分、driver 选择、文件边界、风险判断、测试验证、review gate、commit/push/deploy/restart 授权门控 | 不把最终验收交给 Codex；不因 Codex 自称成功就结束 |
| Codex guarded implementer | 按 allowlist 和 task packet 生成候选 diff | 不扩大 scope；不 push/deploy/restart；不绕过 guard |
| Codex Goal worker | 在一个 bounded stage goal 内计划、实现、自测、自修 | 不接管整个项目；不跨 stage 自作主张 |
| Codex reviewer | 只读审查 diff / packet，返回 blockers / risks / evidence | 不写文件；不变成第二个 implementer |

## 5. Guarded lane 任务包骨架

Hermes 给 ordinary Codex 的内容应是任务包，不是整套 Hermes workflow。

```text
Goal: <本 slice 要完成什么>
Scope: <允许改哪些文件/目录>
Non-goals: <明确不做什么>
Context: <必要设计/接口/约束>
Acceptance: <怎么证明完成>
Verification: <建议运行哪些 focused commands>
Stop if: <缺信息/越界/需要授权时返回 BLOCKED>
Output: changed files + verification evidence + blockers
```

禁止把这些直接塞给 Codex implementer 当主规则：

```text
Hermes memory/profile governance
Hermes skill cleanup policy
Hermes runtime ops 总流程
project-dev-workflow 全量 router
长期产品路线规划权限
```

原因：这些属于 Hermes orchestration 层。Codex implementer 只需要执行当前 bounded task。

## 6. Official `/goal` 文本骨架

Goal prompt 要短、单行、阶段限定、验收清楚。

```text
/goal Complete Stage <N> only from current <base> code. First make a short checkpoint plan, then edit. Read <docs/files>. Objective: <one durable objective>. Scope: <allowed changes>. Required tests: <focused tests>. Verify: <commands>. Must not: <out-of-scope side effects>. Stop if <blockers>. Done only when <evidence-based finish line>.
```

中文要点：

```text
只做一个 stage。
先读指定 docs/files。
明确做什么、不做什么。
禁止 push/deploy/restart/真实 provider/真实数据/secret，除非用户授权。
完成后停下给 Hermes review。
```

## 7. Official `/goal` 专属停止条件

Goal lane 不是硬 guard。`/goal` prompt 只能约束行为，不能保证 fail-closed；`git diff/status` 只能覆盖仓库产物，也不能证明没有外部副作用、secret 读取或网络调用。因此 Goal lane 必须更早停下。

遇到这些情况，Hermes 应停止 Goal 流程并回到人工判断：

- worktree / baseline 无法隔离，或已有 dirty 状态无法归因；
- Goal 试图修改范围外文件、跨 stage、重写阶段目标；
- Goal 请求或触发 push / deploy / restart / 真实 provider / secret / 真实数据访问；
- PTY 提交状态不明、多行 paste 失败、`process(wait)` timeout 后无法判断是否仍在执行；
- `Goal achieved` 但无 diff、测试未跑/失败、出现未预期 staged / untracked 文件；
- 需要外部服务、真实账号、真实数据或长期后台进程，但没有用户明确授权；
- Codex 输出与实际 diff/status 不一致。

这些情况不是“继续让 Goal 自己想办法”的信号，而是 Hermes 收回控制权、重新划边界或询问用户的信号。

## 8. Runtime orchestrator 目标形态

未来如果在 Hermes runtime 里进一步产品化，应是“三选一 driver”，不是单一路线：

```text
large user task
→ Hermes stage planner
→ Stage N driver selection
   → Hermes direct edit：极小或安全敏感改动
   → Ordinary Codex guarded lane：窄范围 candidate implementation/review
   → Official TUI Goal lane：stage 级长目标
→ Hermes diff review + verification
→ local commit/checkpoint only after proof and explicit authorization
→ stop before push/deploy/restart/real provider runs unless authorized
```

关键设计要求：

1. driver 选择必须显式记录在 checkpoint 里；
2. Goal lane 不能伪装成 `codex exec "goal-style prompt"`；
3. guarded lane 不能被说成已经覆盖 official `/goal`；
4. 两条 lane 的产物都必须进入同一个 Hermes 验收出口；
5. push/deploy/restart/真实外部调用仍独立授权。

## 9. `AGENTS.md` 建议落点

`AGENTS.md` 可以记录 repo-level 规则，但不能写成最高优先级规则。

建议写入的最小原则：

```md
## Codex / Hermes workflow

- Hermes owns planning, scope, authorization, and final verification.
- Codex output is candidate work only.
- For bounded implementation slices, use guarded routes such as `codex_staged_implement` / `codex_workflow_run` when available.
- Do not run raw `codex-yuna exec` for implementation when guarded routes are available.
- Official Codex `/goal` is an interactive TUI stage driver, not a long `codex exec` prompt.
- Use `/goal` only for bounded stage-level objectives with explicit stop conditions.
- No push, deploy, restart, secret access, or real-provider runs without explicit user authorization.
```

不建议写：

```text
AGENTS.md 是唯一执行规范。
Codex 可以自己决定下一阶段。
Goal mode 可以替代 Hermes review。
Hermes skills 整包塞给 Codex。
```

## 10. 后续行动建议

短期：

1. 保留本文作为 working note；
2. 后续若整理 6/8 Codex workflow 文档，可把本文作为“driver selection”章节；
3. 若改 `AGENTS.md`，只放最小原则，不塞完整流程；
4. 若继续 runtime 实现，先设计 official TUI Goal driver 的 PTY lifecycle 和 evidence model。

中期：

1. 为 TUI Goal lane 定义 `goal prompt file` / `one-line goal file` 生成规则；
2. 为 Goal lane 定义 process wait timeout、`Goal achieved`、idle composer、0-diff、partial diff 的状态模型；
3. 为两条 lane 统一输出 candidate evidence schema；
4. 为 review packet 补齐 staged / untracked / Goal-produced files 的取证路径。

暂不做：

- 不创建新的 Hermes skill；
- 不创建新的 Codex skill；
- 不恢复旧 stash docs；
- 不改 live gateway / WebUI；
- 不运行真实 Codex implementation；
- 不 push / deploy / restart。

## 11. Review checklist

后续 review 本文或相关实现时，看这些点：

- 是否把 official `/goal` 和 `codex exec` 区分清楚；
- 是否把 guarded lane 和 Goal lane 都纳入，而不是偏废一条；
- 是否保持 Hermes 最终验收权；
- 是否明确 Codex 输出只是 candidate；
- 是否避免把 Hermes skills / memory / runtime ops 整包塞给 Codex；
- 是否明确 push/deploy/restart/真实外部调用必须另行授权；
- 是否没有要求用户把非 secret 行为开关写进 `.env`；
- 是否与 `docs/working-notes/hermes-codex-division-of-labor.md` 保持一致。
