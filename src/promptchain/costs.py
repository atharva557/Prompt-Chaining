"""Token estimation and best-effort cloud cost accounting."""

# Approximate USD per 1M tokens (input, output), matched by substring (most
# specific first). Provider prices drift, so this is a best-effort estimate
# shown with an "est." label only; unknown models return None (no estimate).
_PRICING = [
    ("claude-fable", 10.0, 50.0),
    ("claude-opus", 5.0, 25.0),
    ("claude-sonnet", 3.0, 15.0),
    ("claude-haiku", 1.0, 5.0),
    ("gpt-4o-mini", 0.15, 0.60),
    ("gpt-4o", 2.50, 10.0),
    ("gpt-4.1-mini", 0.40, 1.60),
    ("gpt-4.1", 2.00, 8.00),
    ("o3-mini", 1.10, 4.40),
    ("gemini-2.0-flash", 0.10, 0.40),
    ("gemini-1.5-flash", 0.075, 0.30),
    ("gemini-2.5-pro", 1.25, 10.0),
    ("gemini-1.5-pro", 1.25, 5.0),
    ("gemini", 0.10, 0.40),  # fallback for other gemini flash-tier models
]


def estimate_cost(model: str, input_tokens, output_tokens) -> float | None:
    """Best-effort USD cost for a generation, or None if the model is unknown
    or token counts are missing. Only meaningful for cloud models."""
    if not model or input_tokens is None or output_tokens is None:
        return None
    m = model.lower()
    for sub, price_in, price_out in _PRICING:
        if sub in m:
            return (input_tokens / 1_000_000) * price_in + (output_tokens / 1_000_000) * price_out
    return None


def rough_token_count(*texts: str) -> int:
    """Very rough token estimate (~4 chars/token) across the given strings.
    Good enough for a context-size warning; never used for billing."""
    return sum(len(t) for t in texts if t) // 4


def format_stream_stats(
    model: str, chunk_count: int, elapsed: float, usage: dict
) -> str:
    """One-line stats caption for a generation: chunk-based tok/s estimate,
    plus exact billed tokens and estimated cost when the backend reported
    usage. Returns '' when there is nothing to show."""
    stats = []
    if chunk_count and elapsed > 0:
        # One SSE chunk is roughly one token
        stats.append(
            f"~{chunk_count} tokens in {elapsed:.1f}s "
            f"({chunk_count / elapsed:.1f} tok/s)"
        )
    if usage.get("input_tokens") is not None or usage.get("output_tokens") is not None:
        stats.append(
            f"{usage.get('input_tokens', '?')} in / "
            f"{usage.get('output_tokens', '?')} out tokens"
        )
        cost = estimate_cost(
            model, usage.get("input_tokens"), usage.get("output_tokens")
        )
        if cost is not None:
            stats.append(f"~${cost:.4f} est.")
    return " · ".join(stats)


_SIZE_UNITS = {
    "b": 1,
    "kb": 10**3, "mb": 10**6, "gb": 10**9, "tb": 10**12,
    "kib": 2**10, "mib": 2**20, "gib": 2**30, "tib": 2**40,
}


def parse_size(value) -> int | None:
    """Parse a human VRAM size ('18GiB', '20 GB', 9663676416) into bytes.
    None and empty strings return None; a bare number is taken as bytes."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower().replace(" ", "")
    for unit in sorted(_SIZE_UNITS, key=len, reverse=True):
        if text.endswith(unit):
            number = text[: -len(unit)]
            return int(float(number) * _SIZE_UNITS[unit])
    return int(float(text))
