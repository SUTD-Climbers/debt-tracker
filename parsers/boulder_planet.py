from datetime import datetime
import io
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
import pdfplumber

from parsers.base import BaseGymParser, ParseResult
from parsers.climbers_sutd import parse_day_first_date
from parsers.registry import register_parser
from services.deduplication import build_row_key
from services.normalisation import clean_name, resolve_canonical_name

DATE_LINE_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$")
SENT_HEADER_RE = re.compile(r"Sent:\s+[A-Za-z]+,?\s+(\d{1,2})\s+([A-Za-z]+)(?:\s+at\s+.*)?", re.IGNORECASE)

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

END_MARKERS = [
    "——————",
    "------",
    "balance passes",
    "best regards",
    "on tue,",
    "on wed,",
    "on thu,",
    "on fri,",
    "on sat,",
    "on sun,",
    "on mon,",
    "sutd climbers club has updated",
]


def extract_boulder_planet_rows(
    file_source: Union[str, Path, bytes, io.BytesIO],
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if isinstance(file_source, (str, Path)):
        pdf_ctx = pdfplumber.open(file_source)
    elif isinstance(file_source, bytes):
        pdf_ctx = pdfplumber.open(io.BytesIO(file_source))
    else:
        pdf_ctx = pdfplumber.open(file_source)

    extracted_rows: List[Dict[str, Any]] = []
    prepared_at: Optional[str] = None
    current_date: Optional[str] = None
    started = False
    ended = False

    with pdf_ctx as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""

            # extract email sent date if not yet found
            if not prepared_at:
                sent_match = SENT_HEADER_RE.search(text)
                if sent_match:
                    day_str, month_str = sent_match.groups()
                    m_val = MONTH_MAP.get(month_str.lower()[:3], 10)
                    prepared_at = f"{int(day_str):02d}/{m_val:02d}/2026"

            lines = [l.strip() for l in text.split("\n") if l.strip()]
            for line in lines:
                lower_line = line.lower()

                # check start trigger
                if "as follows" in lower_line or "the usage are" in lower_line:
                    started = True
                    continue

                if not started:
                    # fallback: if we hit a date line after the header, start anyway
                    if DATE_LINE_RE.match(line) and not ("sent:" in lower_line or "to:" in lower_line or "from:" in lower_line):
                        started = True
                    else:
                        continue

                # check end trigger
                if any(marker in lower_line for marker in END_MARKERS):
                    ended = True
                    break

                # check if line is a date header
                m = DATE_LINE_RE.match(line)
                if m:
                    d, mth, yr = m.groups()
                    if len(yr) == 2:
                        yr = "20" + yr
                    current_date = f"{int(d):02d}/{int(mth):02d}/{yr}"
                elif current_date:
                    # filter out extraneous text or email artifacts
                    if (
                        line.startswith("http")
                        or "@" in line
                        or line.lower().startswith("page ")
                        or len(line) <= 1
                    ):
                        continue

                    extracted_rows.append({
                        "usage_date": current_date,
                        "customer": line,
                        "gym_staff": "",
                        "remarks": "",
                        "adj": -1,
                    })

            if ended:
                break

    return extracted_rows, prepared_at


class BoulderPlanetParser(BaseGymParser):
    # parser for Boulder Planet email pass usage reports

    @property
    def gym_name(self) -> str:
        return "Boulder Planet"

    def parse(
        self,
        file_source: Any,
        members: Optional[List[Dict[str, Any]]] = None,
    ) -> ParseResult:
        raw_rows, prepared_at = extract_boulder_planet_rows(file_source)

        cleaned_records: List[Dict[str, Any]] = []
        for r in raw_rows:
            usage_date = r.get("usage_date", "")
            raw_cust = r.get("customer", "")
            staff = r.get("gym_staff", "")
            remarks = r.get("remarks", "")
            adj = int(r.get("adj", -1))

            norm_cust = resolve_canonical_name(raw_cust, members) if raw_cust else ""
            norm_staff = clean_name(staff) if staff else ""

            row_key = build_row_key(
                usage_date=usage_date,
                customer=norm_cust,
                adj=adj,
                gym_staff=norm_staff,
                remarks=remarks,
                members=members,
            )

            cleaned_records.append({
                "usage_date": usage_date,
                "type": "Usage",
                "customer": norm_cust,
                "gym_staff": norm_staff,
                "remarks": remarks,
                "expires": "",
                "adj": adj,
                "row_kind": "usage",
                "row_key": row_key,
            })

        df = pd.DataFrame(cleaned_records)

        earliest_date = None
        latest_date = None
        if not df.empty:
            parsed_dates = [parse_day_first_date(d) for d in df["usage_date"]]
            valid_dates = [d for d in parsed_dates if d is not None]
            if valid_dates:
                earliest_date = min(valid_dates).strftime("%d/%m/%Y")
                latest_date = max(valid_dates).strftime("%d/%m/%Y")

        return ParseResult(
            gym=self.gym_name,
            report_prepared_at=prepared_at or latest_date,
            total_dates_found=len(df),
            rows_parsed_count=len(df),
            reconciliation_passed=True,
            data=df,
            failed_rows=[],
            earliest_date=earliest_date,
            latest_date=latest_date,
        )


# register in global parser registry
register_parser(BoulderPlanetParser())
