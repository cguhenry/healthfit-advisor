# Food Database Download Status

**Download Date:** 2026-05-23  
**Source:** Taiwan FDA (data.gov.tw) + USDA FoodData Central (fdc.nal.usda.gov)

---

## ✅ Taiwan FDA Food Nutrition Composition Database

| Field | Value |
|-------|-------|
| **Source URL** | https://data.gov.tw/dataset/8543 |
| **Direct Download** | `https://data.fda.gov.tw/opendata/exportDataList.do?method=ExportData&InfoId=20&logType=2` |
| **Output File** | `assets/tw_food_db/tw_food_db.csv` |
| **Format** | CSV (Big5-encoded, quoted) |
| **File Size** | 63 MB |
| **Row Count** | 226,825 lines |
| **Download Method** | curl → ZIP → extracted via Python zipfile |

**Column Headers (17 columns):**
- 食品分類, 資料類別, 整合編號, 樣品名稱, 俗名, 樣品英文名稱, 內容物描述,
- 廢棄率, 分析項分類, 分析項, 含量單位, 每100克含量, 樣本數, 標準差,
- 每單位含量, 每單位重, 每單位重含量

**Sample Rows:**
```
"食品分類","資料類別","整合編號","樣品名稱","俗名","樣品英文名稱","內容物描述","廢棄率","分析項分類","分析項","含量單位","每100克含量","樣本數","標準差","每單位含量","每單位重","每單位重含量"
"魚貝類","樣品基本資料","J0414801","鯖魚(炒)",,"Mackerel","前處理描述:去鱗,含皮,去骨刺及內臟,以5g沙拉油炒5分鐘",,"脂肪酸組成","P/M/S",,"1.52/1.89/1.00","0",,,"0.0克",
"魚貝類","樣品基本資料","J0414801","鯖魚(炒)",,"Mackerel","前處理描述:去鱗,含皮,去骨刺及內臟,以5g沙拉油炒5分鐘",,"維生素E","α-生育酚","mg","              0.74","1",,"              0.74","0.0克","              0.00"
```

**Notes:**
- Each food item spans multiple rows (one row per nutrient)
- The same food item (same 整合編號) appears with different 分析項 (nutrients)
- Downloaded as ZIP; actual CSV is `20_2.csv` inside the archive
- Metadata updated: 2025-10-17

---

## ✅ USDA FoodData Central — Foundation Foods (April 2026 Release)

| Field | Value |
|-------|-------|
| **Source URL** | https://fdc.nal.usda.gov/download-datasets |
| **Direct Download** | `https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_foundation_food_csv_2026-04-30.zip` |
| **Output File** | `assets/usda_food_db/usda_foundation.csv` (food.csv, the main food list) |
| **Supporting File** | `assets/usda_food_db/foundation_food.csv` (maps fdc_id → NDB) |
| **Format** | CSV (UTF-8, quoted) |
| **File Size** | 6.9 MB (food.csv) |
| **Row Count** | 87,992 lines (food.csv), 396 lines (foundation_food.csv) |
| **Release Date** | April 2026 |
| **Download Method** | curl → ZIP → extracted via Python zipfile |

**Main food.csv Columns:**
`fdc_id`, `data_type`, `description`, `food_category_id`, `publication_date`

**foundation_food.csv Columns:**
`fdc_id`, `NDB_number`, `footnote`

**Sample Rows (food.csv):**
```
"fdc_id","data_type","description","food_category_id","publication_date"
"319874","sample_food","HUMMUS, SABRA CLASSIC","16","2019-04-01"
"319875","market_acquisition","HUMMUS, SABRA CLASSIC","16","2019-04-01"
```

**Notes:**
- The ZIP contains 28 CSV files (full relational structure including nutrients, portions, etc.)
- Only the main `food.csv` and `foundation_food.csv` are copied to `usda_food_db/`
- To access nutrient data, look at `food_nutrient.csv` in the extracted ZIP at `/tmp/usda_extract/FoodData_Central_foundation_food_csv_2026-04-30/`

---

## ⚠️ Issues Encountered

1. **EDRN portal URL failed** — `portal.edrnamingaining.org` (typo in original task URL) was unreachable
2. **USDA direct .html attempt failed** — 404; resolved by scraping the actual download page for the CSV zip URL
3. **No `file` or `unzip` CLI** — used Python `zipfile` module instead

---

## 📦 Full USDA ZIP Location (for future nutrient data access)

`/tmp/usda_extract/FoodData_Central_foundation_food_csv_2026-04-30/`

Key files inside:
- `food.csv` → 87,992 rows (copied to `assets/usda_food_db/usda_foundation.csv`)
- `food_nutrient.csv` → nutrient values per food item
- `nutrient.csv` → nutrient ID → name mapping
- `food_portion.csv` → portion size data
- `foundation_food.csv` → foundation-specific metadata (copied to `assets/usda_food_db/`)