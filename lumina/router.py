"""Multi-LLM routing: each task type goes to the cheapest model tier that handles it.

The demo ships an offline provider so it runs without keys. In production each tier
maps to a real model (for example a small local model for classification and a
frontier model for planning), selected from environment variables.
"""
import os
import re

ROUTES = {
    "classify": "small",
    "summarize": "small",
    "extract": "medium",
    "draft": "medium",
    "plan": "large",
    "review": "large",
}


def route(task):
    return ROUTES.get(task, "medium")


def model_for(task):
    tier = route(task)
    return os.environ.get(f"LUMINA_MODEL_{tier.upper()}") or f"offline-{tier}"


def complete(task, text):
    model = model_for(task)
    if model.startswith("offline-"):
        return _offline(task, text)
    # ponytail: only the offline provider ships; plug a real client here keyed on `model`.
    raise NotImplementedError(f"no provider wired for {model}")


def _offline(task, text):
    """Deterministic stand-in so every run and test gives the same output."""
    if task == "summarize":
        match = re.match(r"(.+?[.!?])(\s|$)", text.strip(), re.S)
        return match.group(1) if match else text.strip()[:200]
    return text.strip()[:200]
