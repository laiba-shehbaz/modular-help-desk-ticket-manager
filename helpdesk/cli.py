"""
Command-line user interface. Only talks to the user and to TicketService.

There is no SQL in this file. Input and output functions are injected, so the whole menu
can be tested with scripted answers.
"""
from __future__ import annotations

import os
import sys

from . import reports
from . import validation as v
from .errors import HelpDeskError, ValidationError
from .models import Priority, Status

USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

PRIORITY_CHOICES = {"1": Priority.CRITICAL, "2": Priority.HIGH, "3": Priority.MEDIUM, "4": Priority.LOW}
FILTER_STATUS_CHOICES = {"1": Status.OPEN, "2": Status.IN_PROGRESS, "3": Status.CLOSED}
UPDATE_STATUS_CHOICES = {"1": Status.OPEN, "2": Status.IN_PROGRESS}


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def priority_input(raw: str) -> Priority:
    return PRIORITY_CHOICES.get(raw.strip()) or v.parse_priority(raw)


def filter_status_input(raw: str) -> Status:
    return FILTER_STATUS_CHOICES.get(raw.strip()) or v.parse_status(raw)


def update_status_input(raw: str) -> Status:
    return UPDATE_STATUS_CHOICES.get(raw.strip()) or v.parse_status(raw)


class HelpDeskCLI:
    def __init__(self, service, input_fn=input, output_fn=print):
        self.service = service
        self._input = input_fn
        self._print = output_fn
        self.actions = {
            "1": ("Create ticket", self.create_ticket),
            "2": ("List tickets", self.list_tickets),
            "3": ("View ticket details", self.view_ticket),
            "4": ("Search tickets", self.search_tickets),
            "5": ("Update ticket", self.update_ticket),
            "6": ("Close ticket", self.close_ticket),
            "7": ("Summary: open tickets by priority", self.show_summary),
            "8": ("Export summary report", self.export_summary),
        }

    # ---- small output helpers ------------------------------------------------
    def say(self, text: str = "") -> None:
        self._print(text)

    def ok(self, text: str) -> None:
        self.say(paint(f"  ✓ {text}", "32"))

    def warn(self, text: str) -> None:
        self.say(paint(f"  ! {text}", "33"))

    def error(self, text) -> None:
        self.say(paint(f"  ✗ {text}", "31"))

    def title(self, text: str) -> None:
        self.say(paint(f"\n{text}", "1;36"))

    # ---- input helpers -------------------------------------------------------
    def ask(self, label, parse, *, default=None, optional=False, hint=""):
        """Ask until the parser accepts the answer. Enter returns the default (or None if optional)."""
        if default is not None:
            suffix = f" [{getattr(default, 'value', default)}]"
        else:
            suffix = f" {hint}" if hint else ""
        while True:
            raw = self._input(f"  {label}{suffix}: ")
            if not raw.strip():
                if default is not None:
                    return default
                if optional:
                    return None
            try:
                return parse(raw)
            except ValidationError as err:
                self.error(err)

    def ask_ticket(self):
        """Ask for an ID and load the ticket. A wrong format is asked again; a missing ID returns to the menu."""
        number = self.ask("Ticket ID", v.parse_ticket_id)
        return self.service.get_ticket(number)

    def confirm(self, question: str) -> bool:
        return self._input(f"  {question} (y/N): ").strip().lower() in ("y", "yes")

    # ---- screens -------------------------------------------------------------
    def banner(self) -> None:
        line = "═" * 46
        self.say(paint(f"\n╔{line}╗", "36"))
        self.say(paint(f"║{'🎫  HELP-DESK TICKET MANAGER':^45}║", "1;36"))
        self.say(paint(f"╚{line}╝", "36"))
        self.say(f"  Database : {self.service.repo.db_path}")
        self.say(f"  Tickets  : {self.service.repo.count()}")

    def menu(self) -> None:
        self.say(paint("\nMAIN MENU", "1"))
        for key, (label, _) in self.actions.items():
            self.say(f"  {key}. {label}")
        self.say("  0. Exit")

    def run(self) -> None:
        self.banner()
        try:
            while True:
                self.menu()
                choice = self._input("Choose an option: ").strip()
                if choice == "0":
                    break
                action = self.actions.get(choice)
                if action is None:
                    self.error("Please choose a number from the menu.")
                    continue
                try:
                    action[1]()
                except HelpDeskError as err:          # not found, rule broken, database problem...
                    self.error(err)
        except (EOFError, KeyboardInterrupt):
            self.say()
        self.say("Goodbye! All tickets are saved in the database.")

    # ---- actions -------------------------------------------------------------
    def create_ticket(self) -> None:
        self.title("➕ Create ticket")
        name = self.ask("Customer name", v.validate_customer_name)
        issue = self.ask("Issue", v.validate_issue)
        priority = self.ask("Priority (1 Critical, 2 High, 3 Medium, 4 Low)", priority_input, default=Priority.MEDIUM)
        ticket = self.service.create_ticket(name, issue, priority)
        self.ok(f"Ticket #{ticket.id} created ({ticket.priority.value} priority, status {ticket.status.value})")
        self.say(reports.ticket_detail(ticket, self.service.today()))

    def list_tickets(self) -> None:
        self.title("📋 List tickets")
        status = self.ask("Filter by status (1 Open, 2 In Progress, 3 Closed, Enter = all)",
                          filter_status_input, optional=True)
        priority = self.ask("Filter by priority (1 Critical, 2 High, 3 Medium, 4 Low, Enter = all)",
                            priority_input, optional=True)
        self._show_list(self.service.list_tickets(status, priority))

    def view_ticket(self) -> None:
        self.title("🔎 Ticket details")
        self.say(reports.ticket_detail(self.ask_ticket(), self.service.today()))

    def search_tickets(self) -> None:
        self.title("🔍 Search tickets")
        keyword = self.ask("Search text (customer, issue or ID)", v.validate_keyword)
        self._show_list(self.service.search_tickets(keyword), f"matching '{keyword}'")

    def update_ticket(self) -> None:
        self.title("✏️  Update ticket")
        ticket = self.ask_ticket()
        self.say(reports.ticket_detail(ticket, self.service.today()))
        self.say("\n  Press Enter to keep a value.")
        name = self.ask("New customer name", v.validate_customer_name, optional=True, hint=f"[{ticket.customer_name}]")
        issue = self.ask("New issue", v.validate_issue, optional=True, hint=f"[{reports.shorten(ticket.issue, 30)}]")
        priority = self.ask("New priority (1 Critical, 2 High, 3 Medium, 4 Low)", priority_input,
                            optional=True, hint=f"[{ticket.priority.value}]")
        status = self.ask("New status (1 Open, 2 In Progress)", update_status_input,
                          optional=True, hint=f"[{ticket.status.value}]")
        updated = self.service.update_ticket(ticket.id, customer_name=name, issue=issue,
                                             priority=priority, status=status)
        self.ok(f"Ticket #{updated.id} updated")
        self.say(reports.ticket_detail(updated, self.service.today()))

    def close_ticket(self) -> None:
        self.title("✅ Close ticket")
        ticket = self.ask_ticket()
        self.say(reports.ticket_detail(ticket, self.service.today()))
        if not ticket.is_open:
            self.warn(f"Ticket #{ticket.id} is already closed.")
            return
        resolution = self.ask("Resolution note (optional)", v.validate_resolution, optional=True)
        if not self.confirm(f"Close ticket #{ticket.id}?"):
            self.warn("Cancelled: the ticket is still open.")
            return
        closed = self.service.close_ticket(ticket.id, resolution)
        self.ok(f"Ticket #{closed.id} closed at {closed.closed_at}")

    def show_summary(self) -> None:
        self.title("📊 Summary")
        self.say(reports.summary_report(self.service.summary(), self.service.today()))

    def export_summary(self) -> None:
        self.title("📤 Export summary report")
        name = self._input("  File name [ticket_summary.txt] (.txt or .md): ").strip() or "ticket_summary.txt"
        try:
            path = reports.export_summary(self.service.summary(), name, self.service.today())
        except OSError as err:
            self.error(f"Could not write the report: {err}")
            return
        self.ok(f"Report saved to {path}")

    def _show_list(self, tickets, description: str = "") -> None:
        if not tickets:
            self.warn(f"No tickets found {description}".strip() + ".")
            return
        self.say(reports.tickets_table(tickets))
        open_count = sum(t.is_open for t in tickets)
        label = f" {description}" if description else ""
        self.say(f"  {len(tickets)} ticket(s){label}: {open_count} open, {len(tickets) - open_count} closed")
