from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional


class StorageBackend(ABC):
    # abstract storage backend interface

    @abstractmethod
    def get_records(self, gym: Optional[str] = None) -> List[Dict[str, Any]]:
        # retrieve all stored records optionally filtered by gym
        pass

    @abstractmethod
    def add_records(self, records: List[Dict[str, Any]], sync_view: bool = True) -> int:
        # append a list of new records and return count added
        pass

    @abstractmethod
    def update_record_status(
        self,
        record_id: str,
        status: str,
        made_by: str,
        made_at: str,
    ) -> bool:
        # update settlement status and audit fields for a single record
        pass

    @abstractmethod
    def update_records_bulk(
        self,
        record_ids: List[str],
        status: str,
        made_by: str,
        made_at: str,
    ) -> int:
        # update status and audit fields for multiple records in one batch
        pass

    @abstractmethod
    def get_uploads(self, gym: Optional[str] = None) -> List[Dict[str, Any]]:
        # retrieve audit history of uploaded files
        pass

    @abstractmethod
    def add_upload(self, upload_entry: Dict[str, Any]) -> str:
        # record a new upload audit log entry and return upload id
        pass

    @abstractmethod
    def get_members(self) -> List[Dict[str, Any]]:
        # retrieve canonical members list and aliases
        pass

    @abstractmethod
    def save_members(self, members: List[Dict[str, Any]]) -> None:
        # save or overwrite members list and aliases
        pass

    def get_pricing(self) -> Dict[str, Dict[str, float]]:
        # retrieve gym pricing matrix by gym and tier
        from services.pricing import DEFAULT_PRICING
        return DEFAULT_PRICING

    def sync_from_google_sheet(self, gym: str = "Boulder +") -> Dict[str, Any]:
        # synchronize or refresh state from google sheet
        return {"synced": False, "message": "Sync not implemented for this backend"}

    def sync_sheet_view(self, gym: str = "Boulder +") -> None:
        # synchronize visible gym sheet view with current active debts
        pass

    def sync_members_from_google_sheets(self) -> Dict[str, Any]:
        # dynamically synchronize members and tiers from linked google sheets
        return {"synced": False, "message": "Sync members not implemented for this backend"}

    def get_latest_updated_date(self, gym: str = "Boulder +") -> Optional[datetime]:
        # retrieve latest pass date recorded or sheet last updated date
        return None
