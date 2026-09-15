"""Echo backend — no model, no network.

Exists so the orchestrator can be exercised end to end: it returns a well-formed
result without touching a provider. Useful for testing the phases, the state
machine, and the prompt rendering.
"""

import time

from .base import AgentBackend, AgentResult


class EchoBackend(AgentBackend):
    name = "echo"

    def run(self, request):
        started = time.time()
        return AgentResult(
            backend=self.name,
            model="none",
            unsupported=(["extra[argv] (no model is called)"]
                         if (request.extra or {}).get("argv") else []),
            text="echo backend: no model was called",
            structured={
                "summary": "Echo backend — nothing was implemented.",
                "files_changed": [],
                "notes": "Run with a real backend to do actual work.",
            },
            turns=0,
            duration_s=time.time() - started,
        )
