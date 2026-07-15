MODEL_PRICES: dict[str, dict[str, float]] = {
    "gpt-4o":            {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":       {"input": 0.15,  "output": 0.60},
    "gpt-4-turbo":       {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo":     {"input": 0.50,  "output": 1.50},
    "claude-opus-4-8":       {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00,  "output": 15.00},
    "claude-haiku-4-5":  {"input": 0.80,  "output": 4.00},
}

_FALLBACK = {"input": 1.00, "output": 3.00}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = MODEL_PRICES.get(model, _FALLBACK)
    return (input_tokens / 1_000_000 * p["input"]) + (output_tokens / 1_000_000 * p["output"])
