# HealthFit Advisor

HealthFit Advisor 是一個面向 OpenClaw / Agent 工作流的健康管理技能，提供從建檔、熱量與巨量營養素目標計算、飲食建議、食物影像分析、熱量追蹤、週報評分，到 Phase 7 的快取與隱私工具的一整套本機化流程。

目前版本為 Phase 1–7 工程實作版。它適合單人、自託管、本機 SQLite 場景，但不是醫療器材、不是完整 NIH Body Weight Planner 求解器，也不構成醫療建議。

## 功能概覽

- 單人 profile 建立、更新與本機保存
- BMR / TDEE / 每日熱量與蛋白質、碳水、脂肪目標計算
- 高風險情境標記：未成年、孕期、慢性病、飲食疾患風險
- 外食建議與多輪飲食對話
- 食物照片分析 prompt / parser / 結構化輸出
- 熱量追蹤、每日彙總、歷史比較、最近趨勢
- 每日與每週評分、日報與週報
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
3. 讓 agent 透過 skill 直接呼叫腳本
4. 本機資料會落在：
   - ~/.healthfit/profile.json
   - ~/.healthfit/healthfit.db

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

### 外食 / 菜單建議

    python3 scripts/diet_dialogue.py --cuisine 日式 --location 餐廳 --meal 晚餐 --calories 1800
    python3 scripts/diet_dialogue.py --cuisine any --location 超商 --meal 點心 --remaining-calories 250
    python3 scripts/diet_dialogue.py --cuisine 台式 --location 自助餐 --meal 午餐 --remaining-calories 600 --format json

### 食物分析

查看 FOOD scenario prompt：

    python3 scripts/food_analyzer.py --scenario food --show-prompt

### 熱量追蹤 / 彙總

    python3 scripts/calorie_tracker.py progress --user-id <user_id>
    python3 scripts/calorie_tracker.py trend --user-id <user_id>
    python3 scripts/calorie_tracker.py compare --user-id <user_id>

### 報表與評分

    python3 scripts/scoring_engine.py score --user-id <user_id> --date 2026-05-24
    python3 scripts/report_generator.py daily --user-id <user_id>
    python3 scripts/report_generator.py weekly --user-id <user_id> --week-start 2026-05-18

### Phase 7 快取 / 隱私工具

    python3 scripts/integration_test.py
    python3 scripts/privacy_manager.py preview --user-id <user_id>
    python3 scripts/privacy_manager.py export --user-id <user_id> --output-dir ./exports
    python3 scripts/privacy_manager.py delete --user-id <user_id> --confirm

## Phase 3 → Phase 4 交接規格

Canonical contract：

    references/phase3_output_schema.json

calorie_tracker.py 會透過 normalize_phase3_analysis_payload() 做正規化與驗證。

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
- Weekly meal plan 仍為 template-based，不是最佳化求解
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
