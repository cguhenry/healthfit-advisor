#!/usr/bin/env python3
"""
user_restaurant_repository.py — Phase 2B: 使用者常去店家 CRUD

提供：
- upsert_user_restaurant_profile / upsert_user_restaurant_item
- load_user_restaurant_profile / load_user_restaurant_items
"""

from __future__ import annotations

import json
from typing import Any

from db_manager import DBManager
from dining_models import MenuItem


def upsert_user_restaurant_profile(
    db: DBManager,
    *,
    user_id: str,
    restaurant_name: str,
    scene: str,
    notes: str | None = None,
) -> None:
    db.initialize()
    db.execute(
        """
        INSERT INTO user_restaurant_profiles (
            user_id, restaurant_name, scene, notes, updated_at
        )
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, restaurant_name)
        DO UPDATE SET
            scene = excluded.scene,
            notes = excluded.notes,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, restaurant_name, scene, notes),
    )


def upsert_user_restaurant_item(
    db: DBManager,
    *,
    user_id: str,
    restaurant_name: str,
    item: MenuItem,
    notes: str | None = None,
) -> None:
    db.initialize()
    db.execute(
        """
        INSERT INTO user_restaurant_menu_items (
            user_id,
            restaurant_name,
            item_name,
            category,
            price,
            estimated_calories,
            estimated_protein_g,
            estimated_carb_g,
            estimated_fat_g,
            tags,
            notes,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, restaurant_name, item_name)
        DO UPDATE SET
            category = excluded.category,
            price = excluded.price,
            estimated_calories = excluded.estimated_calories,
            estimated_protein_g = excluded.estimated_protein_g,
            estimated_carb_g = excluded.estimated_carb_g,
            estimated_fat_g = excluded.estimated_fat_g,
            tags = excluded.tags,
            notes = excluded.notes,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            user_id,
            restaurant_name,
            item.name,
            item.category,
            item.price,
            item.estimated_calories,
            item.estimated_protein_g,
            item.estimated_carb_g,
            item.estimated_fat_g,
            json.dumps(item.tags, ensure_ascii=False),
            notes,
        ),
    )


def load_user_restaurant_profile(
    db: DBManager,
    *,
    user_id: str,
    restaurant_name: str,
) -> dict[str, Any] | None:
    db.initialize()
    row = db.fetch_one(
        """
        SELECT *
        FROM user_restaurant_profiles
        WHERE user_id = ?
          AND restaurant_name = ?
        """,
        (user_id, restaurant_name),
    )
    return dict(row) if row else None


def load_user_restaurant_items(
    db: DBManager,
    *,
    user_id: str,
    restaurant_name: str,
) -> list[MenuItem]:
    db.initialize()
    rows = db.fetchall(
        """
        SELECT *
        FROM user_restaurant_menu_items
        WHERE user_id = ?
          AND restaurant_name = ?
        ORDER BY item_name ASC
        """,
        (user_id, restaurant_name),
    )

    items: list[MenuItem] = []

    for row in rows:
        tags_raw = row["tags"] or "[]"
        try:
            tags = json.loads(tags_raw)
        except json.JSONDecodeError:
            tags = []

        items.append(
            MenuItem(
                name=row["item_name"],
                category=row["category"],
                price=row["price"],
                estimated_calories=row["estimated_calories"],
                estimated_protein_g=row["estimated_protein_g"],
                estimated_carb_g=row["estimated_carb_g"],
                estimated_fat_g=row["estimated_fat_g"],
                tags=list(tags),
                source="user_restaurant_profile",
                confidence=0.8,
            )
        )

    return items