# HealthFit Advisor

HealthFit Advisor 是一個面向 OpenClaw / agent 工作流的健康管理 skill。它把建檔、熱量目標、飲食記錄、照片分析、體重追蹤、週報、提醒、菜單與採購清單整合在同一套本機化流程裡。

它適合單人、自託管、SQLite 場景。它不是醫療器材，也不構成醫療建議。

## 功能概覽

- 建立與更新單人 profile
- BMR / TDEE / 每日熱量與巨量營養素目標計算
- 每日 check-in、自然語言餐次記錄、照片分析 handoff
- 熱量追蹤、歷史比較、近期趨勢
- 體重預測與 ASCII chart 對照
- 每日與每週評分、日報與週報
- 外食建議、GI 指引、運動記錄、月經週期追蹤、健康警示
- 每週菜單與採購清單
- 隱私匯出 / 刪除工具

## 推薦使用方式

正式入口建議用 **skill / agent**，不是直接記一堆 phase 腳本。

原因很簡單：

- 對使用者最容易，直接跟 agent 對話即可
- 對維護最穩，agent、CLI、文件都能共享 `python3 scripts/healthfit.py` 這個統一入口
- 之後若要接 cron / Docker，也可以繼續沿用同一組命令

CLI 仍然是重要的備援與除錯入口，但不建議把它當主要人機介面。

## 架構

核心元件如下：

- `SKILL.md`：給 OpenClaw / agent 的 skill 說明
- `scripts/healthfit.py`：統一 CLI dispatcher
- `scripts/`：各功能模組
- `tests/`：單元測試與 smoke test
- `~/.healthfit/profile.json`：單人 profile 預設路徑
- `~/.healthfit/healthfit.db`：SQLite DB 預設路徑

目前資料層是 SQLite-first 設計。正式支援的是本機 SQLite，不是 PostgreSQL。

## 預設路徑與資料檔

如果你什麼都不設，HealthFit 會自動使用：

- Profile：`~/.healthfit/profile.json`
- DB：`~/.healthfit/healthfit.db`

這代表大多數單人使用情境下，你 **不需要手動設定** `HEALTHFIT_PROFILE` 或 `HEALTHFIT_DB_PATH`。

只有在以下情況才建議自訂：

- 你要把資料掛到 NAS / Docker volume 的固定路徑
- 你要區分正式資料與測試資料
- 你要替不同環境切不同 profile / DB

## 時區策略

目前預設策略是：

- NAS / 系統層可維持 `UTC`
- HealthFit 的業務日期邊界預設使用 `Asia/Taipei`
- 資料庫事件時間戳維持 `UTC` 儲存

也就是說，「今天 / 本週 / 排程日期」這些業務邏輯預設看台灣時間；但底層 log timestamp 仍維持 UTC，避免後續整合出現時區混亂。

若你要覆寫預設時區：

```bash
export HEALTHFIT_TIMEZONE=Asia/Taipei
```

## 安裝

### Python 環境

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

這會安裝 **正式營運預設需要的 core 依賴**。

### PDF 可選依賴

`fpdf2` 是 **可選依賴**，不是 core install 的一部分。

- 如果你只需要文字、ASCII chart、日報、週報：不需要它
- 如果你要 `meal_planner.py --pdf` 之類的 PDF 輸出：需要它

安裝方式有兩種，擇一即可：

```bash
python3 -m pip install -r requirements-pdf.txt
```

或：

```bash
python3 -m pip install "fpdf2>=2.7"
```

若你是用 package metadata 安裝，也可以：

```bash
python3 -m pip install ".[pdf]"
```

另外若要正常輸出中文 PDF，還需要可讀取的 CJK 字型，例如 `Noto CJK` 或 `WenQuanYi Zen Hei`。

## 部署方式

### 1. Skill 模式

最推薦的正式入口。

把 repo 放在：

```text
~/.openclaw/workspace/skills/healthfit-advisor/
```

至少需要：

- `SKILL.md`
- `scripts/`
- `references/`
- `tests/`

驗證 skill 結構：

```bash
python3 /home/node/.openclaw/agents/main/agent/codex-home/skills/.system/skill-creator/scripts/quick_validate.py .
```

### 2. CLI 模式

適合本機除錯、腳本化、手動驗證。

建議統一走：

```bash
python3 scripts/healthfit.py ...
```

而不是直接記每個 phase 腳本。

### 3. Cron 模式

適合固定時間觸發 daily / weekly report 或 check-in。

重點不是 cron 自己，而是 **先把環境變數固定好**，再用同一個 CLI 入口執行。

### 4. Docker / NAS 模式

適合長期自託管。

建議：

- repo 掛固定路徑
- `~/.healthfit/` 掛 persistent volume
- OpenClaw service 啟動時就把 HealthFit 相關 env 帶進去

範例 volume 規劃：

```text
/volume1/docker/openclaw/workspace/skills/healthfit-advisor -> repo
/volume1/docker/openclaw/data/healthfit                    -> ~/.healthfit
```

## 環境變數

### 核心原則

skill 模式下，最穩的設定順序是：

1. **OpenClaw service / container env**
2. `/home/node/.openclaw/openclaw.json` 的 channel 設定
3. 臨時 shell `export`

目前程式碼 **會讀環境變數，但不會自動讀 `.env` 檔**。

所以如果你想把設定「存成 env」，建議放在真正的啟動層：

- OpenClaw / Docker service 的 `environment:`
- shell / wrapper script 的 `export`
- cron 腳本前段的 `export`

對 `notification_scheduler.py` 來說：

- `LINE` 送訊若沒設 env，會 fallback 讀 `/home/node/.openclaw/openclaw.json`
- `Discord` 若沒設 `DISCORD_WEBHOOK_URL`，會嘗試用 `openclaw.json` 內的 bot token + allowFrom 做 DM fallback

也就是說，**如果 OpenClaw 的 Discord / LINE 本來就已經配好，HealthFit 多半不需要再維護第二份 delivery secret**。

### 通知相關

若要真的送外部通知：

- `DISCORD_WEBHOOK_URL`
- `DISCORD_REPORT_TARGET`
- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_REPORT_TARGET`

選填：

- `HEALTHFIT_CHANNELS`
- `HEALTHFIT_DRY_RUN`
- `HEALTHFIT_DB_PATH`
- `HEALTHFIT_PROFILE`
- `HEALTHFIT_TIMEZONE`

### LLM 加值功能

GI 複合料理估算可選：

- `HEALTHFIT_GI_MODEL`
- `HEALTHFIT_GI_API_KEY` 或 `OPENAI_API_KEY`
- optional `HEALTHFIT_GI_API_URL`
- optional `HEALTHFIT_GI_TIMEOUT_SECONDS`

Meal planner 最佳化可選：

- `HEALTHFIT_MEAL_PLAN_MODEL`
- `HEALTHFIT_MEAL_PLAN_API_KEY` 或 `OPENAI_API_KEY`
- optional `HEALTHFIT_MEAL_PLAN_API_URL`
- optional `HEALTHFIT_MEAL_PLAN_TIMEOUT_SECONDS`

## 首次初始化

### 1. 建檔

最小 payload 範例：

```json
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
```

執行：

```bash
python3 scripts/healthfit.py intake examples/intake_payload.json
```

這會建立或更新：

- `profile.json`
- `users`
- `weight_plans`
- `weight_logs`

### 2. 匯入食品資料

首次啟動建議執行一次：

```bash
python3 scripts/bootstrap_food_db.py
python3 scripts/food_db_status.py
```

## 常用操作

### Check-in prompt / answer

```bash
python3 scripts/healthfit.py checkin prompt --meal-type lunch --user-id <user_id>
python3 scripts/healthfit.py checkin answer --user-id <user_id> --meal-type lunch --text "雞胸肉150g、茶葉蛋、無糖豆漿"
```

### Daily / weekly report

```bash
python3 scripts/healthfit.py report daily --user-id <user_id>
python3 scripts/healthfit.py report weekly --user-id <user_id> --week-start 2026-05-19
```

### Notify / cron helper

```bash
python3 scripts/notification_scheduler.py checkin --meal-type lunch -c print
python3 scripts/notification_scheduler.py daily -c print
python3 scripts/notification_scheduler.py weekly -c print
python3 scripts/notification_scheduler.py setup-cron
```

### Meal plan / shopping

```bash
python3 scripts/healthfit.py plan --cuisine 台式 --meal-preference balanced
python3 scripts/meal_planner.py plan --persist
python3 scripts/meal_planner.py plan --pdf --output meal_plan.pdf
```

### GI / can-eat / chart

```bash
python3 scripts/healthfit.py gi classify --food "白米飯"
python3 scripts/healthfit.py can-eat "一碗拉麵" --meal lunch --user-id <user_id>
python3 scripts/healthfit.py chart --user-id <user_id> --weeks 12
```

## 上線前檢查清單

- Skill 目錄已放對
- `python3 -m pip install -r requirements.txt` 已完成
- 若需要 PDF，已額外安裝 `python3 -m pip install -r requirements-pdf.txt` 或 `python3 -m pip install ".[pdf]"`
- 已完成 intake，`~/.healthfit/profile.json` 與 `~/.healthfit/healthfit.db` 已建立
- 若要外部通知，delivery env 已設好
- 已至少做一次 dry-run smoke test
- 若要正式發送，已做一次真實 delivery smoke test

## 驗證命令

完整驗證：

```bash
python3 -m py_compile scripts/*.py tests/*.py
python3 -m unittest discover -s tests -v
python3 scripts/integration_test.py
python3 /home/node/.openclaw/agents/main/agent/codex-home/skills/.system/skill-creator/scripts/quick_validate.py .
```

若只驗證通知與時區相關：

```bash
python3 -m unittest tests.test_notification_scheduler tests.test_shopping_push -v
python3 scripts/notification_scheduler.py checkin --help
```

## 安全邊界

- 這是工程化健康管理工具，不是醫療診斷系統
- 若 `requires_professional_review = true`，不可包裝成醫療建議
- 慢性病、孕期、未成年、飲食疾患風險情境，應轉專業評估

## 已知限制

- 單人模式優先
- SQLite 為正式支援資料層
- PostgreSQL 尚未抽象完成
- PDF、GI LLM、meal-plan LLM 都屬於可選能力，不是 core install 一部分

## 變更紀錄

開發過程、phase 歷史與修補細節請看：

- `CHANGELOG.md`

## License

See `LICENSE`.
