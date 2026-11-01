# -*- coding: utf-8 -*-
"""gatekit -- detect and solve Akamai interstitial challenges.

The import surface is deliberately lazy: :mod:`gatekit.judges` has no
dependencies at all, so the judgment layer (and its offline tests) works on a
machine without ``curl_cffi`` installed.
"""
from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "judges",
    "detect", "solve", "solve_interstitial", "direct_get",
    "InterstitialClient",
    "classify", "build_snapshot", "compare", "report",
]

_LAZY = {
    "detect": ("interstitial", "detect"),
    "solve": ("interstitial", "solve"),
    "solve_interstitial": ("interstitial", "solve_interstitial"),
    "direct_get": ("interstitial", "direct_get"),
    "InterstitialClient": ("client", "InterstitialClient"),
    "classify": ("inventory", "classify"),
    "build_snapshot": ("inventory", "build_snapshot"),
    "compare": ("inventory", "compare"),
    "report": ("inventory", "report"),
}


def __getattr__(name: str):
    if name == "judges":
        from importlib import import_module
        return import_module(".judges", __name__)
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module
    mod = import_module(f".{target[0]}", __name__)
    return getattr(mod, target[1])
