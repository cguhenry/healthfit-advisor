CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    display_name VARCHAR(50),
    gender CHAR(1),
    age INTEGER,
    birth_year INTEGER,
    height_cm NUMERIC,
    ethnicity VARCHAR(20) DEFAULT 'east_asian',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS weight_plans (
    plan_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT REFERENCES users(user_id),
    start_weight_kg NUMERIC,
    goal_weight_kg NUMERIC,
    target_weeks INTEGER,
    weekly_change_kg NUMERIC,
    weekly_change_pct NUMERIC,
    bmr INTEGER,
    tdee INTEGER,
    activity_level VARCHAR(20),
    daily_calorie_target INTEGER,
    daily_calorie_delta INTEGER,
    protein_target_g INTEGER,
    carb_target_g INTEGER,
    fat_target_g INTEGER,
    target_date DATE,
    goal_type VARCHAR(10),
    warnings TEXT,
    dietary_restrictions TEXT DEFAULT '[]',
    trajectory_json TEXT,
    plan_start_date DATE,
    is_plateau_adjustment INTEGER DEFAULT 0,
    requires_professional_review BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS weight_logs (
    log_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT REFERENCES users(user_id),
    log_date DATE NOT NULL,
    weight_kg NUMERIC,
    body_fat_pct NUMERIC,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS food_logs (
    log_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT REFERENCES users(user_id),
    meal_type VARCHAR(10),
    log_datetime TIMESTAMP NOT NULL,
    food_name VARCHAR(100),
    food_db_source VARCHAR(10),
    food_db_id VARCHAR(50),
    quantity_g NUMERIC,
    calories NUMERIC,
    protein_g NUMERIC,
    carb_g NUMERIC,
    fat_g NUMERIC,
    fiber_g NUMERIC,
    sodium_mg NUMERIC,
    ai_confidence NUMERIC,
    note TEXT,
    quality_label TEXT
);

CREATE TABLE IF NOT EXISTS daily_summaries (
    summary_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT REFERENCES users(user_id),
    summary_date DATE NOT NULL,
    total_calories NUMERIC,
    total_protein_g NUMERIC,
    total_carb_g NUMERIC,
    total_fat_g NUMERIC,
    calorie_target INTEGER,
    calorie_balance NUMERIC,
    daily_score INTEGER,
    score_breakdown TEXT,
    UNIQUE(user_id, summary_date)
);

CREATE TABLE IF NOT EXISTS weekly_summaries (
    summary_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT REFERENCES users(user_id),
    week_start_date DATE NOT NULL,
    avg_daily_calories NUMERIC,
    goal_adherence_pct NUMERIC,
    weekly_score INTEGER,
    weight_change_kg NUMERIC,
    report_text TEXT,
    UNIQUE(user_id, week_start_date)
);

CREATE TABLE IF NOT EXISTS weekly_meal_plans (
    plan_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT REFERENCES users(user_id),
    week_start_date DATE NOT NULL,
    cuisine VARCHAR(20),
    meal_preference VARCHAR(20),
    source VARCHAR(20) DEFAULT 'template',
    plan_json TEXT NOT NULL,
    shopping_list_json TEXT,
    summary_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, week_start_date, source)
);

CREATE TABLE IF NOT EXISTS score_events (
    event_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT REFERENCES users(user_id),
    event_date DATE,
    event_type VARCHAR(30),
    points INTEGER,
    description TEXT
);

-- Phase 6: 台灣FDA + USDA 食品營養資料庫快取
CREATE TABLE IF NOT EXISTS food_nutrition_cache (
    cache_id       TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    source         VARCHAR(10)     NOT NULL,          -- 'TW_FDA' | 'USDA' | 'GI_LLM'
    food_id        VARCHAR(50)     NOT NULL,          -- 整合編號 或 USDA fdcId
    food_name      VARCHAR(200)    NOT NULL,
    food_name_en   VARCHAR(200),
    category       VARCHAR(100),                     -- 食品分類
    calories_100g  NUMERIC(7,1),                     -- 每100g熱量 (kcal)
    protein_100g   NUMERIC(6,1),                     -- 每100g蛋白質 (g)
    carb_100g      NUMERIC(6,1),                     -- 每100g碳水 (g)
    fat_100g       NUMERIC(6,1),                     -- 每100g脂肪 (g)
    fiber_100g     NUMERIC(6,1),                     -- 每100g膳食纖維 (g)
    sodium_100g    NUMERIC(7,1),                     -- 每100g鈉 (mg)
    serving_size_g NUMERIC(7,1),                     -- 建議份量 (g)
    raw_json       TEXT,                             -- 原始回應 (除錯用)
    fetched_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, food_id)
);

CREATE INDEX IF NOT EXISTS idx_food_cache_name  ON food_nutrition_cache(food_name);
CREATE INDEX IF NOT EXISTS idx_food_cache_source ON food_nutrition_cache(source);
CREATE INDEX IF NOT EXISTS idx_food_cache_category ON food_nutrition_cache(category);

-- Phase 6: 運動記錄
CREATE TABLE IF NOT EXISTS exercise_logs (
    log_id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id         TEXT REFERENCES users(user_id),
    log_date        DATE NOT NULL,
    exercise_type   VARCHAR(30)     NOT NULL,  -- 'cardio' | 'strength' | 'hiit' | 'yoga' | 'other'
    activity_name   VARCHAR(100),
    duration_min    INTEGER,
    intensity       VARCHAR(10),               -- 'light' | 'moderate' | 'vigorous'
    calories_burned NUMERIC(7,1),
    note            TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, log_date, activity_name)
);

-- Phase 6: 動態熱量配額（運動後調整）
CREATE TABLE IF NOT EXISTS daily_calorie_ledger (
    ledger_id       TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id         TEXT REFERENCES users(user_id),
    ledger_date     DATE NOT NULL,
    base_target     INTEGER,                   -- 原始每日目標（来自 weight_plans）
    exercise_cal    INTEGER DEFAULT 0,         -- 運動消耗熱量
    adjusted_target INTEGER,                   -- base_target + exercise_cal
    UNIQUE(user_id, ledger_date)
);

-- Phase 6: 月經週期追蹤（使用者自填）
CREATE TABLE IF NOT EXISTS menstrual_logs (
    log_id      TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id     TEXT REFERENCES users(user_id),
    period_start DATE NOT NULL,
    cycle_length INTEGER,                      -- 天數（用於計算下次預估）
    note        TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, period_start)
);

-- Phase 6: 健康警示日誌
CREATE TABLE IF NOT EXISTS health_alerts (
    alert_id    TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id     TEXT REFERENCES users(user_id),
    alert_type  VARCHAR(50)     NOT NULL,   -- 'low_calorie_3day' | 'rapid_weight_loss' | 'protein_deficiency' | 'missing_log_5day'
    severity    VARCHAR(10)     NOT NULL,  -- 'info' | 'warning' | 'critical'
    message     TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    acknowledged BOOLEAN DEFAULT FALSE
);

-- Phase 6: 食物偏好學習（Food Fingerprint）
-- 每筆食物記錄寫入後非同步更新，不影響主流程
CREATE TABLE IF NOT EXISTS food_preference_profile (
    profile_id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id                 TEXT REFERENCES users(user_id),
    food_name               TEXT NOT NULL,
    food_db_id              TEXT,            -- 對應 food_nutrition_cache.food_id
    total_count             INTEGER DEFAULT 0,   -- 總記錄次數
    recent_count            INTEGER DEFAULT 0,   -- 近 30 天內有記錄此食物的天數（非份數）
    avg_daily_score_when_eaten  REAL,             -- 吃這個食物的日子平均日評分（行為訊號）
    avg_food_quality_score       REAL,             -- 食物本身營養特徵分 0–100（營養訊號）
    last_eaten_date         DATE,
    never_suggest           INTEGER DEFAULT 0,   -- 明確說「不要推薦」
    always_suggest          INTEGER DEFAULT 0,  -- 明確說「喜歡，常推薦」
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, food_name)
);

-- Phase 2B: 使用者常去店家個人資料
CREATE TABLE IF NOT EXISTS user_restaurant_profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT    NOT NULL,
    restaurant_name TEXT    NOT NULL,
    scene           TEXT    NOT NULL,
    notes           TEXT,
    created_at      TEXT    DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, restaurant_name)
);

CREATE TABLE IF NOT EXISTS user_restaurant_menu_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             TEXT    NOT NULL,
    restaurant_name     TEXT    NOT NULL,
    item_name           TEXT    NOT NULL,
    category            TEXT,
    price               INTEGER,
    estimated_calories  REAL,
    estimated_protein_g REAL,
    estimated_carb_g    REAL,
    estimated_fat_g     REAL,
    tags                TEXT,
    notes               TEXT,
    created_at          TEXT    DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, restaurant_name, item_name)
);
