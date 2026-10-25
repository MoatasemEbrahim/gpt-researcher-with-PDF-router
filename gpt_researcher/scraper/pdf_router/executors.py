"""Process pools for the router: one set per process, created on first use, shared by every PDF.

- shared_pool(): stage 1 (signals, classify, tiers 0-1) and tier 2. Processes, not
  threads: PyMuPDF isn't thread-safe and the work is CPU-bound. Shared, because the
  scraper already runs many URLs at once; a pool per PDF would multiply processes.
- docling_pool(): tier 3, with a warm DocumentConverter per worker. docling_slot()
  caps running Docling jobs across all PDFs, so a job's timeout starts when it runs,
  not while it waits behind another PDF's job.
- docling_waiters(): threads that only wait on Docling jobs (slot, timeout, reset),
  so route_pdf() can wait on Docling and the shared pool together.

Shared workers are replaced after PDF_ROUTER_WORKER_MAX_TASKS tasks (max_tasks_per_child),
which releases memory that Python and the native libraries never hand back. Docling workers
aren't: a restart costs 8-20 s, and that pool has its own reset on timeout.

Workers use "spawn" on every platform: fork is unsafe once the scraper's threads run.
A spawned worker re-imports the gpt_researcher package (~1.2 s), once per worker.
"""

import multiprocessing
import threading
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor

from . import settings

_lock = threading.Lock()
_shared: Executor | None = None
_docling: Executor | None = None
_docling_slot: threading.Semaphore | None = None
_docling_waiters: Executor | None = None


def shared_pool() -> Executor:
    global _shared
    with _lock:
        if _shared is None:
            _shared = ProcessPoolExecutor(
                max_workers=settings.max_workers(),
                mp_context=multiprocessing.get_context("spawn"),
                max_tasks_per_child=settings.worker_max_tasks(),
            )
        return _shared


def docling_pool() -> Executor:
    global _docling
    with _lock:
        if _docling is None:
            _docling = ProcessPoolExecutor(
                max_workers=settings.docling_concurrency(),
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_warm_docling,
            )
        return _docling


def docling_slot() -> threading.Semaphore:
    global _docling_slot
    with _lock:
        if _docling_slot is None:
            _docling_slot = threading.Semaphore(settings.docling_concurrency())
        return _docling_slot


def docling_waiters() -> Executor:
    global _docling_waiters
    with _lock:
        if _docling_waiters is None:
            _docling_waiters = ThreadPoolExecutor(max_workers=16, thread_name_prefix="pdf-router-docling")
        return _docling_waiters


def reset_shared_pool(pool: Executor) -> None:
    """Drop a broken shared pool (a worker crashed); the next call creates a new one."""
    global _shared
    with _lock:
        if _shared is pool:
            _shared = None
    _kill(pool)


def reset_docling_pool(pool: Executor) -> None:
    """Stop a Docling pool whose job timed out; the next call creates a new one."""
    global _docling
    with _lock:
        if _docling is pool:
            _docling = None
    _kill(pool)


def shutdown() -> None:
    """Stop every pool (tests, or a clean process exit)."""
    global _shared, _docling, _docling_waiters
    with _lock:
        pools = [_shared, _docling, _docling_waiters]
        _shared = _docling = _docling_waiters = None
    for pool in pools:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)


def _kill(pool: Executor) -> None:
    # A running task can't be cancelled through its future, so end the worker
    # processes. _processes is private: the standard library has no public way.
    processes = list((getattr(pool, "_processes", None) or {}).values())  # empty for a thread pool
    pool.shutdown(wait=False, cancel_futures=True)
    for process in processes:
        process.terminate()


def _warm_docling() -> None:
    """Worker initializer: start Docling's converter before the first job (~8 s or more)."""
    from .backends.docling import _get_converter

    _get_converter()
