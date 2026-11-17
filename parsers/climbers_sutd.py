from datetime import datetime
import io
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
import pdfplumber

from parsers.base import BaseGymParser, ParseResult
from parsers.registry import register_parser
from services.deduplication import build_row_key
from services.normalisation import clean_name, resolve_canonical_name

# column start x coordinates
COLUMN_ANCHORS: List[Tuple[str, float]] = [
    ("usage_date", 52.5),
    ("type", 123.2),
    ("customer", 193.9),
    ("gym_staff", 264.6),
    ("remarks", 335.3),
    ("expires", 406.0),
    ("adj", 476.7),
]

DATE_PATTERN = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
FOOTER_PATTERN = re.compile(
    r"Report prepared on\s+([A-Za-z]+,\s+\d{1,2}/\d{1,2}/\d{4}\s+[\d:]+\s*(?:AM|PM)?)",
    re.IGNORECASE,
)


def parse_day_first_date(date_str: str) -> Optional[datetime]:
    # parse day-first date with no zero padding explicitly
    cleaned = date_str.strip()
    parts = cleaned.split("/")
    if len(parts) != 3:
        return None
    try:
        day = int(parts[0])
        month = int(parts[1])
        year = int(parts[2])
        return datetime(year, month, day)
    except (ValueError, TypeError):
        return None


# layer a: pdf extraction to elements with coordinates
def extract_pdf_elements(
    file_source: Union[str, Path, bytes, io.BytesIO],
) -> List[Dict[str, Any]]:
    # extract character elements and text from pdf using pdfplumber
    if isinstance(file_source, (str, Path)):
        pdf_ctx = pdfplumber.open(file_source)
    elif isinstance(file_source, bytes):
        pdf_ctx = pdfplumber.open(io.BytesIO(file_source))
    else:
        pdf_ctx = pdfplumber.open(file_source)

    pages_data: List[Dict[str, Any]] = []
    with pdf_ctx as pdf:
        if len(pdf.pages) == 0:
            return pages_data

        for page_idx, page in enumerate(pdf.pages):
            chars = page.chars
            text = page.extract_text() or ""
            pages_data.append({
                "page_idx": page_idx,
                "width": page.width,
                "height": page.height,
                "chars": chars,
                "text": text,
            })

    return pages_data


# layer b: elements to raw rows (pure function)
def elements_to_raw_rows(
    pages_data: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str], int]:
    # process page characters into structured raw rows via coordinate anchors
    raw_rows: List[Dict[str, Any]] = []
    failed_rows: List[Dict[str, Any]] = []
    report_prepared_at: Optional[str] = None
    total_dates_found = 0

    for page in pages_data:
        page_idx = page["page_idx"]
        chars = page.get("chars", [])

        # check for report prepared footer on final pages
        page_text = page.get("text", "")
        footer_match = FOOTER_PATTERN.search(page_text)
        if footer_match:
            report_prepared_at = footer_match.group(1).strip()

        # group characters into horizontal lines by top coordinate
        lines: List[Dict[str, Any]] = []
        for c in chars:
            # ignore header and title block on page 0
            if page_idx == 0 and c.get("top", 0) < 172.0:
                continue

            c_top = c.get("top", 0)
            placed = False
            for line in lines:
                if abs(line["top"] - c_top) < 3.0:
                    line["chars"].append(c)
                    placed = True
                    break
            if not placed:
                lines.append({"top": c_top, "chars": [c]})

        # sort lines top to bottom
        lines.sort(key=lambda l: l["top"])

        for line in lines:
            line_chars = line["chars"]
            full_line_text = "".join(c.get("text", "") for c in line_chars).strip()

            # skip footer line
            if "report prepared on" in full_line_text.lower():
                continue

            # check if line starts with a date pattern near anchor 52.5
            date_chars = [c for c in line_chars if c.get("x0", 0) < 110.0]
            date_str = "".join(c.get("text", "") for c in date_chars).strip()
            is_date_start = bool(DATE_PATTERN.match(date_str))

            if is_date_start:
                total_dates_found += 1

            # map characters to columns using column anchors in forward order
            col_buffers: Dict[str, str] = {name: "" for name, _ in COLUMN_ANCHORS}
            col_idx = 0

            for c in line_chars:
                c_x0 = c.get("x0", 0)
                # advance to subsequent column anchor if character starts near it
                for next_idx in range(col_idx + 1, len(COLUMN_ANCHORS)):
                    _, anchor_x = COLUMN_ANCHORS[next_idx]
                    if abs(c_x0 - anchor_x) < 0.5:
                        col_idx = next_idx
                        break

                current_col = COLUMN_ANCHORS[col_idx][0]
                col_buffers[current_col] += c.get("text", "")

            # assemble candidate row
            candidate = {k: v.strip() for k, v in col_buffers.items()}
            candidate_date = candidate.get("usage_date", "")

            # check if row is valid
            parsed_dt = parse_day_first_date(candidate_date)
            try:
                adj_val = int(candidate.get("adj", ""))
            except (ValueError, TypeError):
                adj_val = None

            if parsed_dt is not None and adj_val is not None:
                candidate["adj"] = adj_val
                candidate["page"] = page_idx
                raw_rows.append(candidate)
            elif is_date_start:
                # started with a date but failed parsing
                failed_rows.append({
                    "page": page_idx,
                    "raw_text": full_line_text,
                    "extracted": candidate,
                })

    return raw_rows, failed_rows, report_prepared_at, total_dates_found


# layer c: raw rows to clean dataframe (pure function)
def raw_rows_to_dataframe(
    raw_rows: List[Dict[str, Any]],
    members: Optional[List[Dict[str, Any]]] = None,
) -> pd.DataFrame:
    # clean normalize and structure raw rows into a standard dataframe
    if not raw_rows:
        return pd.DataFrame(columns=[
            "usage_date",
            "type",
            "customer",
            "gym_staff",
            "remarks",
            "expires",
            "adj",
            "row_kind",
            "row_key",
        ])

    cleaned_records: List[Dict[str, Any]] = []

    for r in raw_rows:
        usage_date = r.get("usage_date", "").strip()
        row_type = r.get("type", "Adj").strip() or "Adj"
        raw_cust = r.get("customer", "").strip()
        raw_staff = r.get("gym_staff", "").strip()
        remarks = r.get("remarks", "").strip()
        expires = r.get("expires", "").strip()
        adj = int(r.get("adj", 0))

        # fallback heuristics when a name column is empty
        # a usage row with only one name present means that name is customer
        # a positive row with only one name present means that name is employee
        if adj < 0:
            if not raw_cust and raw_staff:
                raw_cust = raw_staff
                raw_staff = ""
        elif adj > 0:
            if raw_cust and not raw_staff:
                raw_staff = raw_cust
                raw_cust = ""

        # normalise names
        norm_cust = resolve_canonical_name(raw_cust, members) if raw_cust else ""
        norm_staff = clean_name(raw_staff) if raw_staff else ""

        # row kind: usage if customer is present, else topup
        row_kind = "usage" if (norm_cust or adj < 0) else "topup"

        # deterministic row key for deduplication
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
            "type": row_type,
            "customer": norm_cust,
            "gym_staff": norm_staff,
            "remarks": remarks,
            "expires": expires,
            "adj": adj,
            "row_kind": row_kind,
            "row_key": row_key,
        })

    return pd.DataFrame(cleaned_records)


class ClimbersSutdParser(BaseGymParser):
    # parser implementation for boulder + climbers sutd pass history report

    @property
    def gym_name(self) -> str:
        return "Boulder +"

    def parse(
        self,
        file_source: Any,
        members: Optional[List[Dict[str, Any]]] = None,
    ) -> ParseResult:
        # validate file and orchestrate three layer parsing
        try:
            pages_data = extract_pdf_elements(file_source)
        except Exception as err:
            return ParseResult(
                gym=self.gym_name,
                report_prepared_at=None,
                total_dates_found=0,
                rows_parsed_count=0,
                reconciliation_passed=False,
                data=pd.DataFrame(),
                error_message=f"Invalid PDF file or unable to read: {err}",
            )

        if not pages_data:
            return ParseResult(
                gym=self.gym_name,
                report_prepared_at=None,
                total_dates_found=0,
                rows_parsed_count=0,
                reconciliation_passed=False,
                data=pd.DataFrame(),
                error_message="PDF contains no extractable text. OCR is not supported for scanned documents.",
            )

        # check title on first page
        page_0_text = pages_data[0].get("text", "")
        if "punches history report" not in page_0_text.lower():
            return ParseResult(
                gym=self.gym_name,
                report_prepared_at=None,
                total_dates_found=0,
                rows_parsed_count=0,
                reconciliation_passed=False,
                data=pd.DataFrame(),
                error_message="File is not a Punches History Report (expected report header not found).",
            )

        # layer b: extract raw rows
        raw_rows, failed_rows, prepared_at, total_dates = elements_to_raw_rows(pages_data)

        # layer c: clean dataframe
        df = raw_rows_to_dataframe(raw_rows, members)

        # reconciliation check
        reconciliation_passed = (len(df) == total_dates) and (len(failed_rows) == 0)

        # date ranges
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
            report_prepared_at=prepared_at,
            total_dates_found=total_dates,
            rows_parsed_count=len(df),
            reconciliation_passed=reconciliation_passed,
            data=df,
            failed_rows=failed_rows,
            earliest_date=earliest_date,
            latest_date=latest_date,
        )


# register parser instance in global registry
register_parser(ClimbersSutdParser())
