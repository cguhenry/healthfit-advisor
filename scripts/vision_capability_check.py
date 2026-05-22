#!/usr/bin/env python3
"""
vision_capability_check.py

Vision-agnostic capability detection for the HealthFit Advisor skill.

This module does NOT call any Vision API. It checks whether the
currently-running LLM (identified by its model ID string) is a known
vision-capable multimodal model. The actual image analysis is performed
by the Agent framework's own LLM when it processes the prompt we return.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Known non-vision models — checked FIRST to avoid substring collisions
# (e.g. "gpt-4o-mini" contains "gpt-4o" but is not vision-capable)
# ---------------------------------------------------------------------------
KNOWN_NONVISION: List[str] = [
    "gpt-3.5",
    "gpt-4o-mini",
    "gpt-4.1",
    "o3",
    "o4",
    "deepseek-v3",
    "deepseek-chat",
]

# ---------------------------------------------------------------------------
# Known vision-capable model identifier substrings
# ---------------------------------------------------------------------------
KNOWN_VISION_SUBSTRINGS: List[str] = [
    # Claude (Anthropic)
    "claude-3",
    "claude-opus",
    "claude-sonnet",
    "claude-haiku",
    "claude-3.5",
    "claude-3.7",
    # OpenAI GPT-4 Vision / GPT-4o / GPT-4 turbo vision
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-4-vision",
    "chatgpt-4",
    # Google Gemini Vision
    "gemini-pro-vision",
    "gemini-1.5",
    "gemini-2.0",
    "gemini-2.5",
    # Open-source / local multimodal
    "llava",
    "qwen-vl",
    "internvl",
    "minigpt4",
    "bakllava",
    "cogvlm",
    "moondream",
    # Others
    "vision",
    "multimodal",
    "gemma-3",
    "gemma-4",
]

# Display names for the fallback message
SUPPORTED_MODEL_FAMILIES: Dict[str, List[str]] = {
    "Claude": ["Claude 3 Sonnet / Opus / Haiku", "Claude 3.5 Sonnet"],
    "OpenAI": ["GPT-4o", "GPT-4 Turbo", "GPT-4 Vision"],
    "Google": ["Gemini 1.5 Pro / Flash", "Gemini 2.0"],
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass
class VisionCheckResult:
    supported: bool
    model_id: str
    confidence: float = 1.0
    fallback_message: Optional[str] = None
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "supported": self.supported,
            "model_id": self.model_id,
            "confidence": self.confidence,
            "fallback_message": self.fallback_message,
            "suggestion": self.suggestion,
        }


# ---------------------------------------------------------------------------
# VisionNotSupportedError — raise in analysis flow to abort gracefully
# ---------------------------------------------------------------------------
class VisionNotSupportedError(Exception):
    """Raised when the current LLM does not support vision input."""

    def __init__(self, fallback_message: str):
        self.fallback_message = fallback_message
        super().__init__(fallback_message)


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------
def check(model_id: Optional[str] = None) -> VisionCheckResult:
    """
    Detect whether model_id refers to a known vision-capable LLM.

    Uses substring matching on KNOWN_VISION_SUBSTRINGS, with KNOWN_NONVISION
    checked first to avoid false positives from substring collisions.
    Returns a VisionCheckResult; does not raise.

    If model_id is None, checks `current_model_id_from_env()`.
    """
    resolved = model_id or current_model_id_from_env()
    if not resolved:
        return VisionCheckResult(
            supported=False,
            model_id="unknown",
            confidence=0.0,
            fallback_message=(
                "⚠️ 無法偵測當前使用的 LLM 模型 ID，"
                "無法判斷是否支援圖像輸入。\n"
                "請確認您的 Agent 框架已正確設定模型 ID，"
                "或切換至已知支援視覺的多模態模型。"
            ),
        )

    resolved_lower = resolved.lower()

    # Check non-vision models FIRST (avoids substring collisions)
    for name in KNOWN_NONVISION:
        if name in resolved_lower:
            return VisionCheckResult(
                supported=False,
                model_id=resolved,
                confidence=1.0,
                fallback_message=_build_fallback_message(resolved),
                suggestion="切換至 GPT-4o、Claude 3 Sonnet、GPT-4 Turbo、Gemini 1.5 Pro 或其他支援圖像輸入的模型。",
            )

    for substring in KNOWN_VISION_SUBSTRINGS:
        if substring in resolved_lower:
            return VisionCheckResult(
                supported=True,
                model_id=resolved,
                confidence=1.0,
            )

    # Unknown model — conservative: assume NOT supported
    return VisionCheckResult(
        supported=False,
        model_id=resolved,
        confidence=0.5,  # uncertain
        fallback_message=_build_fallback_message(resolved),
        suggestion="若模型不支援圖像，請切換至 GPT-4o、Claude 3 Sonnet 或 Gemini 1.5 Pro。",
    )


def require(model_id: Optional[str] = None) -> None:
    """
    Check vision capability. Raise VisionNotSupportedError if not supported.

    Use at the entry point of any image-analysis workflow.
    """
    result = check(model_id)
    if not result.supported:
        raise VisionNotSupportedError(
            result.fallback_message or _build_fallback_message(model_id or "unknown")
        )


def _build_fallback_message(model_id: str) -> str:
    lines = [
        f"⚠️ 您目前使用的模型（`{model_id}`）可能不支援圖像輸入功能。",
        "",
        "若要分析食物照片或菜單圖片，請切換至支援圖像輸入的多模態模型，例如：",
    ]
    for family, examples in SUPPORTED_MODEL_FAMILIES.items():
        lines.append(f"  • {family}：{', '.join(examples)}")
    lines.append("")
    lines.append("切換模型後重新上傳圖片即可繼續分析。")
    return "\n".join(lines)


def current_model_id_from_env() -> Optional[str]:
    """
    Read the current model ID from the runtime environment.
    Checks common environment variable names used by agent frameworks.
    """
    for var in [
        "CURRENT_MODEL_ID",
        "MODEL_ID",
        "OPENAI_MODEL_NAME",
        "ANTHROPIC_MODEL",
        "GEMINI_MODEL",
        "LLM_MODEL",
        "AI_MODEL",
        "AGENT_MODEL",
        "ACTIVE_MODEL",
        "OPENCLAW_MODEL",
    ]:
        value = os.environ.get(var)
        if value:
            return value
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Check if the current LLM supports vision.")
    parser.add_argument("--model", "-m", default=None, help="Model ID to check (default: from env)")
    parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    args = parser.parse_args()

    result = check(args.model)

    if args.format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        if result.supported:
            print(f"✅ 模型 `{result.model_id}` 支援圖像輸入。")
        else:
            print(result.fallback_message or _build_fallback_message(result.model_id))


if __name__ == "__main__":
    main()