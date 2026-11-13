"""
Service layer: the business rules of the help desk.

It sits between the user interface and the database:
    cli.py  ->  TicketService  ->  TicketRepository  ->  SQLite

It validates input, enforces rules (for example "a closed ticket is read-only until it is
reopened"), and turns missing records into clear errors. It never prints and never writes SQL.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Callable

from . import validation as v
from .errors import InvalidOperationError, TicketNotFoundError, ValidationError
from .models import DATETIME_FORMAT, Priority, Status, Ticket, TicketSummary


class TicketService:
    def __init__(self, repository, clock: Callable[[], datetime] | None = None):
        self.repo = repository
        self._clock = clock or datetime.now          # injectable, so tests and demo data can fix the time

    # ---- time ------------------------------------------------------------
    def _now(self) -> str:
        return self._clock().strftime(DATETIME_FORMAT)

    def today(self) -> date:
        return self._clock().date()

    # ---- create ----------------------------------------------------------
    def create_ticket(self, customer_name, issue, priority=Priority.MEDIUM) -> Ticket:
        ticket_id = self.repo.add(v.validate_customer_name(customer_name), v.validate_issue(issue),
                                  v.parse_priority(priority), Status.OPEN, self._now())
        return self.get_ticket(ticket_id)

    # ---- view / search ---------------------------------------------------
    def get_ticket(self, ticket_id) -> Ticket:
        number = v.parse_ticket_id(ticket_id)
        ticket = self.repo.get(number)
        if ticket is None:
            raise TicketNotFoundError(number)
        return ticket

    def list_tickets(self, status=None, priority=None) -> list[Ticket]:
        return self.repo.list_all(self._optional(status, v.parse_status), self._optional(priority, v.parse_priority))

    def search_tickets(self, keyword, status=None, priority=None) -> list[Ticket]:
        return self.repo.search(v.validate_keyword(keyword), self._optional(status, v.parse_status),
                                self._optional(priority, v.parse_priority))

    @staticmethod
    def _optional(value, parser):
        return None if value in (None, "") else parser(value)

    # ---- update ----------------------------------------------------------
    def update_ticket(self, ticket_id, *, customer_name=None, issue=None, priority=None, status=None) -> Ticket:
        ticket = self.get_ticket(ticket_id)
        wanted: dict = {}
        if customer_name is not None:
            wanted["customer_name"] = v.validate_customer_name(customer_name)
        if issue is not None:
            wanted["issue"] = v.validate_issue(issue)
        if priority is not None:
            wanted["priority"] = v.parse_priority(priority)
        if status is not None:
            wanted["status"] = v.parse_status(status)
        if not wanted:
            raise ValidationError("Nothing to update: give at least one new value.")

        if wanted.get("status") is Status.CLOSED:
            raise InvalidOperationError("Use 'Close ticket' to close a ticket, so a resolution can be recorded.")
        if not ticket.is_open:
            only_reopening = set(wanted) == {"status"}
            if not only_reopening:
                raise InvalidOperationError(
                    f"Ticket #{ticket.id} is closed. Reopen it first by setting the status to Open or In Progress.")

        changes = {k: val for k, val in wanted.items() if getattr(ticket, k) != val}
        if not changes:
            raise InvalidOperationError(f"No changes: ticket #{ticket.id} already has those values.")
        if "status" in changes and not ticket.is_open:           # reopening
            changes.update(closed_at=None, resolution=None)
        changes["updated_at"] = self._now()
        self.repo.update(ticket.id, **changes)
        return self.get_ticket(ticket.id)

    def close_ticket(self, ticket_id, resolution=None) -> Ticket:
        ticket = self.get_ticket(ticket_id)
        if not ticket.is_open:
            raise InvalidOperationError(f"Ticket #{ticket.id} is already closed.")
        now = self._now()
        self.repo.update(ticket.id, status=Status.CLOSED, closed_at=now, updated_at=now,
                         resolution=v.validate_resolution(resolution))
        return self.get_ticket(ticket.id)

    # ---- reporting -------------------------------------------------------
    def summary(self) -> TicketSummary:
        status_counts = self.repo.count_by_status()
        return TicketSummary(total=sum(status_counts.values()),
                             open_matrix=self.repo.count_open_by_priority_and_status(),
                             status_counts=status_counts,
                             oldest_open=self.repo.oldest_open())
