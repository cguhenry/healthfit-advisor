#!/usr/bin/env python3
"""
privacy_manager.py — Phase 7: User data export and deletion helpers.

Implements a minimal privacy workflow aligned with GDPR/HIPAA-style
operational basics for local single-user data.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from db_manager import DBManager


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _list_user_tables(db: DBManager) -> list[str]:
    with closing(db.connect()) as conn:
        tables = [
            row["name"]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        ]
        result: list[str] = []
        for table in tables:
            columns = {
                row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "user_id" in columns:
                result.append(table)
        return result


def preview_user_data(db: DBManager, user_id: str) -> dict[str, int]:
    db.initialize()
    counts: dict[str, int] = {}
    for table in _list_user_tables(db):
        row = db.fetch_one(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = ?", (user_id,))
        counts[table] = int(row["n"] or 0) if row else 0
    return counts


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not fieldnames:
            handle.write("")
            return
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def export_user_data(
    db: DBManager,
    user_id: str,
    *,
    output_dir: Optional[Path] = None,
) -> dict[str, Any]:
    db.initialize()
    stamp = _timestamp()
    output_root = (output_dir or Path.cwd()).expanduser().resolve()
    export_dir = output_root / f"healthfit_privacy_export_{user_id}_{stamp}"
    export_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "user_id": user_id,
        "exported_at": stamp,
        "tables": {},
        "total_records": 0,
        "formats": ["json", "csv"],
    }

    for table in _list_user_tables(db):
        rows = [dict(row) for row in db.fetchall(f"SELECT * FROM {table} WHERE user_id = ? ORDER BY rowid", (user_id,))]
        json_path = export_dir / f"{table}.json"
        csv_path = export_dir / f"{table}.csv"
        json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_csv(csv_path, rows)
        manifest["tables"][table] = {
            "records": len(rows),
            "json": json_path.name,
            "csv": csv_path.name,
        }
        manifest["total_records"] += len(rows)

    manifest_path = export_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    zip_path = export_dir.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(export_dir.iterdir()):
            archive.write(path, arcname=f"{export_dir.name}/{path.name}")

    return {
        "user_id": user_id,
        "export_dir": str(export_dir),
        "zip_path": str(zip_path),
        "total_records": manifest["total_records"],
        "tables": manifest["tables"],
    }


def delete_user_data(db: DBManager, user_id: str, *, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        raise ValueError("confirmation required before deleting user data")

    db.initialize()
    tables = _list_user_tables(db)
    ordered_tables = [table for table in tables if table != "users"] + (["users"] if "users" in tables else [])
    deleted: dict[str, int] = {}

    with closing(db.connect()) as conn:
        with conn:
            for table in ordered_tables:
                row = conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                count = int(row["n"] or 0) if row else 0
                if count:
                    conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
                deleted[table] = count

    return {
        "user_id": user_id,
        "deleted_by_table": deleted,
        "total_deleted": sum(deleted.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="HealthFit privacy manager (Phase 7).")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--user-id", required=True)
    common.add_argument("--db-path", default=str(DBManager().db_path))

    p_preview = sub.add_parser("preview", parents=[common], help="Preview user data counts")
    p_export = sub.add_parser("export", parents=[common], help="Export user data to JSON/CSV zip")
    p_export.add_argument("--output-dir", default=".")
    p_delete = sub.add_parser("delete", parents=[common], help="Delete user data after confirmation")
    p_delete.add_argument("--confirm", action="store_true", help="Required confirmation flag")

    args = parser.parse_args()
    db = DBManager(Path(args.db_path))

    if args.command == "preview":
        print(json.dumps(preview_user_data(db, args.user_id), ensure_ascii=False, indent=2))
    elif args.command == "export":
        result = export_user_data(db, args.user_id, output_dir=Path(args.output_dir))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "delete":
        result = delete_user_data(db, args.user_id, confirm=args.confirm)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
