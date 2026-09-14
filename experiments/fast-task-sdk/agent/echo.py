"""Echo backend — no model, no network, no cost.

Exists so the orchestrator can be exercised end to end for free: it returns a
well-formed result without touching a provider. Useful for testing the phases,
the state machine, and the prompt rendering without spending anything.
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
            text="echo backend: no model was called",
            structured={
                "summary": "Echo backend — nothing was implemented.",
                "files_changed": [],
                "notes": "Run with a real backend to do actual work.",
            },
            turns=0,
            cost_usd=0.0,
            input_tokens=0,
            output_tokens=0,
            duration_s=time.time() - started,
        )
