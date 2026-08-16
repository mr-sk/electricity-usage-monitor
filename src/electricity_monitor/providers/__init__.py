from __future__ import annotations

from .psegliny import PSEGLI_RATE_194

PROVIDERS = {
    "psegliny-rate194": PSEGLI_RATE_194,
}


def get_provider(name: str):
    try:
        return PROVIDERS[name]
    except KeyError as exc:
        raise ValueError(f"unknown provider {name!r}; choices: {', '.join(sorted(PROVIDERS))}") from exc

