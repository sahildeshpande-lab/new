import calendar
import re
from datetime import date
from difflib import SequenceMatcher
from typing import Any


MONTH_PATTERN = re.compile(
    r"\b("
    + "|".join(month.lower() for month in calendar.month_name[1:])
    + r"|"
    + "|".join(month.lower() for month in calendar.month_abbr[1:])
    + r")\b",
    re.IGNORECASE,
)
DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def match_report(question: str, metadata: dict[str, Any]) -> tuple[str | None, list[str]]:
    normalized_question = normalize_text(question)
    matches: list[tuple[float, str]] = []

    for report_id, report in metadata["reports"].items():
        phrases = [report["name"], report["description"], *report.get("natural_language_aliases", [])]
        best_score = 0.0
        for phrase in phrases:
            normalized_phrase = normalize_text(phrase)
            if normalized_phrase and normalized_phrase in normalized_question:
                best_score = max(best_score, 1.0)
            else:
                best_score = max(best_score, SequenceMatcher(None, normalized_question, normalized_phrase).ratio())

        keyword_hits = sum(1 for word in normalize_text(report["name"]).split() if word in normalized_question)
        best_score += min(keyword_hits * 0.08, 0.24)
        matches.append((best_score, report_id))

    matches.sort(reverse=True)
    if not matches or matches[0][0] < 0.56:
        return None, ["Unsupported report. Please ask for Attendance, Timesheet, Team Lead Timesheet, or HR Timesheet reports."]

    if len(matches) > 1 and matches[0][0] - matches[1][0] < 0.06:
        top_names = [metadata["reports"][report_id]["name"] for _, report_id in matches[:2]]
        return None, [f"Ambiguous report request. Please choose one of: {', '.join(top_names)}."]

    return matches[0][1], []


def extract_filters(question: str, allowed_filters: list[str], today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    filters: dict[str, Any] = {}
    text = question.strip()
    normalized = normalize_text(text)

    dates = DATE_PATTERN.findall(text)
    if "date_from" in allowed_filters and dates:
        filters["date_from"] = dates[0]
    if "date_to" in allowed_filters and len(dates) > 1:
        filters["date_to"] = dates[1]

    if "date_from" in allowed_filters and "date_to" in allowed_filters:
        if "today" in normalized:
            filters.setdefault("date_from", today.isoformat())
            filters.setdefault("date_to", today.isoformat())
        elif "this month" in normalized:
            first_day = today.replace(day=1)
            last_day = today.replace(day=calendar.monthrange(today.year, today.month)[1])
            filters.setdefault("date_from", first_day.isoformat())
            filters.setdefault("date_to", last_day.isoformat())
        else:
            month_match = MONTH_PATTERN.search(text)
            if month_match and "date_from" not in filters:
                month_token = month_match.group(1).lower()
                month_number = _month_number(month_token)
                if month_number:
                    year_match = re.search(r"\b(20\d{2})\b", text)
                    year = int(year_match.group(1)) if year_match else today.year
                    filters["date_from"] = date(year, month_number, 1).isoformat()
                    filters["date_to"] = date(year, month_number, calendar.monthrange(year, month_number)[1]).isoformat()

    filter_stop = r"(?=\s+(?:from|to|for|status|client|work\s+type|role\s+type|project|user|employee|mfg\s+type|manufacturing\s+type|project\s+type)\b|$)"
    filter_patterns = {
        "user_id": r"\buser(?:\s+id)?\s*[:#-]?\s*(\d+)\b",
        "team_leader_id": r"\b(?:team\s+leader|tl)(?:\s+id)?\s*[:#-]?\s*(\d+)\b",
        "project_id": r"\bproject(?:\s+id)?\s*[:#-]?\s*(\d+)\b",
        "status": rf"\bstatus\s*[:=-]?\s*([a-zA-Z _-]+?){filter_stop}",
        "client": rf"\bclient\s*[:=-]?\s*([a-zA-Z0-9 _-]+?){filter_stop}",
        "work_type": rf"\bwork\s+type\s*[:=-]?\s*([a-zA-Z0-9 _-]+?){filter_stop}",
        "role_type": rf"\brole\s+type\s*[:=-]?\s*([a-zA-Z0-9 _-]+?){filter_stop}",
        "project_mfg_type": rf"\b(?:mfg\s+type|manufacturing\s+type|project\s+type)\s*[:=-]?\s*([a-zA-Z0-9 _-]+?){filter_stop}",
    }
    for filter_name, pattern in filter_patterns.items():
        if filter_name not in allowed_filters:
            continue
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if filter_name.endswith("_id") or filter_name == "user_id":
                filters[filter_name] = int(value)
            else:
                filters[filter_name] = value

    if "employee_name" in allowed_filters:
        name_match = re.search(r"\b(?:employee|user)\s+name\s*[:=-]?\s*([a-zA-Z ]+?)(?:\s+from|\s+to|\s+for|$)", text, re.IGNORECASE)
        if name_match:
            filters["employee_name"] = name_match.group(1).strip()

    return filters


def _month_number(token: str) -> int | None:
    token = token.lower()
    month_names = {month.lower(): index for index, month in enumerate(calendar.month_name) if month}
    month_abbrs = {month.lower(): index for index, month in enumerate(calendar.month_abbr) if month}
    return month_names.get(token) or month_abbrs.get(token)
