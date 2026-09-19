"""The document processing worker.

One background thread processes one document at a time, in the order the documents were
queued. A single worker keeps the heavy native libraries (PyMuPDF, ONNX Runtime) on one
thread and keeps the API responsive: request handlers only ever enqueue.

The queue lives in memory and the state of every document lives in the database, so a
restart in the middle of a run is recoverable: documents left `queued` or `processing` are
put back on the queue when the application starts.
"""

from __future__ import annotations

import logging
import queue
import threading

from app.db import SessionLocal
from app.models import Document
from app.processing.pipeline import ProcessingError, read_file
from app.segmentation import engine as segmentation_engine
from app.services import analysis
from app.services import segmentation as segmentation_service
from app.services.locks import WORKSPACE_LOCK
from app.storage import absolute_storage_path

logger = logging.getLogger("claimai.worker")

_SHUTDOWN = None  # sentinel put on the queue to stop the thread


class ProcessingWorker:
    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lifecycle = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._current: str | None = None
        self._processed = 0
        self._failed = 0
        self._accepting = True

    # --- lifecycle ----------------------------------------------------------------------

    def start(self, *, recover: bool = True) -> None:
        with self._lifecycle:
            self._accepting = True
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="claimai-processing", daemon=True)
            self._thread.start()
            logger.info("Processing worker started")
        if recover:
            self.recover()

    def recover(self) -> list[str]:
        """Put documents interrupted by a restart back on the queue."""
        try:
            with SessionLocal() as session:
                document_ids = analysis.requeue_unfinished(session)
        except Exception as exc:  # noqa: BLE001 — recovery must never stop the application
            logger.warning("Could not requeue unfinished documents: %s", exc)
            return []
        if document_ids:
            self.submit(document_ids)
        return document_ids

    def stop(self, timeout: float = 20.0) -> None:
        with self._lifecycle:
            thread, self._thread = self._thread, None
            self._accepting = False
            if thread is None:
                return
            self._queue.put(_SHUTDOWN)
        thread.join(timeout=timeout)
        if thread.is_alive():
            logger.warning("Processing worker did not stop within %.0fs", timeout)
        else:
            logger.info("Processing worker stopped")

    # --- queue --------------------------------------------------------------------------

    def submit(self, document_ids: list[str] | tuple[str, ...]) -> int:
        if not document_ids:
            return 0
        if not self._accepting:
            logger.warning("Worker is not accepting work; %d document(s) stay queued in the database", len(document_ids))
            return 0
        self._idle.clear()
        for document_id in document_ids:
            self._queue.put(document_id)
        return len(document_ids)

    def drain(self) -> int:
        """Discard queued work (used before the workspace is rebuilt)."""
        removed = 0
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            self._queue.task_done()
            if item is _SHUTDOWN:
                self._queue.put(_SHUTDOWN)
                break
            removed += 1
        if self._queue.empty():
            self._idle.set()
        return removed

    def wait_idle(self, timeout: float = 120.0) -> bool:
        """Block until the queue is empty and nothing is being processed."""
        return self._idle.wait(timeout=timeout)

    def stats(self) -> dict:
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "queue_depth": self._queue.qsize(),
            "current_document_id": self._current,
            "processed": self._processed,
            "failed": self._failed,
        }

    # --- the loop -----------------------------------------------------------------------

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _SHUTDOWN:
                    return
                self._current = item
                self.process_document(item)
            except Exception:  # noqa: BLE001 — the worker must survive any single document
                logger.exception("Unexpected failure while processing document %s", item)
            finally:
                self._current = None
                self._queue.task_done()
                if self._queue.empty():
                    self._idle.set()

    def process_document(self, document_id: str) -> None:
        """Run the pipeline for one document and store the outcome.

        Runs under a shared workspace lock, so a demo reset cannot delete the tables or the
        stored files midway. A document that disappeared (because the workspace was reset)
        is skipped quietly.
        """
        with WORKSPACE_LOCK.shared():
            with SessionLocal() as session:
                document = session.get(Document, document_id)
                if document is None:
                    logger.info("Document %s is gone; nothing to process", document_id)
                    return
                if document.processing_status == analysis.STATUS_PROCESSED:
                    return
                claim_id = document.claim_id
                path = absolute_storage_path(document.storage_path)
                analysis.mark_started(session, document)
                try:
                    # The file is read once — rendered, OCR'd and measured — and then grouped into
                    # the documents it holds. A file holding one document yields one group, which
                    # is the path every upload has always taken.
                    read = read_file(
                        path,
                        content_type=document.content_type,
                        sha256=document.sha256,
                        claim_id=claim_id,
                        render_key=document.source_file_id,
                        stage=lambda name: analysis.set_stage(session, document, name),
                    )
                    segments = segmentation_engine.segment(read)
                except ProcessingError as exc:
                    logger.warning("Document %s could not be processed: %s", document.original_filename, exc)
                    analysis.mark_failed(session, document, str(exc))
                    self._failed += 1
                except Exception as exc:  # noqa: BLE001 — one document failing is not the claim failing
                    logger.exception("Processing failed for %s", document.original_filename)
                    analysis.mark_failed(session, document, f"{type(exc).__name__}: {exc}")
                    self._failed += 1
                else:
                    stored = segmentation_service.store(session, document, read, segments)
                    self._processed += 1
                    if len(stored) > 1:
                        logger.info(
                            "%s held %d documents", document.original_filename, len(stored)
                        )
                analysis.finish_claim_if_done(session, claim_id)


_worker: ProcessingWorker | None = None
_worker_lock = threading.Lock()


def get_worker() -> ProcessingWorker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = ProcessingWorker()
        return _worker
