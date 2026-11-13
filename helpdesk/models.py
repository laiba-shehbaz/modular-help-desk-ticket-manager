"""Plain data classes. No database code and no user-interface code in this file."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class Priority(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"

    @property
    def rank(self) -> int:
        """0 = most urgent."""
        return {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}[self.value]

    @classmethod
    def by_urgency(cls) -> list["Priority"]:
        return sorted(cls, key=lambda p: p.rank)


class Status(str, Enum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    CLOSED = "Closed"

    @classmethod
    def active(cls) -> tuple["Status", "Status"]:
        """Statuses that count as 'open' tickets."""
        return cls.OPEN, cls.IN_PROGRESS


@dataclass(frozen=True)
class Ticket:
    id: int
    customer_name: str
    issue: str
    priority: Priority
    status: Status
    created_at: str
    updated_at: str
    closed_at: str | None = None
    resolution: str | None = None

    @classmethod
    def from_row(cls, row) -> "Ticket":
        return cls(id=row["id"], customer_name=row["customer_name"], issue=row["issue"],
                   priority=Priority(row["priority"]), status=Status(row["status"]),
                   created_at=row["created_at"], updated_at=row["updated_at"],
                   closed_at=row["closed_at"], resolution=row["resolution"])

    @property
    def is_open(self) -> bool:
        return self.status is not Status.CLOSED

    @property
    def created_date(self) -> str:
        return self.created_at[:10]

    def age_days(self, today: date) -> int:
        """Days from creation until closing (or until `today` if still open)."""
        start = datetime.strptime(self.created_at, DATETIME_FORMAT).date()
        end = datetime.strptime(self.closed_at, DATETIME_FORMAT).date() if self.closed_at else today
        return max(0, (end - start).days)


@dataclass
class TicketSummary:
    total: int
    open_matrix: dict[Priority, dict[Status, int]]
    status_counts: dict[Status, int]
    oldest_open: Ticket | None = None

    @property
    def open_by_priority(self) -> dict[Priority, int]:
        return {p: sum(self.open_matrix[p].values()) for p in Priority.by_urgency()}

    @property
    def total_open(self) -> int:
        return sum(self.open_by_priority.values())

    @property
    def total_closed(self) -> int:
        return self.status_counts.get(Status.CLOSED, 0)
