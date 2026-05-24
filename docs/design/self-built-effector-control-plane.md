# 自建 Effector：一个 MAN 实例

> 状态：设计草案(v0.2 方向),非当前实现规格。配套决策见 [ADR-0012](../adr/0012-self-built-effector-control-plane.md)。
> 目标架构：[v0.3 §10](./v0.3-morphogenetic-architecture.md#105-实现分期-2026-05)；连线映射：[joinpoint model Appendix E](./opencoat-openclaw-joinpoint-model-v0.1.md#appendix-e--v03-action--a_reflex-mapping)。
> 谱系：[形态发生 Agent 纲要](./morphogenetic-aspect-agent.md)；2004 论文 RAL(脊髓/反射)÷ KBAL(皮层/可塑)。

---

## §0. 一句话

```
effector = M = (N, ⇩_fast, ⇩_slow, F, κ, T(·))
```

**effector 不是"LLM + 旁挂控制面"，而是一个完整的 MAN 实例。**
LLM 是 `⇩_fast` 里被外包的 System1；确定性控制面是图状态 `N` 中 `A_reflex` 子集在效应边界的同步 gate；
软织入是 `A_cortex = A \ A_reflex`，受 `⇩_slow` 形态发生驱动。

把今天"OpenCOAT 作为客人插件、只能发建议"翻转为"OpenCOAT 拥有效应边界"的那个翻转，
**形式上就是：把 Tier C 挂载点变成 `⇩_fast` 里 `A_reflex` gate 的同步阻断点。**

---

## §1. 为什么 effector = M 实例（而非"控制面"）

### 当前合作式路径的三重问题

| 问题 | MAN 语言 | 证据 |
|---|---|---|
| 织入退化为 prompt 文本，因果不可知 | `⇩_fast` 的效应边界不在 OpenCOAT 图内 | `injector.ts`："Notes only — do not overwrite structured params" |
| `WeavingOperation` 无软硬之分 | `A_reflex` 与 `A_cortex` 被压成同一个 enum，gate 语义缺失 | `envelopes.py`：12 op 平铺，无 `enforcement` 字段 |
| 硬 advice 信用不干净 | `κ(a)` 无法归因（因果未知 → 反事实估计有噪） | morphogenetic §9：soft advice 信用统计估计，带噪 |

**结论**：问题不是"控制面不够强"，而是**效应边界不在图里**。
把效应边界拉进图 = fork OpenClaw + 把 Tier C 挂载点变成 `⇩_fast` 的同步 gate = 解决上面全部三条。

### fork 的形式含义

fork 让 OpenCOAT 在 `tool.before_execute` / `memory.before_write` / `response.before_final` 等点
插入**阻断式中介**（即 `⇩_fast` 里的 `A_reflex` gate）：

```
⇩_fast 一轮 = joinpoint 匹配 → pointcut gate（A_reflex） → advice 注入 → LLM 效应 → 效应边界 gate（A_reflex）→ 产出
```

---

## §2. 状态 `N = (A, S, x)`

```
A = A_reflex ⊎ A_cortex
```

| 子集 | 类型 | 参与 `⇩_slow`？ | 信用 |
|---|---|---|---|
| `A_reflex` | 确定性反射 aspect；在效应边界同步 gate | **否**（脑干不变量） | 干净（因果已知） |
| `A_cortex` | 软 advice aspect；prompt 级条件化 + DCN 可塑 | **是**（形态发生主体） | 统计（反事实估计） |

**`A_reflex` 成员**（初始集合，由 meta-concern 治理扩缩）：

| aspect id | 挂载点 | 默认裁决 fail mode | **Current (2026-05)** |
|---|---|---|---|
| `reflex.tool_guard` | `tool.before_call` | deny | **collaborative** — bridge `tool_guard` + daemon RPC |
| `reflex.memory_guard` | `memory.before_write` | deny | **skipped** — sync hot path; pending in-proc TCB |
| `reflex.response_verifier` | `response.before_final` | allow* | **collaborative** — `message_sending` outbound cancel |
| `reflex.spawn_guard` | `task.before_create` / subagent spawn | deny | **collaborative** — spawn veto via bridge |
| `reflex.queue_guard` | `queue.before_enqueue` | allow | **partial — fork hook + bridge `queue_guard` (collaborative)** block/rewrite |
| `reflex.phase_gate` | `reply_run.phase.*` | allow | **not wired** |

\* `response.before_final` 默认 fail-open 防止卡死 agent；严格场景由治理面升级为 fail-closed。

**突触 `S`**：`A_reflex` 的出边指向 `A_cortex`（单向；反射 gate 结果可作为软 advice 的激活上下文输入，但不反向）。
**激活态 `x`**：当前轮 gate 中间状态；`A_reflex` gate 的 `x` 是确定性布尔/补丁，`A_cortex` 的 `x` 是激活分数。

---

## §3. 快动力学 `⇩_fast`：effector 一轮

MAN §2 的 π 归约，在 effector 里展开为：

```
1. joinpoint 事件 φ 到达（工具调用 / 写记忆 / 交付响应 / ...）
2. A_reflex 同步 gate(φ) → Verdict（阻断；未返回前底层效应不执行）
3. Verdict.allow → pointcut 匹配 A_cortex 候选 → advice 注入 → LLM(System1) 消费
4. LLM 产出 → 再次触发效应边界 gate（步骤 2 的下游挂载点）
5. 最终效应写出；资格迹 e_a / e_s 累积
```

**A_reflex gate 是 `⇩_fast` 里的同步阻断节点**，不是异步建议。
这是"fork" = "把 Tier C 挂载点变成进程内同步"的形式表达。

---

## §4. `A_reflex` 裁决语义（Verdict）

gate 在每个挂载点产出一个 **Verdict**（纯函数：给定输入快照 + `A_reflex` 成员集 → 确定输出）：

```typescript
type Verdict =
  | { kind: "allow" }
  | { kind: "deny";              reason: string }
  | { kind: "rewrite";           patch: StructuredPatch; reason: string }
  | { kind: "require_approval";  prompt: string }
  | { kind: "defer";             until: JoinpointSelector }

type GateDecision = {
  weave_id:    string;
  joinpoint:   string;          // e.g. "tool.before_execute"
  verdict:     Verdict;
  enforcement: "hard";          // A_reflex gate 恒为 hard
  by:          string[];        // 命中的 A_reflex 成员 ids
  fail_mode:   "deny" | "allow";
}
```

**裁决偏序（确定性、可重放）**：`deny > require_approval > rewrite > defer > allow`。

多 `A_reflex` 成员命中同一挂载点时，按偏序合并；同级 `rewrite` 按 `declare precedence` 顺序应用补丁，冲突降级为 `deny` 并记日志。

**整个 gate 过程是纯函数** → 给定 JSONL 快照，结构轨迹逐字节可重放（对齐 MAN §8、ADR-0007）。

---

## §5. 信用场 `κ` 与慢动力学 `⇩_slow`

### 硬裁决 → 干净信用

`A_reflex` 的每次 gate 产出因果已知的信号：deny = 底层效应确实未执行，rewrite = 确实按补丁执行。
因此：

```
κ(a_reflex) += (r_t − b) · e_a(t) · ρ_a(t)    // ρ tier-1，纯日志，无需反事实
κ(s)        += (r_t − b) · e_s(t)
```

`A_cortex` 的 advice 因果不可确定（随机 LLM），`ρ` 需要 tier-2 反事实校准（带噪，贵）。

**`A_reflex` 信用是 `⇩_slow` 的低噪驱动源**：它驱动 `A_cortex` 的 split / connect / prune，
同时自身被 `⇩_slow` 排除在外（`A_reflex ∩ ⇩_slow 改写文法 = ∅`）。

### 三时间尺度

| 尺度 | effector 里跑什么 |
|---|---|
| 快（每轮） | `⇩_fast`：gate + advice 注入 + LLM 效应；资格迹累积 |
| 温（近线） | `A_cortex` reweight + connect / prune；`κ` tier-1 驱动 |
| 冷（心跳） | `A_cortex` split / lift / merge + tier-2 反事实校准；`A_reflex` 成员集治理审查（只增不减，除非 meta-concern 明确授权） |

`A_reflex` 成员集在冷尺度接受**治理审查**（ADR-0008 `GovernanceCapability`），但审查结果是"加/删成员"而非随机改写 aspect 内部结构。

---

## §6. 接口契约

### fork 侧（π 演算风格：同步通道）

```typescript
// 每个效应边界 = 一个同步通道；mediate 返回前通道阻断
interface ReflexGate<TCtx> {
  joinpoint: string;                               // 对应 A_reflex 成员的挂载点
  mediate(ctx: TCtx, deadlineMs: number): Promise<GateDecision>;
  //  同步阻断；超时按 fail_mode 处理；ctx 只读快照
}

registerReflexGates(gates: ReflexGate<unknown>[]): void;  // fork 注册 6 个挂载点
```

**Today (2026-05):** six joinpoints are defined; **four have collaborative bridge guards** (`tool`, `message`, `spawn`, `queue` on fork); **zero have in-proc authoritative TCB** (`ReflexMonitor`). See [v0.3 §10.5](./v0.3-morphogenetic-architecture.md#105-实现分期-2026-05).

### OpenCOAT 侧（新 hexagonal port，扩展 ADR-0006）

```python
class EffectorReflexPort(Protocol):       # A_reflex 在 OpenCOAT core 里的 port
    def gate(self, jp: JoinpointEvent, deadline_ms: int) -> GateDecision: ...
    def reflex_set(self) -> frozenset[str]: ...   # A_reflex 当前成员 ids
```

**契约硬要求**：
1. **同步阻断**：`mediate` 返回前不得执行底层效应。
2. **超时即 fail_mode**：deny 子集超时 = deny；allow 子集超时 = allow + 记 `degraded`。
3. **只读快照**：`ctx` 是 host 状态快照；改动只经 `rewrite` 补丁回流。
4. **可重放**：每次 `gate` 的输入快照 + `GateDecision` 写 JSONL（与 MAN §8 资格迹同一日志流）。

> 接入 fork 时只需补一件事：把 §3 六个 `⇩_fast` 挂载点的 `mediate(...)` 接到 fork 真实调用点；OpenCOAT 侧无需改动。

---

## §7. 与现有代码的衔接（增量，不推倒）

| 现有 | 改动 | MAN 含义 |
|---|---|---|
| `WeavingOperation`（12 op） | 加 `enforcement: hard\|soft` + `fail_mode` 分类表（`weaving/enforcement.py`） | 显式区分 `A_reflex` op 与 `A_cortex` op |
| `AdviceType` | `TOOL_GUARD`/`MEMORY_WRITE_GUARD` 归 `A_reflex`（hard）；其余归 `A_cortex`（soft） | 把 enum 成员映射到图子集 |
| `injector.ts` 决策函数 | fork 路径：从"建议"升级为 `GateDecision`；bridge 路径保持合作式不变 | `⇩_fast` gate 替换合作式 suggest |
| ports（ADR-0006） | 加 `EffectorReflexPort` | 新 hexagonal port；core 仍 host-agnostic |
| concern `reflex` 字段 | 新增布尔标记；`DCN ⇩_slow` 改写文法跳过 `reflex=true` 的 aspect | `A_reflex` 在图里的物理标记 |
| JSONL replay（ADR-0007） | `GateDecision` 纳入同一日志流 | 快时间尺度 gate 可重放；喂冷时间尺度信用校准 |
| `ConcernVector.activation_score` | 对应 MAN `a_i`（激活分数）；gate 结果可作为下游 `A_cortex` 的上下文输入 | `S` 的权重流 |

**关键**：这是"在已有 weaving 上，把 `A_reflex` 子集做硬"，不是另起炉灶。

---

## §8. 路线图（三时间尺度对齐）

每个里程碑对应 MAN 的一个时间尺度层或一个组件；全部遵循仓库 PR 工作流（AGENTS.md）。

| 里程碑 | MAN 时间尺度 | 范围 | 交付物 | 可证伪/验收 |
|---|---|---|---|---|
| **M-E0 A_reflex 标记** | 基础设施 | `WeavingOperation`/`AdviceType` 加 enforcement+fail_mode 表；concern `reflex` 字段；`⇩_slow` 跳过逻辑 | `weaving/enforcement.py`、concern schema 更新、单测 | 12 op 全覆盖；`A_reflex` 成员被 `⇩_slow` 跳过（测试可证） |
| **M-E1 EffectorReflexPort** | 快（`⇩_fast` gate） | `GateDecision` 协议 + 裁决合并纯函数 + `EffectorReflexPort` port + JSONL replay 写入 | 新 port、协议类型、合并器 | 给定输入 + aspect 集，GateDecision 逐字节可重放 |
| **M-E2 影子模式** | 快（旁路观测） | fork 未接前：`⇩_fast` 旁路跑 `A_reflex` gate，只记 `GateDecision` 不执行 | shadow runner、GateDecision JSONL | 影子裁决 vs 实际宿主行为差异报告（量化合作式缺口） |
| **M-E3 fork 接入（tool）** | 快（gate 真正生效） | `tool.before_execute` deny/rewrite 硬拦截、fail-closed | `opencoat_runtime_host_effector`、fork mediation 钩子 | 红队：被 deny 的工具调用确实未执行；超时 fail-closed |
| **M-E4 fork 接入（memory/response）** | 快 | `memory.before_write`、`response.before_final` 硬拦截 | 两挂载点 mediation | 写入脱敏/响应改写在交付前确定性生效 |
| **M-E5 治理+人在环** | 冷（`A_reflex` 成员集审查） | meta-concern 覆盖 fail_mode；`require_approval` 闭环；冷时间尺度成员集治理 | 治理覆盖 API、approval 流 | 严格 concern 把 `response.before_final` 升为 fail-closed |
| **M-E6 信用回流** | 温/冷（`κ` → `⇩_slow`） | 硬裁决 `GateDecision` 喂 `κ` tier-1；资格迹累积；接 aspect 网 `⇩_slow` | 信用桥、JSONL→κ pipeline | 硬子集信用方差 < 软子集（度量）；与 MAN §8 可证伪预测对齐 |

**依赖**：M-E0 → M-E1 → {M-E2 影子, M-E3 fork}。M-E2 不依赖 fork，可立即开始。

---

## §9. 不变量（良构 / 可证 safe）

继承 MAN §7：

- **域守恒**：split 后 `dom(a₁) ⊎ dom(a₂) = dom(a)`，`A_reflex` gate 的覆盖域不缩小。
- **流守恒**：总权守恒（`A_reflex` gate 是幂等的，不引入新信用）。
- **信用守恒**：`Σ_a κ_a(t) = r_t − b`（不重复计；`A_reflex` 的干净信用不通胀）。
- **`A_reflex` 不参与 `⇩_slow` 随机改写**：这是自进化的不变量边界（脑干）。
- **细化保行为**：gate 是 refinement，在 gate 作用域外可证不改变 `⇩_fast` 行为。

---

## §10. 风险与边界

- **fork 漂移**：mediation 钩子做薄（只接 §3 六个点）、契约稳定、其余 rebase。
- **`A_reflex` 自身故障**：硬边界 bug 可卡死 agent → 不变量 + 超时 fail_mode + JSONL 可重放兜底。
- **fail-closed 的可用性代价**：`response` 默认 fail-open；`A_reflex` 成员集冷时间尺度治理可调。
- **不可约软点（MAN §9）**：`A_cortex` 对随机 LLM 的因果仍不可确定获知——本设计不消除它，只是把更多织入移入 `A_reflex`（由 M-E6 信用回流量化迁移进度）。

---

## 交接备注（handoff）

- **立即可起步**：M-E0 / M-E1 / M-E2 全在 OpenCOAT 仓库内，不依赖 fork。M-E2 产出"合作式缺口"量化证据，同时为 M-E6 信用回流准备真实 JSONL。
- **fork 接入最小集**：只需把 §3 六个 `⇩_fast` 挂载点的 `mediate(...)` 接到 fork 真实调用点；OpenCOAT 侧 `EffectorReflexPort` 已就绪。
- **与 MAN 纲要的接口**：`A_reflex`（MAN §1）、gate = `⇩_fast` 同步节点（MAN §2）、硬裁决=干净信用（MAN §9）、可重放（MAN §8）四处对齐；本线产出的 `GateDecision` JSONL 即 MAN `κ` 的直接输入。
- **v0.1 → v0.2 的核心变化**：主语从"控制面"换成 `M` 实例；`EffectorControlPlane` 改名为 `EffectorReflexPort`（强调它是 `A_reflex` 在图里的 port，而非旁挂的"面"）；路线图对齐三时间尺度；接口契约增加 π 演算风格的通道语义注释。
