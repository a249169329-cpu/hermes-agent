# Hermes / Codex 分工原则

> 状态：普通文档记录，不是 Hermes skill，不是 Codex skill。
> 目的：固定当前约定，后续再评估是否安装 GitHub 上现成的 Codex skill 包。
> Driver 选择细节见：`docs/working-notes/hermes-codex-driver-selection-guarded-vs-goal.md`。

## 核心结论

最佳分工：**Hermes 设计计划，Codex 落地执行。**

Hermes 不应把一整套 Hermes workflow / router / verification / project-management 规则塞给 Codex，避免两个代理同时争夺“谁来做计划、谁来改范围、谁来决定下一阶段”。

一句话规则：

```text
Hermes skills 管流程；Codex skills 管执行姿势。
```

## 角色边界

| 角色 | 主责 | 不做 |
|---|---|---|
| Hermes | 需求澄清、产品/架构判断、阶段计划、文件边界、验收标准、风险门控、最终验证 | 不把所有流程压力转嫁给 Codex；不让 Codex 决定产品方向 |
| Codex implementer | 按 Hermes 给出的 bounded plan 落地代码，保持 diff 小，返回变更和测试摘要 | 不重新设计产品；不扩大范围；不 push/deploy/restart；不越过 allowlist |
| Codex reviewer | 只读审查 diff 是否符合 Hermes plan，输出 blockers / risks / evidence | 不改文件；不变成第二个 implementer |

## Hermes 应该给 Codex 的内容

Codex 接到的应是“任务包”，不是整套 Hermes 工作流。

任务包包含：

```text
目标：本阶段要实现什么
范围：允许改哪些文件/目录
非目标：本阶段明确不做什么
上下文：必要的设计/接口/数据约束
验收：怎么证明完成
测试：建议运行哪些命令
停止条件：何时返回 BLOCKED
输出要求：changed files + verification evidence + blockers
```

## Codex 不应该收到的内容

不要把这些 Hermes 层规则原样安装/注入给 Codex：

```text
project-dev-workflow
writing-plans
staged-large-task-contract
verification-before-completion
codex-staged-development-review
Hermes skill cleanup / runtime ops / memory profile rules
```

原因：这些是 Hermes 的 orchestration / governance / routing 规则。直接给 Codex 会导致：

- Codex 也开始拆计划、改边界、做阶段判断；
- Hermes 和 Codex 都想当 PM；
- 实现者被流程噪音干扰，执行变慢；
- 越权修改、范围膨胀、重复 review 的风险上升。

## Codex skill 使用原则

后续如果使用 GitHub 上的 Codex skill 包，优先选择“窄职责”技能：

1. 实现姿势类：帮助 Codex 按计划实现、控制范围、报告结果。
2. 只读 review 类：帮助 Codex 审 diff，不写文件。
3. 工具/语言/框架专用类：帮助 Codex 使用某个库、测试框架或 CLI。

不优先安装“大型项目管理 / 全流程代理 / 自主规划”类 skill，除非明确需要 Codex 自己担任主代理。

## 标准流程

```text
1. Hermes 读取需求和项目上下文。
2. Hermes 产出阶段计划：目标、边界、验收、测试。
3. Hermes 把单个 bounded stage 交给 Codex implementer。
4. Codex 只按计划落地；缺信息则返回 BLOCKED。
5. Hermes 检查 git diff / 文件内容 / 测试结果。
6. 必要时 Hermes 发起 Codex read-only review。
7. Hermes 根据 review 决定修复、继续、停止或询问用户。
8. commit / push / deploy / restart 仍由 Hermes 按用户授权门控。
```

## BLOCKED 规则

Codex 遇到以下情况应停止并返回 `BLOCKED`，不要猜：

- Hermes plan 缺少关键业务规则；
- 需要修改 allowlist 外文件；
- 发现设计与现有代码冲突；
- 需要真实数据、secret、外部服务、部署或重启；
- 测试命令不可运行且无法判断是环境问题还是代码问题。

Hermes 收到 `BLOCKED` 后负责补计划、问用户或调整阶段，不让 Codex自行扩大范围。

## 推荐 Codex prompt 骨架

```text
You are the implementation worker for a Hermes-orchestrated stage.
Follow the provided plan exactly.
Do not redesign the product or expand scope.
Only modify the allowed files/directories.
Do not push, deploy, restart services, or read/print secrets.
If required information is missing, stop and return BLOCKED with the exact missing facts.
When done, return: changed files, key decisions, verification commands/results, and remaining risks.
```

## 附录：AGENTS.md 草案判断（2026-06-16）

用户讨论过一份面向 Codex / Hermes 的 `AGENTS.md` 草案，核心方向是正确的：范围控制、简单优先、精准改动、验证闭环、记录落点和高风险确认，都适合作为仓库施工规范。

我的判断：**可以用，但不能写成“唯一执行规范”。** 更准确的定位是：`AGENTS.md` 是 repo-level 项目执行规范，约束仓库内怎么改、怎么验、怎么记录；它不能覆盖系统规则、安全规则、Hermes 工具规则、QQ 回复风格、已加载 skill、平台限制或用户当前明确指令。

建议给不同代理的强度不同：

| 对象 | 建议强度 | 说明 |
|---|---|---|
| Codex implementer | 强约束 | 适合强调 allowlist、最小 diff、测试证据、BLOCKED 停止条件，不让 Codex 自主扩 scope。 |
| Codex reviewer | 只读强约束 | 适合强调只审查、不写文件、只报 blockers / risks / evidence。 |
| Hermes | 中强约束 | Hermes 可以参考并执行 repo-level 施工规范，但仍由系统规则、工具规则、用户授权和 Hermes orchestration 负责最终门控。 |

不建议原样保留的点：

- “唯一执行规范”容易误导；应改成“本仓库内统一项目执行规范”。
- “实施前必须陈述所有假设”太重；应改成“影响目标、范围、安全、验收时才停下”。
- `desktop-commander`、`Serena`、`Codex 自带工具` 等工具名不通用；应写成“若当前环境可用”。
- 简单问答不应强制套完整汇报格式；QQ/Hermes 默认仍应短中文，复杂施工才使用阶段性结构。
- 不应把 Hermes 的 workflow / routing / memory / skill governance 整套塞给 Codex；Codex 只拿 bounded task packet。

推荐开头定位：

```md
# AGENTS.md

本文件是本仓库内模型/代理的项目执行规范。
它约束仓库内的代码修改、文档修改、验证与记录方式。
若与系统规则、平台安全规则、工具限制、用户当前明确指令冲突，以更高优先级规则为准。

用户指令决定“做什么”；本文件约束“如何在本仓库内安全、最小、可验证地做”。
```

推荐工具段定位：

```md
工具选择以最小有效路径为准。
若当前代理支持 Codex、语义搜索、文件补丁、终端、浏览器等工具，应优先选择最安全、最小、最可验证的工具组合。
不得假设某个工具一定存在；工具不可用时，使用当前环境中等价的安全路径。
```

### 给其他会话的交接信息

后续其他会话如果继续处理这份 `AGENTS.md` 草案，先按这个判断接续，不要重新把问题退回“能不能用”的阶段。

- 已确认：草案方向可用，适合作为 repo-level 施工规范，不适合作为最高优先级或唯一规范。
- 已确认：给 Codex 应更窄、更硬、更执行向；给 Hermes 应保留系统/工具/skill/用户授权的上层门控。
- 主要依据：Hermes/Codex 分工应避免双 PM；Codex 只拿 bounded task packet；Hermes 负责设计、边界、授权、最终验证。
- 继续动作：如要正式改某仓库的 `AGENTS.md`，先改开头优先级、澄清触发条件、工具中立表述、高风险边界，再按仓库要求验证和记录。
- 注意：这只是判断与交接记录；尚未把任何仓库根目录 `AGENTS.md` 改成该草案版本。

## 当前决策

- 暂不创建自定义 Hermes skill。
- 暂不创建自定义 Codex skill。
- 后续如要给 Codex 安装 skill，优先评估 GitHub 上已有 Codex skill 包。
- 当前先把“分工边界”、`AGENTS.md` 草案判断、driver 选择对照作为普通文档保存，供后续流程清理、Codex skill 选型和 runtime orchestrator 设计参考。
