#!/usr/bin/env python3
"""
recommendation_explainer.py — Phase 4: LLM 自然語言說明層

將結構化推薦結果交給 LLM，產生自然語言解釋。
嚴格限制：LLM 不得新增未出現在 JSON 的品項，不得改變排名。

使用方式：
    from recommendation_explainer import explain_recommendation

    explanation = explain_recommendation(
        user_context={...},
        recommendation=result.to_dict(),
    )
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import requests

# ─────────────────────────────────────────────────────────────────────────
# Prompt template
# ─────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """你是一位專業的營養師，專門為減脂/增肌族群解釋外食推薦。

你只允許做兩件事：
1. 用自然語言說明每個推薦品項為什麼適合或不適合（熱量、蛋白質、低GI等角度）
2. 提供點餐調整建議（少醬、去皮、減飯等）

嚴格禁止：
- 不要新增任何未出現在輸入 JSON 中的菜單品項
- 不要改變推薦排名
- 不要捏造營養數值（只能引用 JSON 中已有的數值）
- 不要假設使用者有特定的過敏原或飲食限制（除非 JSON 有提到）

如果資料來源是 scenario_template，必須明確說明：「以下是依據此類型店家常見品項推估，並非該店實際菜單。」

回應格式：
- 使用友善的台灣口語（可以說「今天熱量還有...」「蛋白質還差...」）
- 每個推薦品項解釋為什麼適合（1-2 句）
- 最後提供 1-2 個點餐調整技巧

你的回應應該是流暢的段落或條列，不是 JSON。"""


_USER_PROMPT_TEMPLATE = """請根據以下資料，產生自然的說明：

```json
{{
    "使用者狀態": {user_context},
    "推薦結果": {recommendation}
}}
```

說明："""


# ─────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────

def explain_recommendation(
    user_context: dict[str, Any],
    recommendation: dict[str, Any],
    *,
    model: str = "gpt-4o",
    api_key: Optional[str] = None,
    temperature: float = 0.3,
    timeout_s: float = 30.0,
) -> str:
    """
    將結構化推薦結果交給 LLM，產生自然語言說明。

    Parameters
    ----------
    user_context : dict
        包含 calories_remaining, protein_gap_g, goal_type 等欄位
    recommendation : dict
        DiningRecommendation.to_dict() 的輸出
    model : str
        使用的模型（預設 gpt-4o）
    api_key : str, optional
        若未提供，嘗試讀取環境變數 OPENAI_API_KEY
    temperature : float
        LLM temperature（預設 0.3，保持穩定）
    timeout_s : float
        HTTP request timeout（秒）

    Returns
    -------
    str
        LLM 產出的自然語言說明

    Raises
    ------
    RuntimeError
        當無法取得 API key 或 LLM 回應格式有問題時
    """
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not set. "
            "Set the environment variable or pass api_key explicitly."
        )

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        user_context=json.dumps(user_context, ensure_ascii=False),
        recommendation=json.dumps(recommendation, ensure_ascii=False),
    )

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": 1024,
    }

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout_s,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"OpenAI API error {response.status_code}: {response.text}"
        )

    result = response.json()
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected API response shape: {result}") from exc


def explain_recommendation_anthropic(
    user_context: dict[str, Any],
    recommendation: dict[str, Any],
    *,
    model: str = "claude-3-5-haiku",
    api_key: Optional[str] = None,
    temperature: float = 0.3,
    timeout_s: float = 30.0,
) -> str:
    """
    Anthropic Claude 版（若使用 Anthropic API）。

    與 explain_recommendation() 相同介面，替換後端。
    """
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed")

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. "
            "Set the environment variable or pass api_key explicitly."
        )

    client = anthropic.Anthropic(api_key=api_key)

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        user_context=json.dumps(user_context, ensure_ascii=False),
        recommendation=json.dumps(recommendation, ensure_ascii=False),
    )

    message = client.messages.create(
        model=model,
        max_tokens=1024,
        temperature=temperature,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    return "\n".join(
        block.text for block in message.content if hasattr(block, "text")
    )