from __future__ import annotations

import io
import logging
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)


class DocumentLoader:
    SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}

    def load_text(self, filename: str, raw_bytes: bytes) -> str:
        extension = Path(filename).suffix.lower()
        if extension not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file extension: {extension}")

        if extension in {".md", ".txt"}:
            logger.info("Loading plaintext document: %s", filename)
            try:
                return raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                logger.warning("UTF-8 decode failed for %s. Falling back to latin-1.", filename)
                return raw_bytes.decode("latin-1", errors="replace")

        logger.info("Loading PDF document: %s", filename)
        return self._extract_pdf_text(raw_bytes)

    @staticmethod
    def _extract_pdf_text(raw_bytes: bytes) -> str:
        full_text: list[str] = []
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                if text.strip():
                    full_text.append(f"\n[PAGE {page_index}]\n{text}")
        return "\n".join(full_text).strip()
