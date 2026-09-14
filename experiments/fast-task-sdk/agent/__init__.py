"""Backend registry — the one place a provider is named.

The orchestrator imports `get_backend` and the types from `.base`; it never
imports a provider module. Adding a provider is a new module plus a row here.

Backend modules are imported lazily so a missing optional dependency (the Claude
SDK, say) costs nothing until that backend is actually selected.
"""

from .base import (  # noqa: F401  — re-exported as the public seam
    AgentBackend,
    AgentRequest,
    AgentResult,
    extract_last_json_block,
    tools_for,
)

_REGISTRY = {
    "claude-sdk": (".claude_sdk", "ClaudeSDKBackend"),
    "claude-cli": (".claude_cli", "ClaudeCLIBackend"),
    "echo": (".echo", "EchoBackend"),
}

DEFAULT_BACKEND = "claude-sdk"


def backend_names():
    return list(_REGISTRY)


def get_backend(name):
    """Instantiate a backend by name. Raises ValueError for an unknown name —
    an unavailable one (missing dependency) still constructs, and reports the
    problem through its `available()`."""
    if name not in _REGISTRY:
        raise ValueError("unknown backend %r (known: %s)"
                         % (name, ", ".join(backend_names())))
    module_name, class_name = _REGISTRY[name]
    from importlib import import_module
    module = import_module(module_name, package=__name__)
    return getattr(module, class_name)()


def available_backends():
    """[(name, usable, reason)] for every registered backend."""
    rows = []
    for name in backend_names():
        try:
            usable, reason = get_backend(name).available()
        except Exception as e:
            usable, reason = False, "%s: %s" % (type(e).__name__, e)
        rows.append((name, usable, reason))
    return rows
