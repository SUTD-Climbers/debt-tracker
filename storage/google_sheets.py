from datetime import datetime
from typing import Any, Dict, List, Optional
import streamlit as st

from parsers.sheet_parser import (
    convert_sheet_debt_to_records,
    extract_member_tiers_from_sheet,
    format_gym_debt_sheet,
    get_gym_sheet_name,
    normalize_gym_name,
    parse_gym_debt_sheet,
    parse_pricing_tab,
)
from services.pricing import DEFAULT_PRICING
from storage.base import StorageBackend

RECORD_COLUMNS = [
    "record_id",
    "gym",
    "row_kind",
    "person",
    "usage_date",
    "adj",
    "gym_staff",
    "remarks",
    "source_upload_id",
    "status",
    "made_by",
    "made_at",
    "row_key",
]

UPLOAD_COLUMNS = [
    "upload_id",
    "gym",
    "filename",
    "uploaded_by",
    "uploaded_at",
    "report_prepared_at",
    "rows_parsed",
    "usage_rows",
    "topup_rows",
    "rows_added",
    "rows_skipped",
    "earliest_date",
    "latest_date",
]

MEMBER_COLUMNS = [
    "canonical_name",
    "tier",
    "email",
    "gender",
    "contact_no",
    "aliases",
]


class GoogleSheetsStorage(StorageBackend):
    # google sheets storage backend with support for user pricing and gym debt tabs
    backend_name = "google_sheets"

    def __init__(self) -> None:
        # initialize credentials and spreadsheet from streamlit secrets
        self._client = None
        self._spreadsheet = None
        self._cached_pricing: Optional[Dict[str, Dict[str, float]]] = None
        self.spreadsheet_id: str = ""
        self.spreadsheet_title: str = ""
        self._members_cache: List[Dict[str, Any]] = []
        self._records_cache: Optional[List[Dict[str, Any]]] = None
        self._records_cache_time: float = 0.0
        self._balances_cache: Optional[Dict[str, int]] = None

    def invalidate_records_cache(self) -> None:
        # invalidate in-memory cached records so next read queries Google Sheets
        self._records_cache = None
        self._records_cache_time = 0.0

    def _execute_with_retry(self, func, *args, **kwargs) -> Any:
        # execute a Google Sheets operation with automatic reconnection and retry
        import time

        max_attempts = 3
        last_error = None
        for attempt in range(max_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                is_transient = any(
                    token in err_str
                    for token in (
                        "remote disconnected",
                        "connection aborted",
                        "connection reset",
                        "connection closed",
                        "connection refused",
                        "broken pipe",
                        "timed out",
                        "timeout",
                        "503",
                        "502",
                        "500",
                        "429",
                        "quota exceeded",
                    )
                )
                if not is_transient or attempt == max_attempts - 1:
                    raise
                time.sleep(0.5 * (attempt + 1))
                # reset cached client and spreadsheet handle so next iteration reconnects
                self._client = None
                self._spreadsheet = None

    def _get_spreadsheet(self) -> Any:
        # lazily connect to google sheets only when called
        if self._spreadsheet is not None:
            return self._spreadsheet

        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        from pathlib import Path
        import tomllib

        gs_cfg = {}
        local_secrets = Path(".streamlit") / "secrets.toml"
        if local_secrets.exists():
            try:
                with open(local_secrets, "rb") as f:
                    cfg_data = tomllib.load(f)
                    gs_cfg = cfg_data.get("google_sheets", {})
            except Exception:
                pass

        if not gs_cfg:
            try:
                gs_cfg = dict(st.secrets.get("google_sheets", {}))
            except Exception:
                gs_cfg = {}

        spreadsheet_id = gs_cfg.get("spreadsheet_id", "").strip()
        if not spreadsheet_id or spreadsheet_id == "your_google_spreadsheet_id_here":
            raise ValueError(
                "Spreadsheet ID is not configured in .streamlit/secrets.toml. "
                "Please replace 'your_google_spreadsheet_id_here' with your real Google Spreadsheet ID."
            )

        # support loading from json key file or secrets toml dictionary
        sa_file = None
        if "service_account_file" in gs_cfg and Path(gs_cfg["service_account_file"]).exists():
            sa_file = gs_cfg["service_account_file"]
        elif Path("credentials.json").exists():
            sa_file = "credentials.json"
        elif (Path(".streamlit") / "credentials.json").exists():
            sa_file = str(Path(".streamlit") / "credentials.json")
        elif (Path(".streamlit") / "service_account.json").exists():
            sa_file = str(Path(".streamlit") / "service_account.json")
        elif Path("service_account.json").exists():
            sa_file = "service_account.json"

        if sa_file and Path(sa_file).exists():
            credentials = Credentials.from_service_account_file(sa_file, scopes=scopes)
        else:
            sa_info = dict(gs_cfg.get("service_account", {}))
            if not sa_info.get("client_email") or "your-service-account" in sa_info.get("client_email", ""):
                raise ValueError(
                    "No valid Google service account credentials found. "
                    "Please place credentials.json in the project root or configure service_account in .streamlit/secrets.toml."
                )
            credentials = Credentials.from_service_account_info(sa_info, scopes=scopes)

        self._client = gspread.authorize(credentials)
        try:
            from urllib3.util.retry import Retry
            from requests.adapters import HTTPAdapter

            retry_strategy = Retry(
                total=3,
                connect=3,
                read=3,
                backoff_factor=0.5,
                status_forcelist=[429, 500, 502, 503, 504],
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            if hasattr(self._client, "http_client") and hasattr(self._client.http_client, "session"):
                self._client.http_client.session.mount("https://", adapter)
                self._client.http_client.session.mount("http://", adapter)
        except Exception:
            pass

        self._spreadsheet = self._client.open_by_key(spreadsheet_id)
        self.spreadsheet_id = spreadsheet_id
        try:
            self.spreadsheet_title = self._spreadsheet.title
        except Exception:
            self.spreadsheet_title = spreadsheet_id

        # verify core sheets exist in a single roundtrip
        if not getattr(self, "_sheets_verified", False):
            try:
                sheet_titles = [w.title for w in self._spreadsheet.worksheets()]
                if "Records" not in sheet_titles:
                    ws = self._spreadsheet.add_worksheet(title="Records", rows=1000, cols=len(RECORD_COLUMNS))
                    ws.append_row(RECORD_COLUMNS)
                if "Uploads" not in sheet_titles:
                    ws = self._spreadsheet.add_worksheet(title="Uploads", rows=1000, cols=len(UPLOAD_COLUMNS))
                    ws.append_row(UPLOAD_COLUMNS)
                if "Balances" not in sheet_titles:
                    b_ws = self._spreadsheet.add_worksheet(title="Balances", rows=50, cols=5)
                    b_ws.append_row(["gym", "available_passes", "updated_at", "updated_by", "note"])
                    from datetime import datetime
                    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
                    b_ws.append_rows([
                        ["Boulder +", "9", now_str, "system", "Configured balance"],
                        ["Fitbloc", "0", now_str, "system", "Configured balance"],
                        ["Boulder Planet", "18", now_str, "system", "Configured balance"],
                        ["BFF", "0", now_str, "system", "Configured balance"],
                    ])
                if "Members" in sheet_titles:
                    m_ws = self._spreadsheet.worksheet("Members")
                    self._spreadsheet.del_worksheet(m_ws)
                self._sheets_verified = True
            except Exception:
                pass

        return self._spreadsheet

    def _ensure_worksheet(self, name: str, columns: List[str]) -> Any:
        # ensure worksheet exists with header row
        def _check():
            ss = self._get_spreadsheet()
            try:
                ws = ss.worksheet(name)
            except Exception:
                ws = ss.add_worksheet(title=name, rows=1000, cols=len(columns))
                ws.append_row(columns)
            return ws

        return self._execute_with_retry(_check)

    def get_pricing(self, force_refresh: bool = False) -> Dict[str, Dict[str, float]]:
        # read pricing tab from live google spreadsheet
        if not force_refresh and self._cached_pricing is not None:
            return self._cached_pricing

        def _fetch():
            ss = self._get_spreadsheet()
            ws = ss.worksheet("Pricing")
            return ws.get_all_values()

        try:
            rows = self._execute_with_retry(_fetch)
            pricing = parse_pricing_tab(rows)
            if pricing:
                self._cached_pricing = pricing
                return pricing
        except Exception:
            pass

        return DEFAULT_PRICING

    def sync_from_google_sheet(self, gym: str = "Boulder +") -> Dict[str, Any]:
        # read gym tab (e.g. Boulder Plus) and sync baseline records into Records
        target_ws_name = get_gym_sheet_name(gym)

        def _fetch_gym_rows():
            ss = self._get_spreadsheet()
            try:
                ws = ss.worksheet(target_ws_name)
            except Exception:
                try:
                    ws = ss.worksheet(gym)
                except Exception:
                    return None
            return ws.get_all_values()

        try:
            rows = self._execute_with_retry(_fetch_gym_rows)
        except Exception as e:
            return {"synced": False, "message": f"Connection error reading {target_ws_name}: {e}"}

        if rows is None:
            return {"synced": False, "message": f"Worksheet {target_ws_name} not found"}

        parsed_gym = parse_gym_debt_sheet(rows, gym_name=gym)
        pricing = self.get_pricing(force_refresh=True)
        new_records = convert_sheet_debt_to_records(parsed_gym, pricing)

        if new_records:
            self.add_records(new_records, sync_view=False)
            last_upd = parsed_gym.get("last_updated", "15/06/2026")
            self.add_upload({
                "upload_id": f"gsheet_sync_{gym.lower().replace(' ', '_')}",
                "gym": gym,
                "filename": f"Google Sheet ({target_ws_name})",
                "uploaded_by": "google_sheet_sync",
                "uploaded_at": f"{last_upd} 00:00:00",
                "report_prepared_at": last_upd,
                "rows_parsed": len(new_records),
                "usage_rows": len(new_records),
                "topup_rows": 0,
                "rows_added": len(new_records),
                "rows_skipped": 0,
                "earliest_date": last_upd,
                "latest_date": last_upd,
            })

        self.invalidate_records_cache()

        return {
            "synced": True,
            "last_updated": parsed_gym.get("last_updated", ""),
            "members_count": len(parsed_gym.get("members", [])),
            "records_added": len(new_records),
            "pricing": pricing,
        }

    def get_latest_updated_date(self, gym: str = "Boulder +") -> Optional[datetime]:
        # get latest updated date from live gym worksheet or records
        from parsers.climbers_sutd import parse_day_first_date
        dates: List[datetime] = []

        def _fetch_header_date():
            ss = self._get_spreadsheet()
            target_ws_name = get_gym_sheet_name(gym)
            try:
                ws = ss.worksheet(target_ws_name)
            except Exception:
                ws = ss.worksheet(gym)
            return ws.acell("C1").value

        try:
            val = self._execute_with_retry(_fetch_header_date)
            if val:
                d = parse_day_first_date(str(val))
                if d:
                    dates.append(d)
        except Exception:
            pass

        records = self.get_records(gym=gym)
        for r in records:
            d = parse_day_first_date(r.get("usage_date", ""))
            if d:
                dates.append(d)

        return max(dates) if dates else None

    def get_records(self, gym: Optional[str] = None, force_refresh: bool = False) -> List[Dict[str, Any]]:
        # retrieve records from google sheets with short-lived memory caching and auto-reconnect retry
        import time

        now = time.time()
        if not force_refresh and self._records_cache is not None and (now - self._records_cache_time < 30.0):
            all_records = self._records_cache
        else:
            def _fetch_rows():
                ss = self._get_spreadsheet()
                ws = ss.worksheet("Records")
                return ws.get_all_records()

            try:
                rows = self._execute_with_retry(_fetch_rows)
            except Exception:
                if self._records_cache is not None:
                    rows = self._records_cache
                else:
                    raise

            all_records = []
            for r in rows:
                r_dict = dict(r)
                r_dict["adj"] = int(r_dict["adj"]) if r_dict.get("adj") != "" else 0
                all_records.append(r_dict)

            self._records_cache = all_records
            self._records_cache_time = now

        # if records worksheet is empty, initialize from gym tab
        if not all_records and gym:
            sync_res = self.sync_from_google_sheet(gym=gym)
            if sync_res.get("synced"):
                return self.get_records(gym=gym, force_refresh=True)

        if gym is None:
            return [dict(r) for r in all_records]
        return [dict(r) for r in all_records if r.get("gym") == gym]

    def add_records(self, records: List[Dict[str, Any]], sync_view: bool = True) -> int:
        # append new records to google sheets and update visible sheet view
        if not records:
            return 0
        import uuid
        self.invalidate_records_cache()

        rows_to_append: List[List[Any]] = []
        for r in records:
            if "record_id" not in r or not r["record_id"]:
                r["record_id"] = f"rec_{uuid.uuid4().hex[:12]}"
            row_vals = [r.get(col, "") for col in RECORD_COLUMNS]
            rows_to_append.append(row_vals)

        def _append_rows():
            ss = self._get_spreadsheet()
            ws = self._ensure_worksheet("Records", RECORD_COLUMNS)
            ws.append_rows(rows_to_append)

        self._execute_with_retry(_append_rows)

        if sync_view:
            gyms = {r.get("gym", "Boulder +") for r in records if r.get("gym")}
            for g in gyms:
                self._sync_sheet_view(gym=g)

        return len(records)

    def update_record_status(
        self,
        record_id: str,
        status: str,
        made_by: str,
        made_at: str,
    ) -> bool:
        # update single record status
        count = self.update_records_bulk([record_id], status, made_by, made_at)
        return count > 0

    def update_records_bulk(
        self,
        record_ids: List[str],
        status: str,
        made_by: str,
        made_at: str,
    ) -> int:
        # update multiple record statuses in google sheets and sync sheet view
        if not record_ids:
            return 0
        self.invalidate_records_cache()

        def _batch_update_rows():
            ss = self._get_spreadsheet()
            ws = ss.worksheet("Records")
            all_rows = ws.get_all_records()
            target_ids = set(record_ids)

            updated_count = 0
            updates: List[Dict[str, Any]] = []

            for idx, row in enumerate(all_rows, start=2):
                if str(row.get("record_id")) in target_ids:
                    row_status = status
                    row_made_by = made_by if status in ("made", "paid") else ""
                    row_made_at = made_at if status in ("made", "paid") else ""

                    updates.append({
                        "range": f"J{idx}:L{idx}",
                        "values": [[row_status, row_made_by, row_made_at]],
                    })
                    updated_count += 1

            if updates:
                ws.batch_update(updates)
                gyms = {r.get("gym", "Boulder +") for r in all_rows if str(r.get("record_id")) in target_ids and r.get("gym")}
                for g in gyms:
                    self._sync_sheet_view(gym=g)

            return updated_count

        return self._execute_with_retry(_batch_update_rows)

    def sync_sheet_view(self, gym: str = "Boulder +") -> None:
        # public method to synchronize visible gym sheet view
        self._sync_sheet_view(gym=gym)

    def _sync_sheet_view(self, gym: str = "Boulder +") -> None:
        # synchronize visible gym worksheet (e.g. Boulder Plus) with active member debts
        target_ws_name = get_gym_sheet_name(gym)

        def _sync():
            ss = self._get_spreadsheet()
            try:
                ws = ss.worksheet(target_ws_name)
            except Exception:
                try:
                    ws = ss.worksheet(gym)
                except Exception:
                    ws = ss.add_worksheet(title=target_ws_name, rows=100, cols=10)

            existing_rows = ws.get_all_values()
            existing_tiers = extract_member_tiers_from_sheet(existing_rows)

            records = self.get_records(gym=gym)
            pricing = self.get_pricing()

            # incorporate live member directory tiers
            try:
                from services.members import get_member_tier_map
                members = self.get_members()
                live_tiers = get_member_tier_map(members, records=records)
                active_tiers = {**existing_tiers, **live_tiers}
            except Exception:
                active_tiers = existing_tiers

            grid = format_gym_debt_sheet(
                records=records,
                gym_name=gym,
                pricing_matrix=pricing,
                member_tiers=active_tiers,
            )

            ws.clear()
            ws.update(values=grid, range_name="A1")

        try:
            self._execute_with_retry(_sync)
        except Exception as e:
            print(f"Error: Failed to sync sheet view for {gym} ({target_ws_name}): {e}")

    def get_uploads(self, gym: Optional[str] = None) -> List[Dict[str, Any]]:
        # retrieve upload audit entries
        def _fetch_uploads():
            ss = self._get_spreadsheet()
            ws = ss.worksheet("Uploads")
            return ws.get_all_records()

        try:
            rows = self._execute_with_retry(_fetch_uploads)
        except Exception:
            rows = []

        if gym:
            return [r for r in rows if r.get("gym") == gym]
        return rows

    def add_upload(self, upload_entry: Dict[str, Any]) -> str:
        # append upload audit entry
        import uuid
        if "upload_id" not in upload_entry or not upload_entry["upload_id"]:
            upload_entry["upload_id"] = f"upl_{uuid.uuid4().hex[:12]}"

        def _append_upload():
            ss = self._get_spreadsheet()
            ws = ss.worksheet("Uploads")
            row_vals = [upload_entry.get(col, "") for col in UPLOAD_COLUMNS]
            ws.append_row(row_vals)

        self._execute_with_retry(_append_upload)
        return str(upload_entry["upload_id"])

    def get_members(self) -> List[Dict[str, Any]]:
        # retrieve canonical members list from in-memory/session cache, or dynamically pull from the 2 spreadsheets
        if self._members_cache:
            return self._members_cache

        try:
            import streamlit as st
            if "cached_members" in st.session_state and st.session_state.cached_members:
                self._members_cache = list(st.session_state.cached_members)
                return self._members_cache
        except Exception:
            pass

        sync_res = self.sync_members_from_google_sheets()
        if sync_res.get("synced"):
            return self._members_cache
        return []

    def save_members(self, members: List[Dict[str, Any]]) -> None:
        # keep members in memory and session cache only - NEVER write to main spreadsheet
        self._members_cache = list(members)
        try:
            import streamlit as st
            st.session_state.cached_members = list(members)
        except Exception:
            pass

    def sync_members_from_google_sheets(self) -> Dict[str, Any]:
        # dynamically synchronize members and tiers from linked google sheets
        import re
        from pathlib import Path
        import tomllib
        from services.members import generate_name_variants

        client = self._client
        if client is None:
            self._get_spreadsheet()
            client = self._client

        gs_cfg = {}
        local_secrets = Path(".streamlit") / "secrets.toml"
        if local_secrets.exists():
            try:
                with open(local_secrets, "rb") as f:
                    cfg_data = tomllib.load(f)
                    gs_cfg = cfg_data.get("google_sheets", {})
            except Exception:
                pass

        if not gs_cfg:
            try:
                gs_cfg = dict(st.secrets.get("google_sheets", {}))
            except Exception:
                gs_cfg = {}

        all_id = gs_cfg.get("all_members_spreadsheet_id", "1_w_gVQut_8avrUExY496eyvyT7FzdJWJrLg1CG-HQ88").strip()
        t2_id = gs_cfg.get("tier_2_spreadsheet_id", "1BRaPsQBB6LRxARyBrMS0dwSmFazc78Y78hhOa9VIz5g").strip()

        import concurrent.futures

        def _fetch_sheet_values(sheet_id: str) -> List[List[Any]]:
            ss = client.open_by_key(sheet_id)
            ws = ss.get_worksheet(0)
            return ws.get_all_values()

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                f_all = executor.submit(self._execute_with_retry, _fetch_sheet_values, all_id)
                f_t2 = executor.submit(self._execute_with_retry, _fetch_sheet_values, t2_id)
                all_rows = f_all.result()
                t2_rows = f_t2.result()
        except Exception as e:
            return {"synced": False, "message": f"Failed to connect to member spreadsheets: {e}"}

        t2_emails = {r[2].strip().lower() for r in t2_rows[1:] if len(r) > 2 and r[2].strip()}
        t2_phones = {re.sub(r"[^0-9]", "", str(r[3])) for r in t2_rows[1:] if len(r) > 3 and str(r[3]).strip()}

        members_list: List[Dict[str, Any]] = []

        for r in all_rows[1:]:
            if not r or not r[0].strip():
                continue
            name = r[0].strip()
            gender = r[1].strip() if len(r) > 1 else ""
            email = r[2].strip().lower() if len(r) > 2 else ""
            contact = r[3].strip() if len(r) > 3 else ""
            clean_phone = re.sub(r"[^0-9]", "", contact)

            # Difference logic: if present in T2 sheet by email or phone, then Tier 2; else Tier 1
            is_tier_2 = (email and email in t2_emails) or (clean_phone and clean_phone in t2_phones)
            tier = "tier_2" if is_tier_2 else "tier_1"

            # Generate smart aliases
            variants = generate_name_variants(name)
            aliases_str = "; ".join(variants)

            members_list.append({
                "canonical_name": name,
                "tier": tier,
                "email": email,
                "gender": gender,
                "contact_no": contact,
                "aliases": aliases_str,
            })

        if members_list:
            self.save_members(members_list)

        t1_count = sum(1 for m in members_list if m["tier"] == "tier_1")
        t2_count = sum(1 for m in members_list if m["tier"] == "tier_2")

        return {
            "synced": True,
            "total_members": len(members_list),
            "tier_1_count": t1_count,
            "tier_2_count": t2_count,
            "members": members_list,
        }

    def get_all_available_passes(self, force_refresh: bool = False) -> Dict[str, int]:
        from parsers.sheet_parser import normalize_gym_name
        if not force_refresh and self._balances_cache is not None:
            return self._balances_cache

        defaults = {"Boulder +": 9, "Fitbloc": 0, "Boulder Planet": 18, "BFF": 0}

        def _fetch():
            ss = self._get_spreadsheet()
            try:
                ws = ss.worksheet("Balances")
                return ws.get_all_values()
            except Exception:
                return []

        try:
            rows = self._execute_with_retry(_fetch)
            if rows and len(rows) > 1:
                balances = dict(defaults)
                for r in rows[1:]:
                    if len(r) >= 2 and r[0].strip():
                        g_norm = normalize_gym_name(r[0])
                        try:
                            balances[g_norm] = int(float(r[1].strip()))
                        except Exception:
                            pass
                self._balances_cache = balances
                return balances
        except Exception:
            pass

        self._balances_cache = defaults
        return defaults

    def get_available_passes(self, gym: str = "Boulder +") -> int:
        from parsers.sheet_parser import normalize_gym_name
        norm = normalize_gym_name(gym)
        balances = self.get_all_available_passes()
        defaults = {"Boulder +": 9, "Fitbloc": 0, "Boulder Planet": 18, "BFF": 0}
        return balances.get(norm, defaults.get(norm, 0))

    def set_available_passes(
        self,
        gym: str,
        count: int,
        updated_by: str = "",
        note: str = "",
    ) -> None:
        from datetime import datetime
        from parsers.sheet_parser import normalize_gym_name
        norm = normalize_gym_name(gym)
        if self._balances_cache is None:
            self.get_all_available_passes()
        self._balances_cache[norm] = int(count)

        def _update():
            ss = self._get_spreadsheet()
            try:
                ws = ss.worksheet("Balances")
            except Exception:
                ws = ss.add_worksheet(title="Balances", rows=50, cols=5)
                ws.append_row(["gym", "available_passes", "updated_at", "updated_by", "note"])

            rows = ws.get_all_values()
            now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
            row_idx = None
            if rows:
                for i, r in enumerate(rows[1:], start=2):
                    if r and normalize_gym_name(r[0]) == norm:
                        row_idx = i
                        break

            if row_idx is not None:
                ws.update(range_name=f"A{row_idx}:E{row_idx}", values=[[norm, str(count), now_str, updated_by, note]])
            else:
                ws.append_row([norm, str(count), now_str, updated_by, note])

        self._execute_with_retry(_update)
