# HealthFit Advisor

HealthFit Advisor 是一個面向 OpenClaw / Agent 工作流的健康管理技能，提供從建檔、熱量與巨量營養素目標計算、飲食建議、食物影像分析、熱量追蹤、週報評分，到 Phase 7 的快取與隱私工具的一整套本機化流程。

目前版本為 Phase 1–7 工程實作版。它適合單人、自託管、本機 SQLite 場景，但不是醫療器材、不是完整 NIH Body Weight Planner 求解器，也不構成醫療建議。

## 功能概覽

- 單人 profile 建立、更新與本機保存
- BMR / TDEE / 每日熱量與蛋白質、碳水、脂肪目標計算
- 高風險情境標記：未成年、孕期、慢性病、飲食疾患風險
- 外食建議與多輪飲食對話
- 每日 check-in 問答與自然語言餐次記錄
- 固定時間主動發問的 check-in scheduler / cron
- 食物照片分析 prompt / parser / 結構化輸出
- 熱量追蹤、每日彙總、歷史比較、最近趨勢
- **體重預測曲線視覺化（ASCII）**
- 每日與每週評分、日報與週報
- 連續 2 週停滯偵測、自動重算 active plan 與調整建議
- 運動記錄、GI 指引、月經週期追蹤、健康警示、一週菜單
- 食品資料庫快取
- 個資匯出 / 刪除
- Phase 1–7 smoke test 與單元測試

## 專案結構

    healthfit-advisor/
    ├── SKILL.md
    ├── README.md
    ├── CHANGELOG.md
    ├── examples/
    ├── references/
    ├── scripts/
    └── tests/

Canonical GitHub repo root 為 skills/healthfit-advisor/。
projects/healthfit-advisor/ 只用來放內部開發進度與規劃備忘。

## 系統需求

### 最低需求

- Python 3.10+
- Linux / macOS / WSL
- 可寫入本機檔案系統

### 預設本機路徑

- Profile：~/.healthfit/profile.json
- SQLite DB：~/.healthfit/healthfit.db

### Python 建議安裝方式

    python3 -m venv .venv
    source .venv/bin/activate
    python3 -m pip install --upgrade pip

核心流程目前以標準函式庫為主，沒有重度第三方依賴。

若要使用 meal_planner.py --pdf，需額外安裝 PDF 可選依賴：

    pip install "fpdf2>=2.7"

或用 package metadata：

    pip install .[pdf]

## 安裝方式

### 方式 A：當作本機 Python 專案使用

    git clone <your-github-url> healthfit-advisor
    cd healthfit-advisor
    python3 -m unittest discover -s tests -v

### 方式 B：當作 OpenClaw skill 使用

把整個資料夾放到：

    ~/.openclaw/workspace/skills/healthfit-advisor/

然後確認至少有以下內容：

- SKILL.md
- scripts/
- references/
- tests/

驗證 skill 結構：

    python3 /home/node/.openclaw/agents/main/agent/codex-home/skills/.system/skill-creator/scripts/quick_validate.py .

## 部署指南

### 1. 本機單機部署

這是目前最推薦的部署方式。

1. Clone repo
2. 進入 skills/healthfit-advisor/
3. 跑測試確認環境正常
4. 直接執行 scripts/*.py

建議先跑：

    python3 -m py_compile scripts/*.py tests/*.py
    python3 -m unittest discover -s tests -v
    python3 scripts/integration_test.py

### 2. 與 OpenClaw 一起部署

若要掛到 OpenClaw workspace：

1. 把 repo 放到 ~/.openclaw/workspace/skills/healthfit-advisor/
2. 保持 SKILL.md 與 scripts/ 在 skill root
3. 讓 agent 優先透過統一入口 scripts/healthfit.py 呼叫功能
4. 本機資料會落在：
   - ~/.healthfit/profile.json
   - ~/.healthfit/healthfit.db

### Agent manifests

agents/ 目前分為三份 manifest，避免不同平台共用一個名稱不清的檔案：

- agents/openclaw.yaml: OpenClaw routing metadata
- agents/hermes.yaml: Hermes intent manifest
- agents/openai.yaml: OpenAI Assistants / Responses description

三者都統一指向：

    python3 scripts/healthfit.py

### 3. Docker / NAS / 自託管部署建議

若你在 Synology / Docker / NAS 環境使用，建議：

- 把 repo mount 到固定路徑
- 把 ~/.healthfit/ 掛成 persistent volume
- 避免容器重建時遺失 profile.json 與 healthfit.db

範例 volume 規劃：

    /volume1/docker/openclaw/workspace/skills/healthfit-advisor -> repo
    /volume1/docker/openclaw/data/healthfit                    -> ~/.healthfit

### 4. PostgreSQL 切換說明

目前不支援直接把 SQLite backend 切成 PostgreSQL。

原因：

- scripts/db_manager.py 目前是 SQLite-specific implementation
- 內含 PRAGMA、SQLite DDL、SQLite UPSERT 假設
- 若要切 PostgreSQL，應新增 adapter 或 ORM 層，而不是直接換連線字串

目前正式支援的是本機 SQLite。

## 初始化流程

### Step 1：跑 intake 建檔

最小 payload 範例：

    {
      "display_name": "Henry",
      "gender": "M",
      "age": 30,
      "height_cm": 170,
      "current_weight_kg": 85,
      "activity_level": "light",
      "goal_weight_kg": 78,
      "target_weeks": 16
    }

只計算、不寫入：

    python3 scripts/intake_flow.py examples/intake_payload.json --no-persist

寫入 profile、active plan、初始體重：

    python3 scripts/intake_flow.py examples/intake_payload.json

這會同步建立或更新：

- profile.json
- users
- weight_plans
- weight_logs

### Step 2：格式化輸出

    python3 scripts/plan_formatter.py result.json

## 常用操作

### 統一 CLI 入口

建議優先使用單一入口，而不是直接記每個 phase 腳本名稱：

    python3 scripts/healthfit.py intake examples/intake_payload.json
    python3 scripts/healthfit.py log meal <meal_payload.json> --user-id <user_id> --meal-type lunch
    python3 scripts/healthfit.py log from-image <phase3_response.json> --user-id <user_id> --meal-type lunch
    python3 scripts/healthfit.py image prompt --user-id <user_id> --meal-type dinner --remaining-calories 800 --protein-gap 30
    python3 scripts/healthfit.py checkin prompt --meal-type lunch --user-id <user_id>
    python3 scripts/healthfit.py checkin answer --user-id <user_id> --meal-type lunch --text "雞胸肉150g、茶葉蛋、無糖豆漿"
    python3 scripts/healthfit.py notify checkin --meal-type lunch --channels print
    python3 scripts/healthfit.py report daily --user-id <user_id>
    python3 scripts/healthfit.py report weekly --user-id <user_id> --week-start 2026-05-19
    python3 scripts/healthfit.py chart --user-id <user_id> --weeks 12
    python3 scripts/healthfit.py plan --cuisine 台式 --meal-preference balanced
    python3 scripts/healthfit.py gi classify --food "白米飯"
    python3 scripts/healthfit.py alert check --json

這層 wrapper 目前是 thin dispatcher，不重寫原有 phase script 邏輯；目的是讓 CLI、agent manifest、文件三者共享同一個穩定入口。

Feature F 已經可以直接透過統一 CLI 使用：

    python3 scripts/healthfit.py can-eat "一碗拉麵" --meal lunch --user-id <user_id>
    python3 scripts/healthfit.py can-eat "珍奶" --quantity 2 --user-id <user_id>
    python3 scripts/healthfit.py can-eat "兩個便當" --json --user-id <user_id>

原理：串接 `get_calorie_progress()`（今日剩餘熱量）+ `FoodDBLookup.search()`（食物熱量查詢）+ `food_preference_engine`（替代選項），根據 `daily_target` 與 `goal_type` 動態給出「yes / yes_with_caveat / marginal / no」判斷與調整建議。

### 體重預測視覺化（ASCII Chart）

檢視體重預測曲線與實際記錄的對照圖：

```bash
# 顯示近 12 週的體重趨勢
python3 scripts/healthfit.py chart --user-id <user_id> --weeks 12

# 自訂日期範圍與圖表尺寸
python3 scripts/healthfit.py chart --user-id <user_id> --from-date 2026-05-01 --to-date 2026-05-29 --width 60 --height 15
```

Chart 符號說明：

| 符號 | 意義 |
|------|------|
| `·` | 預測曲線（BWPCalculator 或線性插值） |
| `●` | 實際體重記錄（weight_logs） |
| `━` | 目標體重水平線 |

進度狀態說明：
- **如期進行 ✅**：實際體重偏離預測值 < 0.3 kg
- **超前 N 天 ✅**：實際體重比預測值低（減重）/ 高（增肌）N 天以上
- **落後 N 天 ⚠️**：落後於預測進度

> 週報（`report weekly`）會自動在「⚖️ 體重變化」區塊後嵌入 ASCII chart，無需額外參數。

---

### 外食 / 菜單建議

    python3 scripts/diet_dialogue.py --cuisine 日式 --location 餐廳 --meal 晚餐 --calories 1800
    python3 scripts/diet_dialogue.py --cuisine any --location 超商 --meal 點心 --remaining-calories 250
    python3 scripts/diet_dialogue.py --cuisine 台式 --location 自助餐 --meal 午餐 --remaining-calories 600 --format json

### 每日 check-in 問答

先產生 agent 要問的句子：

    python3 scripts/healthfit.py checkin prompt --meal-type lunch --user-id <user_id>

使用者自然語言回答後，直接解析並落庫：

    python3 scripts/healthfit.py checkin answer --user-id <user_id> --meal-type lunch --text "雞胸肉150g、茶葉蛋、無糖豆漿"

若要直接測 diet_dialogue.py 的 check-in 膠水層：

    python3 scripts/diet_dialogue.py --checkin-text "今天午餐吃了雞胸肉150g、茶葉蛋和無糖豆漿" --user-id <user_id> --meal lunch --format json

### 固定時間主動發問

Scheduler 入口：

    python3 scripts/healthfit.py notify checkin --meal-type lunch --channels print

這會產生並送出：

    今天午餐吃了什麼？

同時附帶建議的回覆落庫命令。若要印出建議 cron：

    python3 scripts/healthfit.py notify setup-cron

目前 `setup-cron` 會包含：

- 每天 13:00 午餐 check-in
- 每天 22:30 日報
- 每週日 21:00 週報

### 食物分析

查看 FOOD scenario prompt：

    python3 scripts/food_analyzer.py --scenario food --show-prompt
    python3 scripts/healthfit.py log from-image <phase3_response.json> --user-id <user_id> --meal-type dinner --print-analysis
    python3 scripts/healthfit.py log from-image - --user-id <user_id> --save-raw-response phase3_response.json < raw_phase3_reply.json

Agent/skill 一條龍建議流程：

1. 收到圖片後，先跑：

       python3 scripts/healthfit.py image prompt --user-id <user_id> --meal-type dinner --remaining-calories 800 --protein-gap 30

2. 把輸出的 `system_prompt` + `user_prompt` 與圖片一起送進多模態模型，要求只回傳 JSON。
3. 將原始 JSON 回覆存成 `phase3_response.json`。
4. 立刻執行輸出的 `next_command`，或直接用 stdin 版本：

       python3 scripts/healthfit.py log from-image - --user-id <user_id> --meal-type dinner --save-raw-response phase3_response.json

### 熱量追蹤 / 彙總

    python3 scripts/calorie_tracker.py progress --user-id <user_id>
    python3 scripts/calorie_tracker.py trend --user-id <user_id>
    python3 scripts/calorie_tracker.py compare --user-id <user_id>

### GI 分類與複合料理自動估算

基礎分類（靜態 GI DB + TW_FDA proxy + 可選 LLM fallback）：

    python3 scripts/gi_guide.py classify --food "炸雞排"

若已設定 GI 專用 LLM 環境變數，複合料理會在靜態 DB / TW_FDA 都 miss 時，自動走 LLM 估算並快取 30 天：

    export HEALTHFIT_GI_MODEL=gpt-4.1-mini
    export HEALTHFIT_GI_API_KEY=<your_api_key>
    python3 scripts/gi_guide.py classify --food "鹹水雞"

若要明確停用資料庫或 LLM fallback：

    python3 scripts/gi_guide.py classify --food "鹹水雞" --no-llm
    python3 scripts/gi_guide.py classify --food "鹹水雞" --no-db

GI LLM 快取 TTL 比對已改成 timezone-aware UTC timestamp，避免 datetime.utcnow() 在 Python 3.12+ 的棄用警告與後續移除問題。

### 報表與評分

    python3 scripts/scoring_engine.py score --user-id <user_id> --date 2026-05-24
    python3 scripts/report_generator.py daily --user-id <user_id>
    python3 scripts/report_generator.py weekly --user-id <user_id> --week-start 2026-05-18

### Phase 7 快取 / 隱私工具

    python3 scripts/integration_test.py
    python3 scripts/privacy_manager.py preview --user-id <user_id>
    python3 scripts/privacy_manager.py export --user-id <user_id> --output-dir ./exports
    python3 scripts/privacy_manager.py delete --user-id <user_id> --confirm

### 一週飲食計劃最佳化

預設 CLI 會在可讀到 `profile.user_id` 與 SQLite DB 時，優先嘗試 LLM 最佳化版；若模型未設定、輸出驗證失敗或重試後仍不合格，會自動 fallback 到既有 template 版本。

直接產生計劃：

    python3 scripts/meal_planner.py plan --cuisine 台式 --meal-preference balanced

加入飲食限制：

    python3 scripts/meal_planner.py plan --cuisine 日式 --restrictions "vegetarian,no_shellfish"

強制使用舊版 template：

    python3 scripts/meal_planner.py plan --template-only

若要把本週計劃寫入 SQLite：

    python3 scripts/meal_planner.py plan --persist

若要匯出 PDF：

    python3 scripts/meal_planner.py plan --pdf --output meal_plan.pdf

PDF 匯出注意事項：

- fpdf2 是 optional dependency，不是 core install 的一部分。
- 需有可讀取的 CJK 字型；可安裝 fonts-wqy-zenhei / noto-cjk，或指定 HEALTHFIT_PDF_FONT=/path/to/font.ttf
- 產出前會移除 emoji 等常見字型缺字符號，避免 PDF 內出現空方塊或直接拋錯。

## Phase 3 → Phase 4 交接規格

Canonical contract：

    references/phase3_output_schema.json

calorie_tracker.py 會透過 normalize_phase3_analysis_payload() 做正規化與驗證。
如果要把食物照片分析結果直接落庫，優先走 `python3 scripts/healthfit.py image prompt ...` + `python3 scripts/healthfit.py log from-image ...` 這條正式路徑；前者處理 agent/skill 收圖時的 prompt 與 `phase3_response.json` handoff，後者完成 Phase 3 parsing 與 Phase 4 logging。

如果是每日主動問答情境，優先走 `python3 scripts/healthfit.py checkin prompt ...` + `python3 scripts/healthfit.py checkin answer ...`；後者會把自然語言回答解析成手動餐次記錄，直接寫入 `food_logs` 並更新當日 summary。

如果要固定時間自動詢問，則走 `python3 scripts/healthfit.py notify checkin ...`，並用 `notify setup-cron` 產出 cron。這條會重用同一個 check-in 問句與 handoff 命令，不另外分叉資料流。

### 停滯期偵測 + 自動計劃調整

`health_alerts.py` 現在不只會提醒停滯，還會在以下條件成立時自動重算並寫入新的 active plan：

- 目前 active plan 是 `loss`
- 連續 2 週體重變化 < 0.3 kg
- 最近 14 天內還沒有做過一次停滯期自動調整

自動調整邏輯：

- 先用 `bwp_dynamic_solver.py` 以「目前體重、原目標體重、剩餘週數」重算
- 若仍高於安全下限，將每日熱量目標再減 `100 kcal`
- 若已接近安全下限，改成保留熱量目標並建議「每週增加 1 天運動」
- 新計劃會寫入 `weight_plans`，並切換為新的 `active plan`

執行方式：

    python3 scripts/healthfit.py alert check --json

目前已修正的重要點：

- food_analyzer.py 會保留每樣食物自己的 calories / protein_g / carb_g / fat_g 等欄位
- MealAnalysisResult.to_dict() 不再遺失單品營養欄位
- Phase 3 -> Phase 4 真實 roundtrip 已有測試覆蓋

## 通知與環境變數

若要啟用 scripts/notification_scheduler.py 的外部通知：

必填：

- DISCORD_WEBHOOK_URL
- LINE_CHANNEL_ACCESS_TOKEN
- LINE_REPORT_TARGET

選填：

- HEALTHFIT_CHANNELS
- HEALTHFIT_DRY_RUN=1
- HEALTHFIT_DB_PATH
- HEALTHFIT_PROFILE

若要啟用 `scripts/gi_guide.py` 的複合料理 LLM GI 估算：

- `HEALTHFIT_GI_MODEL`
- `HEALTHFIT_GI_API_KEY` 或沿用 `OPENAI_API_KEY`
- optional `HEALTHFIT_GI_API_URL`
- optional `HEALTHFIT_GI_TIMEOUT_SECONDS`

預設使用 OpenAI 相容的 Chat Completions API：

    https://api.openai.com/v1/chat/completions

`gi_guide.py` 的 LLM fallback 只會在以下情況觸發：

1. 靜態 GI DB 找不到
2. `TW_FDA` proxy 沒命中或信心不足
3. 有提供 GI LLM 環境變數

成功估算後，結果會以 `source='GI_LLM'` 存入 `food_nutrition_cache`，TTL 為 30 天，避免重複呼叫模型。

若要啟用 `scripts/meal_planner.py` 的最佳化週計劃：

- `HEALTHFIT_MEAL_PLAN_MODEL`
- `HEALTHFIT_MEAL_PLAN_API_KEY` 或沿用 `OPENAI_API_KEY`
- optional `HEALTHFIT_MEAL_PLAN_API_URL`
- optional `HEALTHFIT_MEAL_PLAN_TIMEOUT_SECONDS`

`meal_planner.py` 的 LLM 版會做 Python 驗證：

1. 每日總熱量需在目標 ±5% 內
2. 每日蛋白質需達目標的 85% 以上
3. 同一道菜 7 天內不可超過 2 次
4. 若不合格，會帶違規原因重試；仍失敗則 fallback 到 template

注意：

- smoke test 不會真的送出外部通知
- 缺少通知憑證時，應在 delivery 階段明確失敗

## 安全邊界

- 這是工程化健康管理工具，不是醫療診斷系統
- 若 requires_professional_review = true，不可把輸出包裝成醫療建議
- 慢性病、孕期、未成年、飲食疾患風險情境，應升級為專業評估

## 已知限制

- 單人模式優先，尚未完成多使用者授權
- SQLite 為主，PostgreSQL 尚未抽象完成
- Meal planner 現在支援 LLM 最佳化求解，但仍保留 template fallback；若未設定模型或驗證失敗，會退回 template 版
- GI 資料庫只覆蓋常見台灣食品，未知食品會回 explicit fallback
- 週評分若無體重資料，會自動重分配權重，不再默默扣分

## 驗證命令

完整驗證建議：

    python3 -m py_compile scripts/*.py tests/*.py
    python3 -m unittest discover -s tests -v
    python3 scripts/integration_test.py
    python3 /home/node/.openclaw/agents/main/agent/codex-home/skills/.system/skill-creator/scripts/quick_validate.py .

若只驗證關鍵模組：

    python3 -m unittest -v tests.test_intake_flow
    python3 -m unittest -v tests.test_calorie_tracker
    python3 -m unittest -v tests.test_scoring_engine
    python3 -m unittest -v tests.test_report_generator

## 維護文件

- SKILL.md
- CHANGELOG.md
- references/implementation-notes.md
- references/phase3_output_schema.json
- references/exercise_eat_back_policy.md
- projects/healthfit-advisor/PHASE_PROGRESS.md

## 版本說明

目前倉庫包含：

- Phase 1：建檔、BMR/TDEE、active plan、SQLite
- Phase 2：外食與對話式飲食建議
- Phase 3：Vision-agnostic food analysis
- Phase 4：熱量追蹤、daily summary、history comparison
- Phase 5：daily/weekly scoring + report generation
- Phase 6：exercise / GI / cycle / alerts / meal planner / notification
- Phase 7：cache / privacy / integration smoke test

## License

See LICENSE.
