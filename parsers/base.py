from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import pandas as pd


@dataclass
class ParseResult:
    # structured result from parsing a gym report
    gym: str
    report_prepared_at: Optional[str]
    total_dates_found: int
    rows_parsed_count: int
    reconciliation_passed: bool
    data: pd.DataFrame
    failed_rows: List[Dict[str, Any]] = field(default_factory=list)
    earliest_date: Optional[str] = None
    latest_date: Optional[str] = None
    error_message: Optional[str] = None


class BaseGymParser(ABC):
    # file type agnostic base parser interface

    @property
    @abstractmethod
    def gym_name(self) -> str:
        # unique gym identifier
        pass

    @abstractmethod
    def parse(
        self,
        file_source: Any,
        members: Optional[List[Dict[str, Any]]] = None,
    ) -> ParseResult:
        # parse raw file source into a structured ParseResult
        pass
