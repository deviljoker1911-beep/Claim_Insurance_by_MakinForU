"""OCR engines.

Pages without a usable text layer (uploaded photos, scanned images) go through an OCR
engine. Engines are tried in order and every result records which engine produced it, so
a reader can always tell real OCR output from a bundled demo fixture:

  rapidocr      RapidOCR — PP-OCR models on ONNX Runtime. Models ship inside the wheel,
                so it runs offline with no API key and no downloads.
  demo_fixture  Text and geometry captured from the synthetic source document when the
                demo data was generated. It is NOT the output of an OCR engine and is
                labelled as a fixture everywhere it is used. It exists so the demo still
                works on a machine where the OCR extras are not installed.

Heavier engines (Docling, native PaddleOCR) are deliberately not imported here: they
would pull a second, conflicting native stack into the demo process. They belong behind
the same interface in a separate environment.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.processing.types import TextLine, Word

logger = logging.getLogger("claimai.ocr")

ENGINE_RAPIDOCR = "rapidocr"
ENGINE_DEMO_FIXTURE = "demo_fixture"


@dataclass(frozen=True)
class OcrLine:
    text: str
    bbox: tuple[float, float, float, float]  # normalised 0..1, origin top-left
    confidence: float


@dataclass
class OcrPageResult:
    engine: str
    lines: list[OcrLine] = field(default_factory=list)
    note: str | None = None

    @property
    def mean_confidence(self) -> float | None:
        if not self.lines:
            return None
        return round(sum(line.confidence for line in self.lines) / len(self.lines), 4)

    @property
    def min_confidence(self) -> float | None:
        return round(min((line.confidence for line in self.lines), default=0.0), 4) if self.lines else None


class OcrUnavailable(RuntimeError):
    pass


# --- RapidOCR ---------------------------------------------------------------------------


class RapidOcrEngine:
    """RapidOCR (PP-OCR detection + recognition on ONNX Runtime), offline."""

    key = ENGINE_RAPIDOCR
    name = "RapidOCR (PP-OCR, ONNX Runtime)"
    synthetic = False

    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()

    @staticmethod
    def installed() -> bool:
        return find_spec("rapidocr") is not None and find_spec("onnxruntime") is not None

    def _load(self):
        if self._engine is None:
            from rapidocr import RapidOCR

            try:
                self._engine = RapidOCR(params={"Global.log_level": "error"})
            except Exception:  # noqa: BLE001 — older/newer parameter shapes fall back to defaults
                self._engine = RapidOCR()
        return self._engine

    def recognise(self, image: np.ndarray) -> OcrPageResult:
        if not self.installed():
            raise OcrUnavailable("RapidOCR is not installed")
        height, width = image.shape[0], image.shape[1]
        with self._lock:
            engine = self._load()
            result = engine(image)
        lines: list[OcrLine] = []
        boxes = getattr(result, "boxes", None)
        texts = getattr(result, "txts", None) or []
        scores = getattr(result, "scores", None) or []
        if boxes is None:
            return OcrPageResult(engine=self.key, lines=[], note="No text detected")
        for box, text, score in zip(boxes, texts, scores):
            points = np.asarray(box, dtype=float).reshape(-1, 2)
            text = (text or "").strip()
            if not text:
                continue
            lines.append(
                OcrLine(
                    text=text,
                    bbox=(
                        max(0.0, float(points[:, 0].min()) / width),
                        max(0.0, float(points[:, 1].min()) / height),
                        min(1.0, float(points[:, 0].max()) / width),
                        min(1.0, float(points[:, 1].max()) / height),
                    ),
                    confidence=round(float(score), 4),
                )
            )
        lines.sort(key=lambda line: (round(line.bbox[1], 3), line.bbox[0]))
        return OcrPageResult(engine=self.key, lines=lines)


# --- Demo fixtures ----------------------------------------------------------------------


class DemoFixtureEngine:
    """Replays text captured from the synthetic source document at generation time.

    This is demo data, not OCR output. Everything it returns is labelled `demo_fixture`.
    """

    key = ENGINE_DEMO_FIXTURE
    name = "Deterministic demo fixture (not an OCR engine)"
    synthetic = True
    note = "Synthetic demo fixture: text captured from the source document, not OCR output."

    @staticmethod
    def fixtures_dir() -> Path:
        return get_settings().demo_data_dir / "ocr_fixtures"

    @classmethod
    def fixture_path(cls, sha256: str) -> Path:
        return cls.fixtures_dir() / f"{sha256}.json"

    @classmethod
    def has_fixture(cls, sha256: str) -> bool:
        return bool(sha256) and cls.fixture_path(sha256).is_file()

    @classmethod
    def load(cls, sha256: str, page_number: int) -> OcrPageResult:
        path = cls.fixture_path(sha256)
        if not path.is_file():
            raise OcrUnavailable("No demo OCR fixture for this document")
        data = json.loads(path.read_text(encoding="utf-8"))
        for page in data.get("pages", []):
            if int(page.get("page", 0)) != page_number:
                continue
            lines = [
                OcrLine(
                    text=str(entry["text"]),
                    bbox=tuple(float(v) for v in entry["bbox"]),  # type: ignore[arg-type]
                    confidence=float(entry.get("confidence", 0.99)),
                )
                for entry in page.get("lines", [])
                if str(entry.get("text", "")).strip()
            ]
            return OcrPageResult(engine=cls.key, lines=lines, note=cls.note)
        raise OcrUnavailable(f"Demo OCR fixture has no page {page_number}")


@lru_cache
def rapidocr_engine() -> RapidOcrEngine:
    return RapidOcrEngine()


def available_engines() -> list[str]:
    engines = []
    if RapidOcrEngine.installed():
        engines.append(ENGINE_RAPIDOCR)
    engines.append(ENGINE_DEMO_FIXTURE)
    return engines


def recognise_page(image: np.ndarray, *, sha256: str, page_number: int) -> OcrPageResult:
    """Run the first OCR engine that can handle this page.

    Order comes from OCR_ENGINE: `auto` (default) prefers real OCR and falls back to the
    demo fixture; `rapidocr`, `demo_fixture` and `none` pin the behaviour explicitly.
    """
    preference = (get_settings().ocr_engine or "auto").strip().lower()
    if preference == "none":
        raise OcrUnavailable("OCR is disabled (OCR_ENGINE=none)")

    order: list[str]
    if preference == ENGINE_RAPIDOCR:
        order = [ENGINE_RAPIDOCR]
    elif preference == ENGINE_DEMO_FIXTURE:
        order = [ENGINE_DEMO_FIXTURE]
    else:
        order = [ENGINE_RAPIDOCR, ENGINE_DEMO_FIXTURE]

    errors: list[str] = []
    for key in order:
        try:
            if key == ENGINE_RAPIDOCR:
                return rapidocr_engine().recognise(image)
            if key == ENGINE_DEMO_FIXTURE:
                return DemoFixtureEngine.load(sha256, page_number)
        except OcrUnavailable as exc:
            errors.append(f"{key}: {exc}")
        except Exception as exc:  # noqa: BLE001 — a failing engine must not fail the document
            logger.warning("OCR engine %s failed: %s", key, exc)
            errors.append(f"{key}: {type(exc).__name__}: {exc}")
    raise OcrUnavailable("; ".join(errors) or "No OCR engine available")


# --- OCR lines -> text lines ------------------------------------------------------------


def _rows(lines: list[OcrLine]) -> list[list[OcrLine]]:
    """Group OCR boxes that sit side by side on the same row of the page.

    OCR returns one box per run of text, so a two-column layout ("Member Name:" on the
    left, the name on the right) arrives as two boxes. They belong to the same row when
    they overlap vertically and do not overlap horizontally.
    """
    rows: list[list[OcrLine]] = []
    for line in sorted(lines, key=lambda item: (item.bbox[1], item.bbox[0])):
        placed = False
        height = line.bbox[3] - line.bbox[1]
        for row in rows:
            last = row[-1]
            last_height = last.bbox[3] - last.bbox[1]
            overlap = min(line.bbox[3], last.bbox[3]) - max(line.bbox[1], last.bbox[1])
            if overlap < 0.5 * min(height, last_height):
                continue
            horizontal = min(line.bbox[2], last.bbox[2]) - max(line.bbox[0], last.bbox[0])
            if horizontal > 0:  # the two boxes sit above each other, not side by side
                continue
            row.append(line)
            placed = True
            break
        if not placed:
            rows.append([line])
    return [sorted(row, key=lambda item: item.bbox[0]) for row in rows]


def text_lines_from_ocr(result: OcrPageResult, width: float, height: float) -> list[TextLine]:
    """Turn OCR boxes into page-space text lines.

    OCR reports a box per run of text, so word boxes inside a run are apportioned by
    character width; they are precise enough to point a reviewer at the right place on the
    page. Runs that sit side by side become columns of one line, separated by a wide gap,
    so label/value extraction sees "Member Name:  Rajesh Sharma" as it appears on the page.
    Every field extracted this way records `ocr` as its method.
    """
    lines: list[TextLine] = []
    for row in _rows(result.lines):
        row_words: list[Word] = []
        row_separators: list[bool] = []  # True where a column break precedes the word
        for index, entry in enumerate(row):
            words = _entry_words(entry, width, height)
            if not words:
                continue
            for position, word in enumerate(words):
                row_words.append(word)
                row_separators.append(position == 0 and bool(index))
        if not row_words:
            continue
        text_parts: list[str] = []
        spans: list[tuple[int, int]] = []
        cursor = 0
        for position, word in enumerate(row_words):
            if position:
                separator = "  " if row_separators[position] else " "
                text_parts.append(separator)
                cursor += len(separator)
            spans.append((cursor, cursor + len(word.text)))
            text_parts.append(word.text)
            cursor += len(word.text)
        box = (
            min(word.bbox[0] for word in row_words),
            min(word.bbox[1] for word in row_words),
            max(word.bbox[2] for word in row_words),
            max(word.bbox[3] for word in row_words),
        )
        lines.append(TextLine(text="".join(text_parts), words=row_words, spans=spans, bbox=box))
    return lines


def _entry_words(entry: OcrLine, width: float, height: float) -> list[Word]:
    """Split one OCR box into words, apportioning its box by character width."""
    x0, y0, x1, y1 = (
        entry.bbox[0] * width,
        entry.bbox[1] * height,
        entry.bbox[2] * width,
        entry.bbox[3] * height,
    )
    tokens = [token for token in entry.text.split(" ") if token]
    if not tokens:
        return []
    span_width = max(x1 - x0, 1.0)
    characters = sum(len(token) for token in tokens) + max(len(tokens) - 1, 0)
    per_char = span_width / max(characters, 1)
    words: list[Word] = []
    cursor = x0
    for token in tokens:
        token_width = per_char * len(token)
        words.append(
            Word(
                text=token,
                bbox=(cursor, y0, min(cursor + token_width, x1), y1),
                confidence=entry.confidence,
                baseline=y1,
            )
        )
        cursor += token_width + per_char
    return words
