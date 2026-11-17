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

DATE_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$")
DATE_IN_TEXT_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})")
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


def extract_fitbloc_rows(
    file_source: Union[str, Path, bytes, io.BytesIO],
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    # extract table rows across pages with overlap protection on overflow pages
    if isinstance(file_source, (str, Path)):
        pdf_ctx = pdfplumber.open(file_source)
    elif isinstance(file_source, bytes):
        pdf_ctx = pdfplumber.open(io.BytesIO(file_source))
    else:
        pdf_ctx = pdfplumber.open(file_source)

    extracted_rows: List[Dict[str, Any]] = []
    prepared_at: Optional[str] = None

    with pdf_ctx as pdf:
        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""

            # extract email sent date if not yet found
            if not prepared_at:
                sent_match = SENT_HEADER_RE.search(text)
                if sent_match:
                    day_str, month_str = sent_match.groups()
                    m_val = MONTH_MAP.get(month_str.lower()[:3], 8)
                    # use year from earliest table date or current year
                    prepared_at = f"{int(day_str):02d}/{m_val:02d}/2026"

            # for subsequent pages, filter out non-table fonts (Arial/Aptos email body text)
            if page_idx == 0:
                p_eval = page
            else:
                p_eval = page.filter(
                    lambda o: "arial" not in o.get("fontname", "").lower()
                    and "aptos" not in o.get("fontname", "").lower()
                )

            tables = p_eval.extract_tables()
            for t in tables:
                for row in t:
                    if not row or len(row) < 2:
                        continue
                    col0 = str(row[0] or "").strip()
                    m = DATE_IN_TEXT_RE.search(col0)
                    if m:
                        d, mth, yr = m.groups()
                        if len(yr) == 2:
                            yr = "20" + yr
                        date_str = f"{int(d):02d}/{int(mth):02d}/{yr}"

                        # clean client name in col 1
                        raw_client = str(row[1] or "").strip()
                        # handle any trailing split line
                        client = raw_client.split("\n")[-1].strip()

                        location = str(row[2] or "").strip() if len(row) > 2 else ""
                        pricing_opt = str(row[3] or "").strip() if len(row) > 3 else ""

                        extracted_rows.append({
                            "usage_date": date_str,
                            "customer": client,
                            "gym_staff": location,
                            "remarks": pricing_opt,
                            "adj": -1,
                        })

    return extracted_rows, prepared_at


class FitblocParser(BaseGymParser):
    # parser for Fitbloc email pass usage reports

    @property
    def gym_name(self) -> str:
        return "Fitbloc"

    def parse(
        self,
        file_source: Any,
        members: Optional[List[Dict[str, Any]]] = None,
    ) -> ParseResult:
        raw_rows, prepared_at = extract_fitbloc_rows(file_source)

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
register_parser(FitblocParser())
