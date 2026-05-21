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
    note TEXT
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
