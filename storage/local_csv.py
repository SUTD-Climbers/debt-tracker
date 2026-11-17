import csv
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from parsers.sheet_parser import (
    convert_sheet_debt_to_records,
    get_gym_sheet_name,
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


class LocalCsvStorage(StorageBackend):
    # local csv storage implementation storing files in data directory
    backend_name = "local_csv"

    def __init__(self, data_dir: Optional[str] = None) -> None:
        # initialize storage paths
        base_dir = Path(data_dir) if data_dir else Path(__file__).resolve().parent.parent / "data"
        self.data_dir = base_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.records_file = self.data_dir / "records.csv"
        self.uploads_file = self.data_dir / "uploads.csv"
        self.members_file = self.data_dir / "members.csv"
        self.seed_file = self.data_dir / "seed_google_sheet.json"

        self._ensure_file(self.records_file, RECORD_COLUMNS)
        self._ensure_file(self.uploads_file, UPLOAD_COLUMNS)
        self._ensure_file(self.members_file, MEMBER_COLUMNS)

        # seed initial google sheet data if records file has no entries
        self._seed_initial_sheet_data_if_empty()

    def _ensure_file(self, file_path: Path, columns: List[str]) -> None:
        # ensure csv file exists with appropriate header row
        if not file_path.exists() or file_path.stat().st_size == 0:
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(columns)

    def _seed_initial_sheet_data_if_empty(self) -> None:
        # seed baseline records from google sheet seed data if records is empty
        if not self.records_file.exists():
            return

        with open(self.records_file, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        # if only header or empty, seed from google sheet
        if len(rows) <= 1 and self.seed_file.exists():
            try:
                with open(self.seed_file, "r", encoding="utf-8") as f:
                    seed_data = json.load(f)

                pricing = parse_pricing_tab(seed_data.get("Pricing", []))
                sheet_data = parse_gym_debt_sheet(seed_data.get("Boulder Plus", []), gym_name="Boulder +")
                init_records = convert_sheet_debt_to_records(sheet_data, pricing)

                if init_records:
                    self.add_records(init_records, sync_view=False)

                    # record initial upload entry
                    last_upd = sheet_data.get("last_updated", "15/06/2026")
                    upload_entry = {
                        "upload_id": "gsheet_sync_15062026",
                        "gym": "Boulder +",
                        "filename": "Google Sheet (Boulder Plus)",
                        "uploaded_by": "system_sync",
                        "uploaded_at": f"{last_upd} 00:00:00",
                        "report_prepared_at": last_upd,
                        "rows_parsed": len(init_records),
                        "usage_rows": len(init_records),
                        "topup_rows": 0,
                        "rows_added": len(init_records),
                        "rows_skipped": 0,
                        "earliest_date": last_upd,
                        "latest_date": last_upd,
                    }
                    self.add_upload(upload_entry)
            except Exception:
                pass

    def get_pricing(self) -> Dict[str, Dict[str, float]]:
        # read pricing matrix from seed google sheet or default
        if self.seed_file.exists():
            try:
                with open(self.seed_file, "r", encoding="utf-8") as f:
                    seed_data = json.load(f)
                pricing = parse_pricing_tab(seed_data.get("Pricing", []))
                if pricing:
                    return pricing
            except Exception:
                pass
        return DEFAULT_PRICING

    def sync_from_google_sheet(self, gym: str = "Boulder +") -> Dict[str, Any]:
        # reload or refresh baseline from google sheet
        if self.seed_file.exists():
            try:
                with open(self.seed_file, "r", encoding="utf-8") as f:
                    seed_data = json.load(f)
                target_sheet = get_gym_sheet_name(gym)
                sheet_data = parse_gym_debt_sheet(seed_data.get(target_sheet, seed_data.get("Boulder Plus", [])), gym_name=gym)
                pricing = parse_pricing_tab(seed_data.get("Pricing", []))
                return {
                    "synced": True,
                    "last_updated": sheet_data.get("last_updated", ""),
                    "members_count": len(sheet_data.get("members", [])),
                    "pricing": pricing,
                }
            except Exception as e:
                return {"synced": False, "message": str(e)}
        return {"synced": False, "message": "Seed file not found"}

    def get_latest_updated_date(self, gym: str = "Boulder +") -> Optional[datetime]:
        # get latest updated date from seed sheet or stored records
        from parsers.climbers_sutd import parse_day_first_date
        dates: List[datetime] = []

        if self.seed_file.exists():
            try:
                with open(self.seed_file, "r", encoding="utf-8") as f:
                    seed_data = json.load(f)
                sheet_key = get_gym_sheet_name(gym)
                rows = seed_data.get(sheet_key, [])
                if rows and len(rows) > 0 and len(rows[0]) > 2:
                    d = parse_day_first_date(str(rows[0][2]))
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

    def get_records(self, gym: Optional[str] = None) -> List[Dict[str, Any]]:
        # read all records from csv optionally filtered by gym
        records: List[Dict[str, Any]] = []
        if not self.records_file.exists():
            return records

        with open(self.records_file, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if gym is None or row.get("gym") == gym:
                    row["adj"] = int(row["adj"]) if row.get("adj") else 0
                    records.append(dict(row))
        return records

    def add_records(self, records: List[Dict[str, Any]], sync_view: bool = True) -> int:
        # append a batch of records to records csv and synchronize sheet view
        if not records:
            return 0

        with open(self.records_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=RECORD_COLUMNS)
            for r in records:
                if "record_id" not in r or not r["record_id"]:
                    r["record_id"] = f"rec_{uuid.uuid4().hex[:12]}"
                clean_row = {col: r.get(col, "") for col in RECORD_COLUMNS}
                writer.writerow(clean_row)

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
        # update status and audit metadata for a single record
        updated_count = self.update_records_bulk([record_id], status, made_by, made_at)
        return updated_count > 0

    def update_records_bulk(
        self,
        record_ids: List[str],
        status: str,
        made_by: str,
        made_at: str,
    ) -> int:
        # update status and audit metadata for multiple records and sync sheet view
        if not record_ids:
            return 0

        target_set = set(record_ids)
        all_records = self.get_records()
        modified_count = 0
        affected_gyms = set()

        for r in all_records:
            if r.get("record_id") in target_set:
                r["status"] = status
                r["made_by"] = made_by if status in ("made", "paid") else ""
                r["made_at"] = made_at if status in ("made", "paid") else ""
                modified_count += 1
                if r.get("gym"):
                    affected_gyms.add(r["gym"])

        if modified_count > 0:
            temp_file = self.records_file.with_suffix(".tmp")
            with open(temp_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=RECORD_COLUMNS)
                writer.writeheader()
                for r in all_records:
                    writer.writerow({col: r.get(col, "") for col in RECORD_COLUMNS})
            os.replace(temp_file, self.records_file)

            for g in affected_gyms:
                self._sync_sheet_view(gym=g)

        return modified_count

    def sync_sheet_view(self, gym: str = "Boulder +") -> None:
        # public method to trigger synchronization of sheet view
        self._sync_sheet_view(gym=gym)

    def _sync_sheet_view(self, gym: str = "Boulder +") -> None:
        # synchronize local seed google sheet view with current state
        if not self.seed_file.exists():
            return
        try:
            with open(self.seed_file, "r", encoding="utf-8") as f:
                seed_data = json.load(f)

            sheet_key = get_gym_sheet_name(gym)
            existing_rows = seed_data.get(sheet_key, [])
            from parsers.sheet_parser import extract_member_tiers_from_sheet, format_gym_debt_sheet

            existing_tiers = extract_member_tiers_from_sheet(existing_rows)
            records = self.get_records(gym=gym)
            pricing = self.get_pricing()

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

            seed_data[sheet_key] = grid

            with open(self.seed_file, "w", encoding="utf-8") as f:
                json.dump(seed_data, f, indent=2)
        except Exception:
            pass

    def get_uploads(self, gym: Optional[str] = None) -> List[Dict[str, Any]]:
        # read all upload entries from csv
        uploads: List[Dict[str, Any]] = []
        if not self.uploads_file.exists():
            return uploads

        with open(self.uploads_file, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if gym is None or row.get("gym") == gym:
                    uploads.append(dict(row))
        return uploads

    def add_upload(self, upload_entry: Dict[str, Any]) -> str:
        # record an upload entry in uploads csv
        if "upload_id" not in upload_entry or not upload_entry["upload_id"]:
            upload_entry["upload_id"] = f"upl_{uuid.uuid4().hex[:12]}"

        with open(self.uploads_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=UPLOAD_COLUMNS)
            clean_entry = {col: upload_entry.get(col, "") for col in UPLOAD_COLUMNS}
            writer.writerow(clean_entry)

        return str(upload_entry["upload_id"])

    def get_members(self) -> List[Dict[str, Any]]:
        # read all canonical members and aliases
        members: List[Dict[str, Any]] = []
        if not self.members_file.exists():
            return members

        with open(self.members_file, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                members.append(dict(row))
        return members

    def save_members(self, members: List[Dict[str, Any]]) -> None:
        # overwrite members csv with provided list
        temp_file = self.members_file.with_suffix(".tmp")
        with open(temp_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=MEMBER_COLUMNS)
            writer.writeheader()
            for m in members:
                writer.writerow({col: m.get(col, "") for col in MEMBER_COLUMNS})
        os.replace(temp_file, self.members_file)

    def sync_members_from_google_sheets(self) -> Dict[str, Any]:
        # try pulling members from google sheets if credentials and network are available
        try:
            from storage.google_sheets import GoogleSheetsStorage
            gs = GoogleSheetsStorage()
            res = gs.sync_members_from_google_sheets()
            if res.get("synced"):
                self.save_members(res.get("members", []))
                return res
        except Exception as e:
            pass
        members = self.get_members()
        t1_count = sum(1 for m in members if m.get("tier") == "tier_1")
        t2_count = sum(1 for m in members if m.get("tier") == "tier_2")
        return {
            "synced": bool(members),
            "total_members": len(members),
            "tier_1_count": t1_count,
            "tier_2_count": t2_count,
            "members": members,
        }
