"""Remove prompt artifacts accidentally echoed by translation models."""

import re


_TERM_LINE = re.compile(r"^\s*<?[A-Za-z][A-Za-z0-9 _-]*\s*->\s*[^<>\n]+\s*$")
_RULE_LINE = re.compile(
    r"^\s*(?:规则|Rules?)\s*[:：]\s*$",
    re.IGNORECASE,
)
_NUMBERED_RULE_LINE = re.compile(r"^\s*\d+[.、]\s+.*$")
_CONTENT_MARKER = re.compile(
    r"^\s*(?:(?:需要|要)?翻译的内容|内容|Content(?:\s+to\s+translate)?)\s*[:：]\s*(.*)$",
    re.IGNORECASE,
)
_PROMPT_LINE = re.compile(
    r"^\s*(?:Translate\s+the\s+following|You\s+are\s+a\s+professional\s+technical\s+translator)",
    re.IGNORECASE,
)


def _strip_code_fence(lines):
    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        return lines[1:-1]
    return lines


def sanitize_translated_html(content):
    """Remove echoed translation prompts while preserving legitimate text.

    A prompt echo is only removed when a term run (and optional rules) is
    followed by a translation-content marker. This avoids deleting code or
    normal prose that happens to contain an arrow.
    """
    lines = content.replace("\r\n", "\n").split("\n")
    lines = _strip_code_fence(lines)
    cleaned = []
    i = 0

    while i < len(lines):
        if (
            not lines[i].strip()
            or _PROMPT_LINE.match(lines[i])
            or _RULE_LINE.match(lines[i])
            or _NUMBERED_RULE_LINE.match(lines[i])
            or _TERM_LINE.match(lines[i])
        ):
            j = i
            term_count = 0
            marker_index = None
            while j < len(lines):
                line = lines[j]
                marker = _CONTENT_MARKER.match(line)
                if marker:
                    if term_count >= 1:
                        marker_index = j
                    break
                if _TERM_LINE.match(line):
                    term_count += 1
                    j += 1
                elif (
                    not line.strip()
                    or _PROMPT_LINE.match(line)
                    or _RULE_LINE.match(line)
                    or _NUMBERED_RULE_LINE.match(line)
                ):
                    j += 1
                else:
                    break

            if marker_index is not None:
                marker = _CONTENT_MARKER.match(lines[marker_index])
                remainder = marker.group(1).strip()
                if remainder:
                    cleaned.append(remainder)
                i = marker_index + 1
                continue

        cleaned.append(lines[i])
        i += 1

    return "\n".join(cleaned).strip()
