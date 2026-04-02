from __future__ import annotations

import logging
import re
import uuid

from app.models.schemas import Clause, ParsedDocument

logger = logging.getLogger(__name__)

SECTION_RE = re.compile(r"^###\s+Section\s+(\d+):\s*(.+)$", re.IGNORECASE)
CLAUSE_RE = re.compile(r"^(\d+(?:\.\d+)+)\s+(.*)$")
SUBCLAUSE_RE = re.compile(r"^\s+([a-z]{1,2})[\.)]\s+(.*)$")
REFERENCE_RE = re.compile(r"Section\s+(\d+(?:\.\d+)*(?:\([a-z]\))?)", re.IGNORECASE)


class DocumentParser:
    def parse(self, filename: str, raw_text: str) -> ParsedDocument:
        logger.info("Starting parse for file=%s", filename)
        lines = raw_text.splitlines()
        clauses: list[Clause] = []

        current_section = "0"
        current_section_title = "General"
        current_clause_id: str | None = None
        current_clause_heading: str | None = None
        current_clause_lines: list[str] = []
        current_clause_line_start: int | None = None
        main_clause_for_subitems: str | None = None
        main_clause_expects_subitems = False

        def flush_clause() -> None:
            nonlocal current_clause_id
            nonlocal current_clause_heading
            nonlocal current_clause_lines
            nonlocal current_clause_line_start
            if not current_clause_id or not current_clause_lines:
                return
            text = " ".join(line.strip() for line in current_clause_lines if line.strip()).strip()
            if not text:
                return
            references = REFERENCE_RE.findall(text)
            clauses.append(
                Clause(
                    clause_id=current_clause_id,
                    section_id=current_section,
                    section_title=current_section_title,
                    heading=current_clause_heading,
                    text=text,
                    references=references,
                    line_start=current_clause_line_start,
                )
            )
            current_clause_id = None
            current_clause_heading = None
            current_clause_lines = []
            current_clause_line_start = None

        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue

            section_match = SECTION_RE.match(line.strip())
            if section_match:
                flush_clause()
                current_section = section_match.group(1)
                current_section_title = section_match.group(2).strip()
                main_clause_for_subitems = None
                main_clause_expects_subitems = False
                continue

            clause_match = CLAUSE_RE.match(line.strip())
            if clause_match:
                flush_clause()
                current_clause_id = clause_match.group(1)
                main_clause_for_subitems = current_clause_id
                heading = clause_match.group(2).strip()
                current_clause_heading = heading if heading else None
                current_clause_lines = [heading]
                current_clause_line_start = line_number
                main_clause_expects_subitems = bool(heading.endswith(":"))
                continue

            subclause_match = SUBCLAUSE_RE.match(line)
            if subclause_match and main_clause_for_subitems and main_clause_expects_subitems:
                flush_clause()
                sub_letter = subclause_match.group(1).lower()
                sub_text = subclause_match.group(2).strip()
                current_clause_id = f"{main_clause_for_subitems}({sub_letter})"
                current_clause_heading = sub_text if sub_text else None
                current_clause_lines = [sub_text]
                current_clause_line_start = line_number
                continue

            if current_clause_id is None:
                # Heading and plain text before first clause.
                current_clause_id = f"{current_section}.0"
                current_clause_heading = "Section Intro"
                current_clause_lines = [line.strip()]
                current_clause_line_start = line_number
            else:
                current_clause_lines.append(line.strip())

        flush_clause()

        parsed = ParsedDocument(
            document_id=str(uuid.uuid4()),
            filename=filename,
            raw_text=raw_text,
            clauses=clauses,
        )
        logger.info(
            "Parsing completed file=%s clauses=%s sections=%s",
            filename,
            len(parsed.clauses),
            len({clause.section_id for clause in parsed.clauses}),
        )
        return parsed
