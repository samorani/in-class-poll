"""Extract the practice problems and their answers from files/practice-problems.pdf.

Each problem becomes a dict:
    id          "4.MC7"
    chapter     4
    chapter_title "Tracking Changes with Git"
    difficulty  "Easy" | "Medium" | "Hard" | "Extra hard"
    type        "MC" | "SA"
    text        the question text
    options     [{"letter": "a", "text": "..."}, ...]   (MC only)
    correct     "c"                                      (MC only)
    answer      the full answer text from the answers section
"""
import json
import os
import re

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
PDF_PATH = os.path.join(HERE, "files", "practice-problems.pdf")
CACHE_PATH = os.path.join(HERE, "files", "problems.json")

PROBLEM_RE = re.compile(r"^(\d+)\.(MC|SA)(\d+)\.\s*(.*)$")
OPTION_RE = re.compile(r"^\(([a-d])\)\s*(.*)$")
CHAPTER_RE = re.compile(r"^Chapter (\d+): (.+)$")
DIFFICULTIES = {"Easy", "Medium", "Hard", "Extra hard"}


def _pages(pdf_path):
    doc = pymupdf.open(pdf_path)
    return [page.get_text() for page in doc]


def _clean_lines(page_text):
    """Drop the trailing page number and blank lines."""
    lines = [ln.rstrip() for ln in page_text.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    if lines and lines[-1].strip().isdigit():
        lines.pop()
    return lines


def _join(parts):
    """Join wrapped lines, repairing words hyphenated at a line break."""
    out = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not out:
            out = part
        elif out.endswith("-") and part[:1].islower() and not out.endswith(" -"):
            out = out[:-1] + part
        else:
            out = out + " " + part
    return out


def parse(pdf_path=PDF_PATH):
    pages = _pages(pdf_path)

    # Find the page where the answers section begins (a page whose first line is "Answers").
    answers_start = next(
        i for i, p in enumerate(pages) if _clean_lines(p) and _clean_lines(p)[0] == "Answers"
    )
    # Problems begin on the first page whose first line is a chapter heading.
    problems_start = next(
        i for i, p in enumerate(pages)
        if _clean_lines(p) and CHAPTER_RE.match(_clean_lines(p)[0]) and i < answers_start
    )

    problem_lines = []
    for p in pages[problems_start:answers_start]:
        problem_lines.extend(_clean_lines(p))
    answer_lines = []
    for p in pages[answers_start:]:
        answer_lines.extend(_clean_lines(p))

    # ---- problems ----
    problems = []
    chapter, chapter_title, difficulty = None, None, None
    current = None  # the problem being accumulated
    text_parts, options = [], []

    def flush():
        if current is None:
            return
        current["text"] = _join(text_parts)
        if current["type"] == "MC":
            current["options"] = [
                {"letter": letter, "text": _join(parts)} for letter, parts in options
            ]
        problems.append(current)

    for line in problem_lines:
        m = CHAPTER_RE.match(line)
        if m:
            flush(); current = None
            chapter, chapter_title = int(m.group(1)), m.group(2).strip()
            continue
        if line.strip() in DIFFICULTIES:
            flush(); current = None
            difficulty = line.strip()
            continue
        m = PROBLEM_RE.match(line)
        if m:
            flush()
            current = {
                "id": f"{m.group(1)}.{m.group(2)}{m.group(3)}",
                "chapter": chapter,
                "chapter_title": chapter_title,
                "difficulty": difficulty,
                "type": m.group(2),
            }
            text_parts, options = [m.group(4)], []
            continue
        if current is None:
            continue
        m = OPTION_RE.match(line)
        if m and current["type"] == "MC":
            options.append((m.group(1), [m.group(2)]))
            continue
        if options:
            options[-1][1].append(line)
        else:
            text_parts.append(line)
    flush()

    # ---- answers ----
    answers = {}
    aid, parts = None, []
    for line in answer_lines:
        if line.strip() == "Answers" or CHAPTER_RE.match(line):
            continue
        m = PROBLEM_RE.match(line)
        if m:
            if aid:
                answers[aid] = _join(parts)
            aid = f"{m.group(1)}.{m.group(2)}{m.group(3)}"
            parts = [m.group(4)]
        elif aid:
            parts.append(line)
    if aid:
        answers[aid] = _join(parts)

    for p in problems:
        p["answer"] = answers.get(p["id"], "")
        if p["type"] == "MC":
            m = re.match(r"^\(([a-d])\)", p["answer"])
            p["correct"] = m.group(1) if m else None
    return problems


def load(pdf_path=PDF_PATH, cache_path=CACHE_PATH):
    """Return the problems, parsing the PDF (and caching to JSON) if needed."""
    if os.path.exists(cache_path) and os.path.getmtime(cache_path) >= os.path.getmtime(pdf_path):
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    problems = parse(pdf_path)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(problems, f, indent=2, ensure_ascii=False)
    except OSError:
        pass  # a read-only filesystem is fine; we just parse again next start
    return problems


if __name__ == "__main__":
    ps = parse()
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(ps, f, indent=2, ensure_ascii=False)
    print(f"{len(ps)} problems written to {CACHE_PATH}")
