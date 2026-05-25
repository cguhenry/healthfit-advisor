#!/usr/bin/env python3
"""
healthfit.py - Unified CLI entry point for HealthFit Advisor.

Keeps the existing per-phase scripts intact while exposing one stable
operator-facing command surface for local CLI use and agent manifests.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent


def _run_script(script_name: str, forwarded_args: Sequence[str]) -> int:
    script_path = SCRIPT_DIR / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"missing target script: {script_path}")
    cmd = [sys.executable, str(script_path), *forwarded_args]
    completed = subprocess.run(cmd, check=False)
    return completed.returncode


def _summary_date_from_timestamp(log_datetime: str | None) -> str:
    if not log_datetime:
        return date.today().isoformat()
    normalized = log_datetime.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).date().isoformat()


def _load_json_payload(path_or_dash: str) -> dict[str, Any]:
    if path_or_dash == "-":
        raw_text = sys.stdin.read()
    else:
        raw_text = Path(path_or_dash).read_text(encoding="utf-8")
    payload = json.loads(raw_text)
    if not isinstance(payload, dict):
        raise ValueError("Phase 3 payload must be a JSON object.")
    return payload


def _write_json_file(path: str, payload: dict[str, Any]) -> str:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(target)


def _build_image_prompt_bundle(forwarded_args: Sequence[str]) -> int:
    from db_manager import DBManager
    from food_analyzer import AnalysisScenario, build_llm_prompt

    parser = argparse.ArgumentParser(
        prog="healthfit.py image prompt",
        description="Build the multimodal prompt bundle for image meal analysis and show the next ingestion command.",
    )
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--meal-type", choices=("breakfast", "lunch", "dinner", "snack"), default="lunch")
    parser.add_argument("--scenario", choices=("food", "menu", "before_after"), default="food")
    parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))
    parser.add_argument("--goal-type", choices=("loss", "gain", "maintain"), default="loss")
    parser.add_argument("--remaining-calories", type=int, default=0)
    parser.add_argument("--protein-gap", type=int, default=0)
    parser.add_argument("--daily-calorie-target", type=int, default=0)
    parser.add_argument("--protein-target-g", type=int, default=0)
    parser.add_argument("--estimated-meal-calories", type=int, default=0)
    parser.add_argument("--log-datetime", help="Optional ISO-8601 timestamp to reuse at logging time.")
    parser.add_argument("--note", help="Optional note to attach when persisting the meal log.")
    parser.add_argument(
        "--phase3-output",
        default="phase3_response.json",
        help="Suggested path for the raw Phase 3 JSON response produced from the image.",
    )
    args = parser.parse_args(list(forwarded_args))

    # A1 fix: auto-fill remaining-calories / protein-gap / targets from DB
    # when --db-path is provided and --remaining-calories wasn't explicitly set
    import os as _os
    if args.db_path and Path(args.db_path).expanduser().exists():
        try:
            from calorie_tracker import get_calorie_progress

            db = DBManager(Path(args.db_path).expanduser())
            progress = get_calorie_progress(db, args.user_id)
            if progress:
                if not args.remaining_calories:
                    args.remaining_calories = max(0, int(progress.get("remaining_calories") or 0))
                if not args.protein_gap:
                    args.protein_gap = max(0, int(progress.get("protein_gap_g") or 0))
            plan = db.get_active_plan(args.user_id)
            if plan:
                if not args.daily_calorie_target:
                    args.daily_calorie_target = int(plan["daily_calorie_target"] or 0)
                if not args.protein_target_g:
                    args.protein_target_g = int(plan["protein_target_g"] or 0)
                if not args.goal_type or args.goal_type == "loss":
                    args.goal_type = plan.get("goal_type", "loss")
        except Exception:
            pass  # silently fall back to explicitly provided values

    system_prompt, user_prompt = build_llm_prompt(
        AnalysisScenario(args.scenario),
        goal_type=args.goal_type,
        remaining_calories=args.remaining_calories,
        protein_gap=args.protein_gap,
        daily_calorie_target=args.daily_calorie_target,
        protein_target_g=args.protein_target_g,
        estimated_meal_calories=args.estimated_meal_calories,
    )

    next_command = [
        "python3",
        "scripts/healthfit.py",
        "log",
        "from-image",
        args.phase3_output,
        "--user-id",
        args.user_id,
        "--meal-type",
        args.meal_type,
        "--scenario",
        args.scenario,
        "--db-path",
        args.db_path,
    ]
    if args.log_datetime:
        next_command.extend(["--log-datetime", args.log_datetime])
    if args.note:
        next_command.extend(["--note", args.note])

    result = {
        "scenario": args.scenario,
        "meal_type": args.meal_type,
        "phase3_output_file": str(Path(args.phase3_output).expanduser()),
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "next_command": next_command,
        "agent_workflow": [
            "Attach the meal image to the multimodal LLM together with system_prompt and user_prompt.",
            "Save the raw JSON-only reply to phase3_output_file.",
            "Run next_command to parse the JSON and persist the meal log.",
        ],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _build_checkin_prompt_bundle(forwarded_args: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="healthfit.py checkin prompt",
        description="Build the daily check-in prompt for a specific meal.",
    )
    parser.add_argument("--meal-type", choices=("breakfast", "lunch", "dinner", "snack"), default="lunch")
    parser.add_argument("--user-id", help="Optional user id for the suggested next command.")
    args = parser.parse_args(list(forwarded_args))

    meal_labels = {
        "breakfast": "早餐",
        "lunch": "午餐",
        "dinner": "晚餐",
        "snack": "點心",
    }
    next_command = ["python3", "scripts/healthfit.py", "checkin", "answer"]
    if args.user_id:
        next_command.extend(["--user-id", args.user_id])
    next_command.extend(["--meal-type", args.meal_type, "--text", "<user_reply>"])
    result = {
        "meal_type": args.meal_type,
        "question": f"今天{meal_labels[args.meal_type]}吃了什麼？",
        "next_command": next_command,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _run_log_from_checkin(forwarded_args: Sequence[str]) -> int:
    import json as _json
    from pathlib import Path as _Path
    from notification_scheduler import DEFAULT_PROFILE_PATH

    from diet_dialogue import process_checkin_response

    parser = argparse.ArgumentParser(
        prog="healthfit.py checkin answer",
        description="Parse a natural-language daily check-in answer and persist it as a manual meal log.",
    )
    parser.add_argument("--user-id")  # optional — auto-loaded from profile.json if absent
    parser.add_argument("--text", required=True, help="Natural-language user reply, e.g. '雞胸肉、茶葉蛋、無糖豆漿'.")
    parser.add_argument("--meal-type", choices=("breakfast", "lunch", "dinner", "snack"))
    parser.add_argument("--db-path", default="~/.healthfit/healthfit.db")
    parser.add_argument("--log-datetime", help="Optional ISO-8601 timestamp override.")
    parser.add_argument("--note", help="Optional note attached to each inserted row.")
    args = parser.parse_args(list(forwarded_args))

    # B3 fix: auto-read user_id from profile.json if not provided
    if not args.user_id:
        profile_path = _Path(str(DEFAULT_PROFILE_PATH)).expanduser()
        if profile_path.exists():
            with open(profile_path) as pf:
                profile = _json.load(pf)
                args.user_id = profile.get("user_id") or profile.get("user", {}).get("user_id", "")
        if not args.user_id:
            raise ValueError(
                "Could not determine user_id. Provide --user-id or ensure ~/.healthfit/profile.json "
                "contains a top-level 'user_id' field."
            )

    result = process_checkin_response(
        args.text,
        user_id=args.user_id,
        meal_type=args.meal_type,
        db_path=args.db_path,
        log_datetime=args.log_datetime,
        note=args.note,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _run_log_from_image(forwarded_args: Sequence[str]) -> int:
    from calorie_tracker import log_meal_analysis, normalize_phase3_analysis_payload, upsert_daily_summary
    from db_manager import DBManager
    from food_analyzer import AnalysisScenario, parse_llm_response

    parser = argparse.ArgumentParser(
        prog="healthfit.py log from-image",
        description="Parse a Phase 3 image-analysis JSON response and persist it directly into Phase 4 logs.",
    )
    parser.add_argument("json_file", help="Path to raw Phase 3 LLM JSON response, or '-' to read JSON from stdin.")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--meal-type", choices=("breakfast", "lunch", "dinner", "snack"), default="lunch")
    parser.add_argument("--scenario", choices=("food", "before_after"), default="food")
    parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))
    parser.add_argument("--log-datetime", help="Override the log timestamp (ISO-8601).")
    parser.add_argument("--note", help="Optional note attached to each inserted row.")
    parser.add_argument("--print-analysis", action="store_true", help="Also print the normalized Phase 3 payload.")
    parser.add_argument(
        "--save-raw-response",
        help="Optional path to also save the raw Phase 3 JSON (useful when the agent produced JSON from an attached image).",
    )
    args = parser.parse_args(list(forwarded_args))

    raw_payload = _load_json_payload(args.json_file)
    saved_raw_response = None
    if args.save_raw_response:
        saved_raw_response = _write_json_file(args.save_raw_response, raw_payload)
    parsed = parse_llm_response(AnalysisScenario(args.scenario), raw_payload)
    normalized_payload = parsed.to_dict()
    if args.note:
        normalized_payload["note"] = args.note
    if args.log_datetime:
        normalized_payload["log_datetime"] = args.log_datetime

    foods, total_nutrition = normalize_phase3_analysis_payload(normalized_payload)
    db = DBManager(Path(args.db_path))
    inserted = log_meal_analysis(
        db,
        args.user_id,
        args.meal_type,
        foods,
        total_nutrition=total_nutrition,
        log_datetime=normalized_payload.get("log_datetime"),
        note=normalized_payload.get("note"),
    )

    active_plan = db.get_active_plan(args.user_id)
    calorie_target = int(active_plan["daily_calorie_target"] or 0) if active_plan else 0
    summary = upsert_daily_summary(
        db,
        args.user_id,
        summary_date=_summary_date_from_timestamp(normalized_payload.get("log_datetime")),
        calorie_target=calorie_target,
    )

    result = {
        "logged_rows": len(inserted),
        "log_ids": inserted,
        "summary": {
            "date": summary.summary_date,
            "total_calories": summary.total_calories,
            "total_protein_g": summary.total_protein_g,
            "total_carb_g": summary.total_carb_g,
            "total_fat_g": summary.total_fat_g,
            "calorie_target": summary.calorie_target,
            "calorie_balance": summary.calorie_balance,
        },
    }
    if args.print_analysis:
        result["analysis"] = normalized_payload
    if saved_raw_response:
        result["saved_raw_response"] = saved_raw_response

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="healthfit.py",
        description="Unified CLI for HealthFit Advisor workflows.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_intake = sub.add_parser("intake", help="Run the Phase 1 intake flow.")
    p_intake.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to intake_flow.py")

    p_log = sub.add_parser("log", help="Logging workflows.")
    log_sub = p_log.add_subparsers(dest="log_command", required=True)
    p_log_meal = log_sub.add_parser("meal", help="Log a meal analysis payload.")
    p_log_meal.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to calorie_tracker.py log")
    p_log_from_image = log_sub.add_parser("from-image", help="Parse Phase 3 image analysis JSON and log it in one step.")
    p_log_from_image.add_argument("json_file", help="Path to raw Phase 3 LLM JSON response, or '-' to read stdin")
    p_log_from_image.add_argument("--user-id", required=True)
    p_log_from_image.add_argument("--meal-type", choices=("breakfast", "lunch", "dinner", "snack"), default="lunch")
    p_log_from_image.add_argument("--scenario", choices=("food", "before_after"), default="food")
    p_log_from_image.add_argument("--db-path", default="~/.healthfit/healthfit.db")
    p_log_from_image.add_argument("--log-datetime")
    p_log_from_image.add_argument("--note")
    p_log_from_image.add_argument("--print-analysis", action="store_true")
    p_log_from_image.add_argument("--save-raw-response")

    p_image = sub.add_parser("image", help="Image-analysis prompt and ingestion helpers.")
    image_sub = p_image.add_subparsers(dest="image_command", required=True)
    p_image_prompt = image_sub.add_parser("prompt", help="Build the prompt bundle for an attached meal image.")
    p_image_prompt.add_argument("args", nargs=argparse.REMAINDER, help="Arguments handled by the image prompt helper")

    p_checkin = sub.add_parser("checkin", help="Daily check-in Q&A helpers.")
    checkin_sub = p_checkin.add_subparsers(dest="checkin_command", required=True)
    p_checkin_prompt = checkin_sub.add_parser("prompt", help="Build the standard meal check-in question.")
    p_checkin_prompt.add_argument("args", nargs=argparse.REMAINDER, help="Arguments handled by the check-in prompt helper")
    p_checkin_answer = checkin_sub.add_parser("answer", help="Parse a natural-language check-in reply and log it.")
    p_checkin_answer.add_argument("--user-id")  # optional — auto-loaded from profile.json
    p_checkin_answer.add_argument("--text", required=True)
    p_checkin_answer.add_argument("--meal-type", choices=("breakfast", "lunch", "dinner", "snack"))
    p_checkin_answer.add_argument("--db-path", default="~/.healthfit/healthfit.db")
    p_checkin_answer.add_argument("--log-datetime")
    p_checkin_answer.add_argument("--note")

    p_report = sub.add_parser("report", help="Generate reports.")
    report_sub = p_report.add_subparsers(dest="report_command", required=True)
    p_report_daily = report_sub.add_parser("daily", help="Generate a daily report.")
    p_report_daily.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to report_generator.py daily")
    p_report_weekly = report_sub.add_parser("weekly", help="Generate a weekly report.")
    p_report_weekly.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to report_generator.py weekly")

    p_plan = sub.add_parser("plan", help="Generate a weekly meal plan.")
    p_plan.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to meal_planner.py plan")

    p_gi = sub.add_parser("gi", help="GI lookup and guidance.")
    gi_sub = p_gi.add_subparsers(dest="gi_command", required=True)
    p_gi_classify = gi_sub.add_parser("classify", help="Classify a food's GI tier.")
    p_gi_classify.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to gi_guide.py classify")
    p_gi_alias = gi_sub.add_parser("lookup", help="Alias of gi classify.")
    p_gi_alias.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to gi_guide.py classify")
    p_gi_swap = gi_sub.add_parser("swap", help="Recommend a lower-GI alternative.")
    p_gi_swap.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to gi_guide.py swap")
    p_gi_strategy = gi_sub.add_parser("strategy", help="Show GI eating strategy.")
    p_gi_strategy.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to gi_guide.py strategy")

    p_menu = sub.add_parser("menu", help="Get menu suggestions from menu_advisor.py.")
    p_menu.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to menu_advisor.py")

    p_alert = sub.add_parser("alert", help="Health alert workflows.")
    alert_sub = p_alert.add_subparsers(dest="alert_command", required=True)
    for name in ("check", "list", "ack"):
        p_alert_sub = alert_sub.add_parser(name, help=f"Forward to health_alerts.py {name}")
        p_alert_sub.add_argument("args", nargs=argparse.REMAINDER, help=f"Arguments forwarded to health_alerts.py {name}")

    p_notify = sub.add_parser("notify", help="Notification workflows.")
    notify_sub = p_notify.add_subparsers(dest="notify_command", required=True)
    for name in ("daily", "weekly", "checkin", "test", "setup-cron"):
        p_notify_sub = notify_sub.add_parser(name, help=f"Forward to notification_scheduler.py {name}")
        p_notify_sub.add_argument("args", nargs=argparse.REMAINDER, help=f"Arguments forwarded to notification_scheduler.py {name}")

    return parser


def dispatch(argv: Sequence[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 2
    if argv[0] in {"-h", "--help"}:
        build_parser().print_help()
        return 0

    command = argv[0]
    rest = argv[1:]

    if command == "intake":
        return _run_script("intake_flow.py", rest)
    if command == "log":
        if not rest:
            raise ValueError("log requires a subcommand")
        if rest[0] == "meal":
            return _run_script("calorie_tracker.py", ["log", *rest[1:]])
        if rest[0] == "from-image":
            return _run_log_from_image(rest[1:])
        raise ValueError(f"unsupported log subcommand: {rest[0]}")
    if command == "report":
        if not rest:
            raise ValueError("report requires a subcommand")
        if rest[0] in {"daily", "weekly"}:
            return _run_script("report_generator.py", [rest[0], *rest[1:]])
        raise ValueError(f"unsupported report subcommand: {rest[0]}")
    if command == "plan":
        return _run_script("meal_planner.py", ["plan", *rest])
    if command == "image":
        if not rest:
            raise ValueError("image requires a subcommand")
        if rest[0] == "prompt":
            return _build_image_prompt_bundle(rest[1:])
        raise ValueError(f"unsupported image subcommand: {rest[0]}")
    if command == "checkin":
        if not rest:
            raise ValueError("checkin requires a subcommand")
        if rest[0] == "prompt":
            return _build_checkin_prompt_bundle(rest[1:])
        if rest[0] == "answer":
            return _run_log_from_checkin(rest[1:])
        raise ValueError(f"unsupported checkin subcommand: {rest[0]}")
    if command == "gi":
        if not rest:
            raise ValueError("gi requires a subcommand")
        gi_command = "classify" if rest[0] in {"classify", "lookup"} else rest[0]
        if gi_command not in {"classify", "swap", "strategy", "list"}:
            raise ValueError(f"unsupported gi subcommand: {rest[0]}")
        return _run_script("gi_guide.py", [gi_command, *rest[1:]])
    if command == "menu":
        return _run_script("menu_advisor.py", rest)
    if command == "alert":
        if not rest:
            raise ValueError("alert requires a subcommand")
        if rest[0] not in {"check", "list", "ack"}:
            raise ValueError(f"unsupported alert subcommand: {rest[0]}")
        return _run_script("health_alerts.py", [rest[0], *rest[1:]])
    if command == "notify":
        if not rest:
            raise ValueError("notify requires a subcommand")
        if rest[0] not in {"daily", "weekly", "checkin", "test", "setup-cron"}:
            raise ValueError(f"unsupported notify subcommand: {rest[0]}")
        return _run_script("notification_scheduler.py", [rest[0], *rest[1:]])

    raise ValueError(f"unsupported command path: {command}")


def main() -> None:
    raise SystemExit(dispatch())


if __name__ == "__main__":
    main()
