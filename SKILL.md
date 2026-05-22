---
name: healthfit-advisor
description: 提供健康減重、增肌、維持體重的技能化工作流程，適合用在 AI Agent 需要建立個人健康檔案、計算 BMR/TDEE、評估安全減重或增肌速度、產生每日熱量與巨量營養素目標、整理單人健康追蹤資料，或規劃後續飲食/影像辨識模組時使用。當需求包含「減重」「增肌」「熱量」「TDEE」「BMR」「飲食計劃」「體重目標」「巨量營養素」「健康管理 skill」等情境時使用。
---

# HealthFit Advisor

建立以安全性為優先的健康體重管理流程。先完成個人檔案、基礎能量估算與目標安全檢查，再進入飲食建議、影像分析與追蹤報告。

## Core Workflow

1. 先判斷需求屬於哪一類：
   - 新使用者建檔
   - 既有資料的體重目標重算
   - 熱量/巨量營養素快速估算
   - 外食或菜單建議
   - 後續 phase 的規劃或擴充
2. 若是首次使用，先建立或讀取本機單人設定檔 `~/.healthfit/profile.json`。
3. 若需要完整 Phase 1 intake，優先使用 `scripts/intake_flow.py`：
   - 驗證必要欄位
   - 建立或更新 profile
   - 計算安全調整後的 active plan
   - 寫入 SQLite 開發資料庫
4. 用 `scripts/bwp_calculator.py` 計算：
   - BMR
   - TDEE
   - 目標週變化率
   - 每日熱量目標
   - 蛋白質/脂肪/碳水目標
5. 一定執行安全檢查：
   - 每週體重變化是否超過安全範圍
   - 每日熱量是否低於最低安全值
   - 蛋白質是否低於最低建議
   - 是否有未成年、孕期、慢性病或飲食疾患風險
6. 輸出結果時要明示：
   - 這是 Phase 1 的工程近似版，不是假裝完整重現 NIH 線上求解器
   - 若使用者有慢性病、孕期、飲食疾患或未成年，應建議轉專業醫療評估
7. 若需求是「要吃什麼」「外食怎麼選」「超商/自助餐/餐廳建議」，用 `scripts/menu_advisor.py`：
   - 讀取或要求 cuisine/location/meal type
   - 使用 active plan 的 daily calorie target 與 protein target
   - 若已知今日剩餘熱量或已攝取蛋白質，優先用剩餘缺口
   - 輸出主建議、替代選項、避免項目與搭配理由

## Phase 1 Boundaries

- Phase 1 只實作單人模式。
- Phase 1 先用本機檔案與 SQLite-ready schema/abstraction，避免被執行環境是否有 PostgreSQL 阻塞。
- 若執行環境已有 PostgreSQL，可沿用 `scripts/db_schema.sql` 與 `scripts/db_manager.py` 的介面再接上實際後端。
- 不在 Phase 1 直接承諾圖片辨識、菜單 OCR、食品資料庫完整匯入。

## Phase 2 Boundaries

- Phase 2 Round 1 提供 curated menu recommendation，不依賴完整食品資料庫。
- 食物熱量與巨量營養素是工程估算，用於決策輔助，不作為精密營養標示。
- 若使用者提供具體店家或商品營養標示，優先使用使用者提供的數字。
- 還不處理圖片菜單 OCR 或食物照片估算；那些保留給 Phase 3。
- Phase 2 的對話引導樹由 `scripts/diet_dialogue.py` 實作：
  - 自動解析使用者自然語言（支援中英文關鍵字）
  - 支援多輪對話 state 持續（`DialogueState` 物件）
  - 缺少必要欄位時主動詢問，不假設不存在的資訊
  - 完整輸入後直接回傳 recommendation 與 formatted 文字

## Files To Use

- `scripts/bwp_calculator.py`
  - 體重目標與巨量營養素計算核心
- `scripts/profile_manager.py`
  - 單人模式設定檔建立、讀取、更新
- `scripts/db_manager.py`
  - 開發期儲存抽象，預設 SQLite；可初始化 schema、upsert profile、保存/讀取 active plan
- `scripts/intake_flow.py`
  - Phase 1 agent-facing intake procedure，串接 profile、calculator、database
- `scripts/plan_formatter.py`
  - 將 plan payload 轉成可讀摘要，適合用於聊天回覆
- `scripts/menu_advisor.py`
  - Phase 2 飲食諮詢引擎，根據料理類型、用餐地點、餐別與熱量/蛋白缺口推薦外食搭配
- `scripts/diet_dialogue.py`
  - Phase 2 對話引導樹，解析 cuisine/location/meal 自然語言，支援多輪 state 持續
- `scripts/db_schema.sql`
  - Phase 1 schema 草案
- `references/implementation-notes.md`
  - 設計界線、風險與後續 phase 切分

## Working Rules

- 先讀 profile，再讀或建立 active plan。
- 如果輸入缺少年齡、身高、體重、活動量或目標時程，不要硬猜；只補齊必要欄位。
- 人種修正只作可選校正項，不要包裝成高確定性的醫學定論。
- 使用「安全調整後方案」作為預設輸出，並把原始不安全方案列在 warning 中。
- 需要 persistent storage 時，先用 `db_manager.py`，不要把 SQL 散落在各腳本裡。
- 遇到 `requires_professional_review=true` 時，不要把自動熱量目標包裝成醫療建議；輸出需明確建議專業評估。
- Phase 2 menu advice 要明確標示為估算，並提供避免項目與替代選項。

## Validation

- 修改計算或 intake/persistence 邏輯後，執行 `python3 -m unittest discover -s tests -v`
- 修改 skill 結構後，執行 `python3 /home/node/.openclaw/agents/main/agent/codex-home/skills/.system/skill-creator/scripts/quick_validate.py /home/node/.openclaw/workspace/skills/healthfit-advisor`
