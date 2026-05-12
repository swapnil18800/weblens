"""
Thread-safe per-request LLM cost / token tracker.

Pattern borrowed from alphalens/agent/llm/token_tracker.py — a context-scoped
singleton that LLM clients call after each completion. The eval harness resets
it per question and reads `snapshot()` to attach cost data to per-question JSON.

Prices are illustrative defaults (DeepSeek is cheap; OpenAI prices update often).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict

_PRICES_USD_PER_1K = {
    # input, output per 1K tokens (approximate, May 2026)
    "deepseek-chat":      (0.00027, 0.0011),
    "deepseek-reasoner":  (0.00055, 0.0022),
    "gpt-4o-mini":        (0.00015, 0.0006),
    "gpt-4o":             (0.0025,  0.010),
    "gpt-4.1-mini":       (0.0004,  0.0016),
}


@dataclass
class _Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class TokenTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_model: Dict[str, _Usage] = {}

    def record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            u = self._by_model.setdefault(model, _Usage())
            u.calls += 1
            u.input_tokens += input_tokens
            u.output_tokens += output_tokens
            price = _PRICES_USD_PER_1K.get(model, (0.0, 0.0))
            u.cost_usd += (input_tokens / 1000.0) * price[0] + (output_tokens / 1000.0) * price[1]

    def snapshot(self) -> dict:
        with self._lock:
            total_calls = sum(u.calls for u in self._by_model.values())
            total_in = sum(u.input_tokens for u in self._by_model.values())
            total_out = sum(u.output_tokens for u in self._by_model.values())
            total_cost = sum(u.cost_usd for u in self._by_model.values())
            return {
                "calls": total_calls,
                "input_tokens": total_in,
                "output_tokens": total_out,
                "total_tokens": total_in + total_out,
                "cost_usd": round(total_cost, 6),
                "by_model": {
                    m: {
                        "calls": u.calls,
                        "input_tokens": u.input_tokens,
                        "output_tokens": u.output_tokens,
                        "cost_usd": round(u.cost_usd, 6),
                    }
                    for m, u in self._by_model.items()
                },
            }

    def reset(self) -> None:
        with self._lock:
            self._by_model.clear()


_GLOBAL = TokenTracker()


def get_tracker() -> TokenTracker:
    return _GLOBAL
