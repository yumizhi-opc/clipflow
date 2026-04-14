"""UGC/viral pipeline — v2 orchestrator (stub)."""

from __future__ import annotations

from clipflow.pipeline.base import BasePipeline


class UGCPipeline(BasePipeline):
    """v2 UGC pipeline — planned."""

    def _validate(self):
        raise NotImplementedError("UGC pipeline is planned for v2.0")

    def _run_stages(self, on_progress):
        raise NotImplementedError("UGC pipeline is planned for v2.0")
