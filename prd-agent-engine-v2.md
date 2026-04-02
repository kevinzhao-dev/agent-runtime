# PRD: Agent Engine — 一個從生產級 Coding Agent 學習的 Python Template

> **版本**: v1.1  
> **日期**: 2026-04-02  
> **狀態**: Draft for Review

---

## 1. 背景與動機

### 1.1 為什麼要做這個專案

市面上有大量 AI Agent 的教學與 demo，但多數停留在「呼叫 LLM + 接幾個工具」的層次。真正在生產環境裡穩定運作的 agent 系統，需要解決的問題遠超這個範圍：上下文如何在有限的 token 預算內治理、錯誤如何分層恢復而不是一出問題就崩、多代理如何共用同一個引擎而不是各造各的輪子、驗證如何跟實作分離而不是讓系統自己給自己打分。

業界目前最成熟的 coding agent 之一，其開源源碼揭示了一套完整的 agent runtime 設計。這套設計最重要的啟示不在任何單一功能，而在一個貫穿全局的態度：**把模型當不穩定部件，把可靠性做進 harness（挽具），而不是寄託在模型的自覺性上**。

本專案的目的是透過實作來學習這些工程實踐，產出一個具體而微的 Python agent engine template，既是學習成果，也可作為未來 AI Agent 專案（如 3D Generation Pipeline）的 PoC 起點。

### 1.2 本專案不是什麼

- **不是某個特定產品的 Python 翻譯**：我們取其精髓，不複製其全部複雜度
- **不是通用 agent framework**：它是一個 coding agent template，帶有明確的設計觀點
- **不是生產級產品**：它是 PoC + 學習工具，優先清晰度而非完整度

---

## 2. 目標與非目標

### 2.1 目標

| 編號 | 目標 | 驗收標準 |
|------|------|---------|
| G1 | 實作一個有狀態的 query loop，支援多輪工具呼叫 | 能在 CLI 中下達 coding 任務（如「建立一個 FastAPI server」），agent 自主讀寫檔案、跑 bash、迭代修正，直到完成 |
| G2 | 實作分層 context 治理，包含自動壓縮與 token 預算 | 長對話超過 context window 閾值時自動觸發 compact，compact 後能繼續工作而非失去關鍵上下文 |
| G3 | 實作分層錯誤恢復 | prompt-too-long 自動 compact retry、max-output-tokens 自動續寫、API error exponential backoff，均帶 circuit breaker |
| G4 | 實作 multi-agent（同一引擎遞歸） | Coordinator 能透過 AgentTool 分派子任務，子 agent 有獨立 context 和 abort 控制 |
| G5 | 實作獨立 verification agent | Verifier 用 read-only 工具集獨立檢查 implementation 結果，回傳結構化的判定結果 |
| G6 | 提供可複用的 template 結構 | 同一個 engine 支援 CLI 和 SDK 兩種入口，未來專案可 import 使用 |

### 2.2 非目標（明確排除）

| 編號 | 非目標 | 原因 |
|------|--------|------|
| NG1 | MCP server 支援 | 增加大量通訊層複雜度，與學習核心 agentic workflow 無關 |
| NG2 | Web UI | CLI + SDK 足夠驗證，UI 是獨立專案 |
| NG3 | 多 LLM provider 切換 | 只用 Anthropic Claude API，避免抽象層過早泛化 |
| NG4 | 生產級安全沙箱 | Bash 工具用基礎 permission gate，不做 Docker 隔離 |
| NG5 | Prompt cache 優化 | 這是 API 層面的優化，與 agent runtime 學習目標無關 |

---

## 3. 核心設計哲學

本專案的設計哲學濃縮自一個核心觀察：成熟的 agent 系統，其複雜度不在模型有多聰明，而在模型之外的 harness 如何組織約束與執行。以下哲學貫穿整份 PRD 的每一個技術決策。

### 3.1 Harness Engineering：秩序住在運行時

一個會寫程式碼的模型被放進終端機以後，真正的問題不是「它會不會寫」，而是「它寫錯了怎麼辦、寫到一半被打斷怎麼辦、上下文爆了怎麼辦、它自以為改對了但其實沒改對怎麼辦」。

Harness Engineering 的核心立場是：**把模型當不穩定部件，把可靠性做進系統，而不是寄託在模型身上**。你越早承認模型不可靠，系統就越早開始長出權限、恢復、驗證和回滾。這不是悲觀，這是工程紀律。

### 3.2 Agent 不是加強版問答，Agent 是有狀態的執行過程

很多人把 agent 理解成「LLM + 幾個工具」，那只是一個花哨的問答。真正的 agent 依賴一段持續的、有狀態的執行循環。這個循環不是把模型呼叫包在 try/catch 裡就結束，它要維護跨輪次的狀態，處理前置治理、流式消費、工具調度、恢復分支、停止條件。

判斷一個系統能不能被稱為 agent，往往不取決於它會不會說，而取決於它能不能在幾輪之後仍然知道自己在做什麼。

### 3.3 上下文是稀缺資源，不是免費空氣

每個 token 都有成本，每條訊息都占空間。能按需載入的不要一開始就塞進去，能壓縮的要壓縮，能丟棄的要丟棄。上下文治理不是「快爆了才處理」的緊急操作，而是每一輪模型呼叫之前的例行公事。

在有限的 context window 裡裝最有用的資訊，這件事的優先級比「讓模型推理得更好」更高。因為如果上下文爛了，再好的推理也只是在爛資料上做推理。

### 3.4 錯誤路徑就是主路徑

Prompt too long、max output tokens、API rate limit、compact 自身失敗、子 agent 跑飛——這些不是邊緣案例，而是長會話代理的日常天氣。在設計時就考慮恢復、熔斷、限次、防死循環，和在出了問題之後才補，是兩種根本不同的系統品質。

恢復的目標不是展示禮貌的錯誤訊息，而是讓系統繼續工作。截斷之後最好的動作是續寫，壓縮失敗時最重要的是先讓系統恢復呼吸。

### 3.5 多代理的意義是把不確定性分區

Multi-agent 不是為了看起來厲害。它的真正價值是把研究、實作、驗證、綜合放進不同的職責容器裡，讓每個容器有自己的 prompt、工具集、context 和 abort 邊界。隔離不確定性，分離角色，最後由 coordinator 收束理解——並行真正帶來的價值是更清楚，不是更快。

### 3.6 驗證必須獨立

實作者天然傾向於相信自己的改動「差不多行了」。模型更是如此。如果系統讓同一個 agent 既實作又驗證，它就把「我改完了」和「它已經正確了」混為一談。凡是重要任務，驗證都應該成為獨立階段、獨立角色、獨立工具集。

---

## 4. 設計原則

以下原則是上述哲學在具體工程上的落地。每一條都有明確的實作對應。

### 原則 1：Query Loop 是心跳，不是請求-回應

Agent 的核心是一個 `while True` 的 async generator 主循環。每一輪迭代的結構是：**治理輸入 → 呼叫模型 → 消費流式輸出 → 執行工具 → 恢復或停止 → 決定下一輪**。模型呼叫只是心跳中的一次收縮，而非循環本身。把主循環設計成 async generator 意味著 loop 內部的每一步都能即時被外部消費——這比返回一個完整結果重要得多，它讓系統在模型尚未完成之前就能開始安排下一步。

> **實作對應**：`engine/loop.py` — 全專案最重要的檔案

### 原則 2：Prompt 是控制面，不是人格裝修

System prompt 的職責是定義行為協議——能做什麼、什麼時候做、做錯了怎麼辦、誰來兜底。它和 runtime、tool schema 一起組成控制平面。把 prompt 當人設，最後你會得到一個很會表演但不受約束的系統。

更關鍵的是，prompt 必須是分層拼裝的，而且有嚴格優先級。成熟系統不會迷信唯一版本的 prompt，它把 prompt 看成一個有層級的配置系統：override > coordinator > agent > custom > default。不同角色在不同上下文裡生效，新增角色只能在基礎約束之上叠加領域行為，而不能換掉底層紀律。

> **實作對應**：`context/prompt.py` — 分層 prompt assembly + 優先級鏈

### 原則 3：狀態屬於主業務，而非副作用

很多系統把狀態當包袱，覺得 stateless 才優雅。對 agent 系統來說，這種偏好毫無意義。只要進入真實工作流，狀態就會自然出現——messages、turn count、recovery counters、compact tracking、tool use context。忽視狀態不能消除它，只會讓它以更難管理的方式回來。

正確做法是把所有跨輪次狀態顯式定義為一個 frozen dataclass，在每輪結束時整體建立新物件。這讓狀態可追蹤、可序列化、可偵錯——而且讓 state transition 的因果鏈清清楚楚。

> **實作對應**：`engine/state.py` — LoopState frozen dataclass + Transition

### 原則 4：先治理，再推理

在每輪模型呼叫前，runtime 先跑一整串 context 治理：檢查 token 預算、判斷是否需要 compact、組裝 system prompt。它不把「從混亂中整理秩序」的責任交給模型，而是由 runtime 先清理好再交出去。很多系統恰恰相反：先把大量上下文塞進去，再寄希望於模型自己判斷什麼重要。那種做法看似省事，實際上是在把 runtime 應承擔的責任轉嫁給概率分布。

> **實作對應**：loop 主體在 `call_model()` 之前，先執行 `pre_model_governance()` pipeline

### 原則 5：恢復是主路徑的一部分，而且必須分層

錯誤恢復不是 catch block 裡的禮貌動作，它是 loop 的正式分支。恢復按破壞性從低到高分層嘗試：先 context collapse，再 reactive compact，再 truncate head。每種恢復都生成新的 State + Transition，然後 `continue` 回到 loop 頂端，而不是重新遞歸呼叫自己（遞歸在長會話裡會爆栈）。

更重要的是，恢復必須有 circuit breaker。一個不會收手的恢復系統，和一個不會恢復的系統一樣危險，只是它危險得更勤奮一點。

> **實作對應**：`engine/recovery.py` — 恢復策略函式，被 loop 呼叫但不自己驅動控制流

### 原則 6：多代理是同一引擎的遞歸

Multi-agent 不需要另一套系統。AgentTool 是一個普通的 tool，當模型決定 delegate 時，它 spawn 一個新的 engine 實例——用不同的 prompt、不同的工具集、獨立的 abort controller。所謂 coordinator 只是「工具列表裡包含 AgentTool 的那個 engine 實例」。

角色差異不靠獨立的 Coordinator class，而靠一個 RoleConfig dataclass：不同的 prompt sections、不同的 allowed tools、不同的 read_only 旗標。Coordinator、Implementer、Verifier 都只是不同的 RoleConfig 實例，跑在完全相同的 engine 上。

> **實作對應**：`tools/agent_tool.py` + `roles/config.py`

### 原則 7：工具是受管執行介面，不是直通管道

一旦模型開始碰 shell、檔案系統和外部世界，問題就從「它會不會說」變成「它會不會留下後果」。工具不能讓模型說調就調，中間要有 permission gate（allow / deny / ask 三態），執行完要有結果收集和錯誤處理。

Permission gate 是 tool execution pipeline 的一環，不是獨立系統。它和工具執行、結果回傳、錯誤處理共同組成一條 pipeline：tool request → input validation → permission check → execute → result / error → back to loop。

> **實作對應**：`tools/permission.py` 作為 tool execution 的 middleware

---

## 5. 系統架構

### 5.1 五層架構

把 agent 系統畫成「使用者 → 模型 → 工具 → 輸出」是一種過度簡化。更合理的理解方式是分成五層：

**第一層：入口層（Entrypoints）**
使用者透過 CLI REPL 或 SDK API 與 engine 互動。入口層只負責把使用者意圖轉成 messages 送進 engine，並消費 engine yield 出來的事件流。同一個 engine，不同的入口——加一個 entrypoint 就是加一層薄包裝。

**第二層：控制面層（Control Plane）**
System prompt assembly、RoleConfig、permission mode。這層定義「系統的行為邊界」，不直接執行任何操作。

**第三層：執行循環層（Query Loop）**
整個系統的心臟。while True 主循環，每一輪做五件事：pre-model governance → call model → post-model processing → tool execution → state transition。所有 context 治理、恢復邏輯都住在這一層。

**第四層：外部能力層（Tools）**
read_file、write_file、edit、bash、grep、agent_tool。每個 tool 遵循統一 protocol，透過 registry 被 engine 發現，經過 permission gate 後才能執行。

**第五層：Context 治理層（Context Governance）**
Token budget 追蹤、autocompact 判斷、compact 執行與 rebuild。這層的職責是確保 context window 永遠處於可工作狀態。

模型不在最上層，也不在最底層。模型只是 query loop 中的一環。真正把系統綁在一起的，是控制面和恢復面。

### 5.2 Query Loop 內部結構

Loop 的每一輪迭代包含以下階段。這個順序本身就是一種架構聲明——它把「上下文治理」放在「模型推理」之前：

**Phase 1 — Pre-Model Governance**
檢查 token budget → 判斷是否觸發 autocompact → 如果需要則壓縮並 rebuild working context → 組裝 system prompt（分層 assembly）

**Phase 2 — Call Model (Streaming)**
把治理後的 messages + system prompt + tool definitions 送給模型 API。模型輸出是一串事件流，不只是最終答案。事件裡可能包含 assistant text、tool_use blocks、usage 更新、stop reason、API 錯誤。

**Phase 3 — Error Detection & Recovery**
判斷模型回應是否觸發了 recoverable error。如果是 prompt-too-long，先嘗試低破壞性的 compact retry；如果是 max-output-tokens，注入續寫訊息讓模型從截斷處繼續；如果是 API error，做 exponential backoff。每種恢復都生成新 State + Transition，`continue` 回到 Phase 1。所有恢復都有 circuit breaker。

**Phase 4 — Tool Execution**
如果模型回應包含 tool_use blocks：依序對每個 tool call 跑 permission gate → execute → collect result。結果以 tool_result messages 的形式 append 到 messages，驅動下一輪。

**Phase 5 — Stop Condition**
如果模型回應不包含 tool_use（即 end_turn），或者達到 max_turns 限制，或者 circuit breaker 觸發，loop 結束。

**State Transition**
每個 `continue` 點都是一個 state transition，帶有明確的 reason（next_turn / reactive_compact_retry / max_output_recovery / api_retry / done / circuit_break）。Loop 不遞歸呼叫自己，而是 `state = new_state; continue`。

### 5.3 Context 治理模型

Context 治理的核心概念是**預算制度**。整個 context window 被切成幾段有明確用途的空間：

**Effective Window** = Context Window − Compact Reserve
模型的 context window（例如 200k tokens）先減去一筆留給 compact 本身的預算。Compact 本身要花 token 做摘要，絕不能把窗口吃到只剩一口氣時才想起求生。

**Autocompact Threshold** = Effective Window − Buffer
在 effective window 上再扣掉一個 buffer（例如 13k tokens）。超過這個閾值就觸發自動壓縮。

**Circuit Breaker**
Autocompact 不是永遠嘗試。如果連續失敗達到上限（例如 3 次），就觸發 circuit breaker 停止嘗試，避免在註定失敗的壓縮上浪費 API calls。

**Compact 不只是摘要**
壓縮不是「把前面聊天摘要一下」。完整的 compact 流程是：strip images/attachments → 呼叫模型做摘要 → 如果摘要自己也 prompt-too-long 就 truncate head retry → 建立 compact boundary → rebuild working context（重新注入必要的 file state、plan、tool delta）。Compact 的目標是重建一個還能繼續工作的語義底座，不是做一條漂亮的 summary。

### 5.4 Tool Execution Pipeline

工具執行不是「模型說調就調」的直通管道。每次 tool call 經過一條 pipeline：

1. **Input Parsing** — 驗證 tool input 是否符合 schema
2. **Permission Gate** — 根據 tool 的 destructive/read-only 屬性和當前 permission mode，決定 allow / deny / ask
3. **Execute** — 呼叫 tool 的 execute 方法，帶入 working directory、abort signal 等 context
4. **Result Collection** — 收集 stdout/stderr 或檔案操作結果，包裝成 tool_result message
5. **Error Handling** — 如果執行失敗，包裝成 is_error=True 的結果回傳給模型，讓模型有機會修正

Permission gate 的三態設計：
- **allow**：read-only 工具（read_file、grep）預設 allow
- **deny**：被明確禁止的操作
- **ask**：destructive 工具（write_file、edit、bash 含寫入指令）需要使用者確認

### 5.5 Multi-Agent 架構

多代理的核心洞察是：**AgentTool 本身就是一個普通的 tool**。當模型在 loop 裡決定 delegate 任務時，它呼叫 agent_tool，agent_tool 內部 spawn 一個新的 engine 實例。這個子 engine：

- 有自己的 LoopState（獨立的 messages、turn count、recovery counters）
- 有自己的 abort controller（父 agent abort 時可以傳播到子 agent）
- 用不同的 RoleConfig（不同的 system prompt sections、allowed tools、max turns）
- 結果以 tool_result 的形式回到父 agent 的 loop

這意味著 coordinator 不需要一個專門的 orchestration 層。它就是「工具列表裡包含 agent_tool 的那個 engine 實例」。它的 prompt 不是在說「你是一個聰明的經理」，而是在說「你的職責是拆解任務、分派給子 agent、綜合結果、不要自己動手做 implementation」。

角色差異完全用 RoleConfig 表達：

| 角色 | Prompt 重點 | 允許的工具 | 特殊限制 |
|------|-----------|----------|---------|
| Coordinator | 拆解、分派、綜合 | read_file, grep, agent_tool | can_spawn_agents=True |
| Implementer | 完成指定 coding 任務 | read_file, write_file, edit, bash, grep | 標準 max_turns |
| Verifier | 獨立驗證，找出問題 | read_file, grep, bash (read-only) | read_only=True |

### 5.6 Verification 架構

Verification 的設計原則是**可插拔策略**。Verifier 本身是一個用 VERIFIER_ROLE spawn 的子 engine，但它的驗證邏輯是策略化的：

**PytestStrategy** — 跑 pytest，解析 exit code 和 output，回傳結構化的 pass/fail 結果。

**LLMReviewStrategy** — 讓 verifier agent 用 read-only 工具集做 code review。Prompt 明確要求「假設程式碼有 bug，你的任務是找到它」，而不是「檢查一下看看有沒有問題」。

**VerificationStrategy Protocol** — 任何新策略只需實作 `verify(context) -> VerifyResult`。未來 3D Generation 專案的 PhysicsValidationStrategy 就是同一個 protocol 的另一個實作。

驗證結果是結構化的：verdict（PASS / FAIL / PARTIAL）+ reason（人類可讀的解釋）+ details（測試輸出、review comments 等額外資訊）。

---

## 6. 實作架構

### 6.1 目錄結構

```
agent-engine/
├── engine/
│   ├── __init__.py
│   ├── loop.py              # async generator 主循環（全專案最重要的檔案）
│   ├── state.py             # LoopState dataclass + Transition + Event types
│   └── recovery.py          # 恢復策略函式（被 loop 呼叫）
│
├── tools/
│   ├── __init__.py
│   ├── base.py              # Tool protocol（name, description, input_schema, execute）
│   ├── registry.py          # 工具註冊 + 依名稱查找
│   ├── permission.py        # allow / deny / ask 三態閘門
│   ├── read_file.py         # 讀取檔案內容
│   ├── write_file.py        # 寫入/建立檔案
│   ├── edit.py              # str_replace 式精確編輯
│   ├── bash.py              # 執行 shell 命令
│   ├── grep.py              # 搜尋檔案內容
│   └── agent_tool.py        # spawn 子 engine（多代理的入口）
│
├── context/
│   ├── __init__.py
│   ├── compact.py           # 摘要壓縮 + rebuild working context
│   ├── budget.py            # token 追蹤 + 閾值判斷 + shouldCompact()
│   └── prompt.py            # system prompt 分層組裝
│
├── roles/
│   ├── __init__.py
│   └── config.py            # RoleConfig dataclass + 預設角色定義
│
├── verify/
│   ├── __init__.py
│   └── verifier.py          # Verification engine + strategies（pytest, llm_review）
│
├── entrypoints/
│   ├── __init__.py
│   ├── cli.py               # 互動式 REPL
│   └── sdk.py               # AgentEngine class（可被其他專案 import）
│
├── main.py                  # python -m agent_engine "task description"
└── pyproject.toml
```

### 6.2 關鍵模組職責

**`engine/state.py`**
定義 `LoopState`（frozen dataclass）、`CompactTracking`、`Transition`，以及所有 Event 類型（TextEvent, ToolUseEvent, ToolResultEvent, CompactEvent, ErrorEvent, DoneEvent）。LoopState 持有 messages、turn_count、compact_tracking、recovery counters、transition reason。每次 state transition 建立新物件，保持不可變。

**`engine/loop.py`**
簽名為 `async def query_loop(...) -> AsyncGenerator[Event, None]`。接收 messages、system_prompt、tools、config、abort_signal。內部是 while True + state object。包含 9 種 transition reason 對應的 continue 點：next_turn、reactive_compact_retry、max_output_recovery、api_retry、stop_hook_retry、abort、circuit_break、max_turns、done。

**`engine/recovery.py`**
提供 `handle_prompt_too_long(state, config) -> LoopState | None`、`handle_max_output_tokens(state, config) -> LoopState | None`、`handle_api_error(error, attempt) -> RetryDecision` 等函式。這些函式負責判斷恢復策略和生成新 state，但 state transition 的決策權留在 loop.py 主體。

**`tools/base.py`**
定義 Tool Protocol：name、description、input_schema（JSON Schema，直接傳給 Anthropic API）、execute(input, context) -> ToolResult、is_read_only()、is_destructive()。以及 ToolResult（content + is_error）、ToolContext（working_dir + abort_signal + permission_gate）。

**`tools/registry.py`**
工具註冊與查找。ToolRegistry 接受 RoleConfig 的 allowed_tools 篩選，支援動態註冊。

**`tools/permission.py`**
PermissionGate class，支援 default / yolo / strict 三種 mode。check(tool, input) 回傳 ALLOW / DENY / ASK。ASK 時在 CLI 模式下等待使用者確認，在 SDK 模式下可透過 callback 處理。

**`context/budget.py`**
TokenBudget class，追蹤 current_input_tokens 和 current_output_tokens（從 API response 的 usage 欄位取得）。提供 should_compact()、is_critical()、effective_window() 等判斷方法。數值設計遵循預算制度：compact_reserve、autocompact_buffer 各有明確用途。

**`context/compact.py`**
compact_conversation() 的完整流程：strip → summarize → handle PTL retry → build boundary → rebuild working context。CompactResult 包含 summary_message、post_compact_messages、token counts。Circuit breaker 限制連續失敗次數。

**`context/prompt.py`**
build_system_prompt(role_config, append_prompt) → str。分層 assembly：identity section + rules section + role-specific sections + optional append。優先級鏈確保新增角色只能疊加領域行為，不能換掉底層紀律。

**`roles/config.py`**
RoleConfig frozen dataclass：name、system_prompt_sections、allowed_tools、read_only、can_spawn_agents、max_turns。預定義 DEFAULT_ROLE、COORDINATOR_ROLE、IMPLEMENTER_ROLE、VERIFIER_ROLE。

**`tools/agent_tool.py`**
AgentTool 的 execute 方法 spawn 新的 engine 實例：根據 role 參數選擇 RoleConfig → 建立獨立 LoopState → 建立子 abort controller（鏈接到父 abort）→ 跑 query_loop → 收集結果回傳為 tool_result。

**`verify/verifier.py`**
定義 VerificationStrategy Protocol（verify(context) -> VerifyResult）。提供 PytestStrategy 和 LLMReviewStrategy 兩個預設實作。VerifyResult 是結構化的判定：verdict + reason + details。Verifier 本身透過 agent_tool 以 VERIFIER_ROLE spawn。

**`entrypoints/cli.py`**
互動式 REPL：readline 介面 → 使用者輸入 → 呼叫 engine.run() → 消費 AsyncGenerator 事件流 → 印出 text、顯示 tool 執行狀態、處理 ask 確認。

**`entrypoints/sdk.py`**
AgentEngine class：接收 RoleConfig、model、working_dir、permission_mode。run(prompt, messages) → AsyncGenerator[Event, None]。可被其他 Python 專案 import 使用。

---

## 7. 技術決策記錄

| 決策 | 選擇 | 理由 |
|------|------|------|
| 語言 | Python | 未來作為 3D Generation 專案的 template，Python 生態更合適 |
| LLM Provider | Anthropic Claude | tool_use schema 與參考設計一致，減少轉譯成本 |
| LLM SDK | anthropic 官方 SDK | 處理 streaming、retry、message format 都已成熟，不造輪子 |
| 預設模型 | claude-sonnet-4（可配置） | Sonnet 性價比最高，Opus 留給 verification 等高要求場景 |
| Loop 結構 | async generator | 事件流式消費，讓系統在模型尚未完成前就能安排下一步 |
| State 管理 | frozen dataclass | 每次 transition 建立新物件，可追蹤可偵錯 |
| Coordinator | RoleConfig 實例 | 多代理是同一引擎的遞歸，角色差異用 config 表達 |
| Recovery 位置 | loop 內嵌 + 輔助函式 | 保持控制流可追蹤，避免跨模組的隱式 state transition |
| Permission | tool pipeline 內嵌 | Permission 是工具執行的一環，不是獨立系統 |
| Verification | 可插拔策略 (Protocol) | 為未來 3D gen 的 physics validation 保留擴展點 |
| Runtime 依賴 | 僅 `anthropic` SDK | 刻意極簡，避免 agent framework 常見的依賴爆炸 |

---

## 8. 實作計畫

### Phase 1：引擎骨架（能對話）

**交付物**：`engine/loop.py`, `engine/state.py`, `context/prompt.py`, `entrypoints/cli.py`, `roles/config.py`

**驗收標準**：
- 在 CLI 中輸入自然語言，模型回應流式輸出到 terminal
- Loop 有明確的 state transition，每輪建立新的 LoopState
- pre_model_governance 有空位（先不做 compact，但介面預留）
- 能多輪對話（模型說完且無 tool_use 時停止）

### Phase 2：工具系統（能動手）

**交付物**：`tools/` 全部檔案（base, registry, permission, read_file, write_file, edit, bash, grep）

**驗收標準**：
- 模型能自主呼叫五種工具完成 coding 任務
- Destructive 操作觸發 ask 確認
- 能完成一個端到端任務（例如「建立一個 hello world FastAPI server」）

### Phase 3：Context 治理與恢復（能長跑）

**交付物**：`context/compact.py`, `context/budget.py`, `engine/recovery.py`

**驗收標準**：
- Token budget 從 API response usage 欄位追蹤
- 超過閾值自動觸發 compact，compact 後 loop 繼續
- prompt-too-long / max-output-tokens / API error 均有分層恢復
- 每種恢復都有 circuit breaker

### Phase 4：Multi-Agent + Verification（能協作）

**交付物**：`tools/agent_tool.py`, `verify/verifier.py`

**驗收標準**：
- Coordinator 能透過 AgentTool 分派子任務
- 子 agent 有獨立 LoopState 和 abort 控制
- Verifier 用 read-only 工具集獨立檢查
- PytestStrategy 和 LLMReviewStrategy 均可工作
- Coordinator 綜合結果後回覆使用者

### Phase 5：SDK 入口 + 收尾（能複用）

**交付物**：`entrypoints/sdk.py`, `main.py`, `pyproject.toml`, README

**驗收標準**：
- AgentEngine class 可被其他 Python 專案 import
- `python -m agent_engine "task"` one-shot 模式可用
- 跑完 demo scenario：使用者下達任務 → coordinator 分派 → implementer 實作 → verifier 驗證 → 回傳結果

---

## 9. 風險與緩解

| 風險 | 影響 | 緩解 |
|------|------|------|
| Compact 摘要品質不佳導致 agent 失去關鍵 context | 長任務失敗率上升 | Compact prompt 加入「保留所有檔案路徑、函式名、未完成步驟」的指令；觀察 compact 前後的行為差異 |
| Multi-agent 子 agent 跑飛（token 消耗失控） | 成本爆炸 | 每個 RoleConfig 有 max_turns 限制；子 agent 的 token budget 獨立追蹤 |
| Verification 的 LLM review 和 implementation 用同一個模型，有 self-confirmation bias | 驗證失效 | Verifier prompt 明確要求「假設程式碼有 bug，你的任務是找到它」；未來可用不同模型 |
| Permission gate 太寬鬆導致檔案被意外覆寫 | 使用者信任降低 | 預設 mode 為 default（destructive 操作要 ask）；bash 工具對 rm、mv 等指令額外標記 destructive |
| Circuit breaker 數值需要調整 | 過早放棄或無限重試 | 先用業界驗證過的數值（compact 3 次、max-output 5 次），觀察後調整 |

---

## 10. 未來擴展路線

本專案作為 template，以下是已預留的擴展點：

| 擴展方向 | 預留機制 | 對應未來專案 |
|----------|----------|------------|
| 3D Generation Agent | RoleConfig 新增 scene_planner / asset_generator / physics_verifier 角色 | 3D Gen Pipeline |
| Physics Validation | VerificationStrategy 新增 PhysicsValidationStrategy | USD scene validation |
| MCP Server 支援 | Tool protocol 可包裝 MCP tool call | 外部工具整合 |
| Web UI | SDK 入口的 async generator 可直接接 WebSocket | 前端介面 |
| 多模型切換 | LoopConfig.model 已可配置 | 成本優化（小任務用便宜模型）|
| Persistent Memory | context/prompt.py 的 section 機制可加入持久化指令 | 長期專案記憶 |

---

## 附錄 A：依賴清單

```toml
[project]
name = "agent-engine"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.52.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.4",
]
```

**只有一個 runtime 依賴**：`anthropic` SDK。刻意保持極簡。

---

*— End of PRD —*
