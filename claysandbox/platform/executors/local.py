"""Local executor: runs ``RunRequest``s in this process, up to ``max_parallel`` at once.

Threads, not processes: a run spends its time waiting on Bedrock and on MCP subprocesses, so
threads are enough, and they keep the registry and the store in one place. The executor only
executes; infra retries and the eval cap are the service's job (it decides from each
``RunStatus``), the same split the Fargate executor uses.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor

from pydantic import BaseModel, Field

from claysandbox.contracts.execution import RunRequest, RunStatus
from claysandbox.contracts.registry import register

log = logging.getLogger("claysandbox.executor.local")


@register("executor", "local")
class LocalExecutor:
    name = "local"
    version = "1"

    class Params(BaseModel):
        max_parallel: int = Field(default=2, ge=1, le=16)

    def __init__(
        self, params: dict | None = None, run: Callable[[RunRequest], RunStatus] | None = None
    ) -> None:
        self.params = self.Params(**(params or {}))
        self._run = run  # injected by the service (the worker bound to a store)
        self._pool = ThreadPoolExecutor(
            max_workers=self.params.max_parallel, thread_name_prefix="clay-run"
        )
        self._futures: dict[str, tuple[RunRequest, Future[RunStatus]]] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    def bind(self, run: Callable[[RunRequest], RunStatus]) -> LocalExecutor:
        self._run = run
        return self

    def submit(self, requests: Iterable[RunRequest]) -> None:
        if self._run is None:
            raise RuntimeError("LocalExecutor has no run function; call bind() first")
        for req in requests:
            with self._lock:
                if req.eval_id in self._cancelled:
                    continue
                self._futures[req.run_id] = (req, self._pool.submit(self._safe_run, req))

    def _safe_run(self, req: RunRequest) -> RunStatus:
        try:
            return self._run(req)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001  a crashed worker is an executor failure
            log.exception("run %s crashed", req.run_id)
            kind = getattr(exc, "kind", None) or "executor_failure"
            # Configuration problems will fail again: exclude instead of retrying.
            state = "infra_excluded" if type(exc).__name__ == "ConfigError" else "infra_retry"
            return RunStatus(
                run_id=req.run_id,
                eval_id=req.eval_id,
                state=state,
                error_kind=str(kind),
                message=str(exc)[:500],
            )

    def poll(self) -> list[RunStatus]:
        done: list[RunStatus] = []
        with self._lock:
            for run_id, (_req, fut) in list(self._futures.items()):
                if fut.done():
                    done.append(fut.result())
                    del self._futures[run_id]
        return done

    def pending(self) -> int:
        with self._lock:
            return len(self._futures)

    def cancel(self, eval_id: str) -> None:
        with self._lock:
            self._cancelled.add(eval_id)
            for run_id, (req, fut) in list(self._futures.items()):
                if req.eval_id == eval_id and fut.cancel():
                    del self._futures[run_id]

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)
