"""
Tests for the help-desk ticket manager. Run from the project folder:

    python -m unittest -v
"""
import contextlib
import io
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as main_module  # noqa: E402
from helpdesk import reports, validation as v  # noqa: E402
from helpdesk.cli import HelpDeskCLI  # noqa: E402
from helpdesk.database import TicketRepository  # noqa: E402
from helpdesk.demo_data import seed_demo  # noqa: E402
from helpdesk.errors import (DatabaseError, InvalidOperationError, TicketNotFoundError,  # noqa: E402
                             ValidationError)
from helpdesk.models import Priority, Status  # noqa: E402
from helpdesk.service import TicketService  # noqa: E402


class Clock:
    """A clock the tests can move forward."""

    def __init__(self):
        self.now = datetime(2026, 11, 13, 10, 0, 0)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class ServiceCase(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.repo = TicketRepository(":memory:")
        self.service = TicketService(self.repo, clock=self.clock)
        self.addCleanup(self.repo.close)

    def make(self, name="Ali Raza", issue="Printer is not working", priority="Medium"):
        return self.service.create_ticket(name, issue, priority)


# ───────────────────────────── validation ─────────────────────────────
class ValidationTests(unittest.TestCase):
    def test_customer_name(self):
        self.assertEqual(v.validate_customer_name("  Ayesha   Khan "), "Ayesha Khan")
        self.assertEqual(v.validate_customer_name("Sana O'Neil-Smith Jr."), "Sana O'Neil-Smith Jr.")
        for bad in ("", "   ", "A", "x" * 61, "Ali123", "123 Ali", "Ali; DROP", "<b>Ali</b>", None):
            with self.assertRaises(ValidationError, msg=repr(bad)):
                v.validate_customer_name(bad)

    def test_issue(self):
        self.assertEqual(v.validate_issue("  Cannot   log in  "), "Cannot log in")
        for bad in ("", "abc", " " * 10, "x" * 501):
            with self.assertRaises(ValidationError, msg=repr(bad)):
                v.validate_issue(bad)

    def test_priority_and_status_parsing(self):
        self.assertIs(v.parse_priority(" HIGH "), Priority.HIGH)
        self.assertIs(v.parse_status("in-progress"), Status.IN_PROGRESS)
        self.assertIs(v.parse_status("IN PROGRESS"), Status.IN_PROGRESS)
        with self.assertRaises(ValidationError):
            v.parse_priority("urgent")
        with self.assertRaises(ValidationError):
            v.parse_status("done")

    def test_ticket_id(self):
        for good, expected in (("12", 12), (" #7 ", 7), (5, 5)):
            self.assertEqual(v.parse_ticket_id(good), expected)
        for bad in ("abc", "", "-3", "0", "3.5", "1e3", True, None, 0, -1, 10 ** 12):
            with self.assertRaises(ValidationError, msg=repr(bad)):
                v.parse_ticket_id(bad)

    def test_keyword_and_resolution(self):
        self.assertEqual(v.validate_keyword(" printer "), "printer")
        with self.assertRaises(ValidationError):
            v.validate_keyword("a")
        self.assertIsNone(v.validate_resolution("   "))
        with self.assertRaises(ValidationError):
            v.validate_resolution("x" * 301)


# ───────────────────────────── database layer ─────────────────────────
class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.repo = TicketRepository(":memory:")
        self.addCleanup(self.repo.close)

    def add(self, name="Ali Raza", issue="Printer is not working", priority=Priority.MEDIUM,
            created="2026-11-01 09:00:00"):
        return self.repo.add(name, issue, priority, Status.OPEN, created)

    def test_add_and_get_round_trip(self):
        ticket = self.repo.get(self.add())
        self.assertEqual((ticket.customer_name, ticket.priority, ticket.status), ("Ali Raza", Priority.MEDIUM, Status.OPEN))
        self.assertEqual((ticket.created_at, ticket.updated_at), ("2026-11-01 09:00:00",) * 2)
        self.assertIsNone(ticket.closed_at)

    def test_missing_id_returns_none_or_false(self):
        self.assertIsNone(self.repo.get(999))
        self.assertFalse(self.repo.update(999, issue="Some new text"))

    def test_ordering_urgent_first_and_closed_last(self):
        low = self.add(issue="Low priority thing", priority=Priority.LOW)
        crit = self.add(issue="Critical outage now", priority=Priority.CRITICAL)
        closed = self.add(issue="Old closed ticket", priority=Priority.CRITICAL)
        self.repo.update(closed, status=Status.CLOSED, closed_at="2026-11-02 10:00:00")
        self.assertEqual([t.id for t in self.repo.list_all()], [crit, low, closed])

    def test_filters(self):
        a = self.add(priority=Priority.HIGH)
        b = self.add(priority=Priority.LOW)
        self.repo.update(b, status=Status.IN_PROGRESS)
        self.assertEqual([t.id for t in self.repo.list_all(priority=Priority.HIGH)], [a])
        self.assertEqual([t.id for t in self.repo.list_all(status=Status.IN_PROGRESS)], [b])
        self.assertEqual(self.repo.list_all(status=Status.CLOSED), [])

    def test_search_name_issue_and_id(self):
        a = self.add(name="Ayesha Khan", issue="Email is slow")
        self.add(name="Bilal Ahmed", issue="VPN keeps dropping")
        self.assertEqual([t.id for t in self.repo.search("ayesha")], [a])        # case-insensitive
        self.assertEqual(len(self.repo.search("vpn")), 1)
        self.assertEqual([t.id for t in self.repo.search(str(a))], [a])          # by ID
        self.assertEqual([t.id for t in self.repo.search(f"#{a}")], [a])
        self.assertEqual(self.repo.search("nothing like this"), [])

    def test_search_treats_wildcards_literally(self):
        full = self.add(issue="Disk is 100% full")
        self.add(issue="Plain issue text here")
        under = self.add(issue="File_name problem")
        self.assertEqual([t.id for t in self.repo.search("100%")], [full])
        self.assertEqual([t.id for t in self.repo.search("%")], [full])
        self.assertEqual([t.id for t in self.repo.search("_")], [under])

    def test_sql_injection_is_harmless(self):
        evil = "Robert'); DROP TABLE tickets;--"
        ticket_id = self.add(name=evil)
        self.assertEqual(self.repo.get(ticket_id).customer_name, evil)       # stored as plain text
        self.assertEqual(self.repo.search("' OR '1'='1"), [])
        self.assertEqual(self.repo.search("x'; DELETE FROM tickets; --"), [])
        self.assertEqual(self.repo.count(), 1)                               # table still intact

    def test_update_only_allows_whitelisted_columns(self):
        ticket_id = self.add()
        with self.assertRaises(ValueError):
            self.repo.update(ticket_id, id=5)
        with self.assertRaises(ValueError):
            self.repo.update(ticket_id, **{"issue = 'x', priority": "Low"})
        self.assertTrue(self.repo.update(ticket_id, priority=Priority.HIGH))
        self.assertIs(self.repo.get(ticket_id).priority, Priority.HIGH)

    def test_schema_constraints_protect_the_data(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo._conn.execute("INSERT INTO tickets (customer_name, issue, priority, status, created_at, updated_at)"
                                    " VALUES ('Ali Raza', 'Valid issue text', 'Urgent', 'Open', 'x', 'x')")
        ticket_id = self.add()
        with self.assertRaises(DatabaseError):                               # Closed without closed_at
            self.repo.update(ticket_id, status=Status.CLOSED)

    def test_statistics(self):
        a = self.add(priority=Priority.CRITICAL, created="2026-11-05 09:00:00")
        b = self.add(priority=Priority.CRITICAL, created="2026-11-03 09:00:00")
        c = self.add(priority=Priority.LOW)
        self.repo.update(b, status=Status.IN_PROGRESS)
        self.repo.update(c, status=Status.CLOSED, closed_at="2026-11-06 09:00:00")
        self.assertEqual(self.repo.count(), 3)
        self.assertEqual(self.repo.count_by_status(), {Status.OPEN: 1, Status.IN_PROGRESS: 1, Status.CLOSED: 1})
        matrix = self.repo.count_open_by_priority_and_status()
        self.assertEqual(matrix[Priority.CRITICAL], {Status.OPEN: 1, Status.IN_PROGRESS: 1})
        self.assertEqual(matrix[Priority.LOW], {Status.OPEN: 0, Status.IN_PROGRESS: 0})   # closed not counted
        self.assertEqual(self.repo.oldest_open().id, b)
        self.assertIsNotNone(a)

    def test_empty_database_statistics(self):
        self.assertEqual(self.repo.count(), 0)
        self.assertIsNone(self.repo.oldest_open())


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_tickets_survive_closing_the_program(self):
        path = self.dir / "nested" / "folder" / "helpdesk.db"          # folders are created automatically
        with TicketRepository(path) as repo:
            service = TicketService(repo)
            ticket = service.create_ticket("Sana Malik", "Cannot open the shared drive", "High")
            service.close_ticket(ticket.id, "Permissions fixed")
        with TicketRepository(path) as repo:                            # a "new run" of the program
            saved = TicketService(repo).get_ticket(ticket.id)
        self.assertEqual((saved.customer_name, saved.status, saved.resolution),
                         ("Sana Malik", Status.CLOSED, "Permissions fixed"))

    def test_damaged_database_file_gives_a_clear_error(self):
        path = self.dir / "broken.db"
        path.write_bytes(b"this is definitely not a sqlite database file" * 20)
        with self.assertRaisesRegex(DatabaseError, "not a valid SQLite database"):
            TicketRepository(path)

    def test_unusable_path_gives_a_clear_error(self):
        blocker = self.dir / "blocker"
        blocker.write_text("I am a file, not a folder")
        with self.assertRaises(DatabaseError):
            TicketRepository(blocker / "helpdesk.db")


# ───────────────────────────── service layer ──────────────────────────
class ServiceTests(ServiceCase):
    def test_create_ticket(self):
        ticket = self.make()
        self.assertEqual((ticket.id, ticket.status, ticket.priority), (1, Status.OPEN, Priority.MEDIUM))
        self.assertEqual(ticket.created_at, "2026-11-13 10:00:00")
        self.assertEqual(self.make(priority="critical").priority, Priority.CRITICAL)

    def test_invalid_input_never_reaches_the_database(self):
        for kwargs in ({"name": ""}, {"issue": "no"}, {"priority": "urgent"}, {"name": "Ali2"}):
            with self.assertRaises(ValidationError):
                self.make(**kwargs)
        self.assertEqual(self.repo.count(), 0)

    def test_invalid_and_missing_ids(self):
        self.make()
        for bad in ("abc", "", "-1", "0", None):
            with self.assertRaises(ValidationError, msg=repr(bad)):
                self.service.get_ticket(bad)
        with self.assertRaisesRegex(TicketNotFoundError, "No ticket with ID 999"):
            self.service.get_ticket(999)
        for action in (lambda: self.service.update_ticket(999, issue="New issue text"),
                       lambda: self.service.close_ticket(999)):
            with self.assertRaises(TicketNotFoundError):
                action()

    def test_update_fields(self):
        ticket = self.make()
        self.clock.advance(hours=2)
        updated = self.service.update_ticket(ticket.id, priority="critical", status="in progress",
                                             issue="Printer jams on every page", customer_name="Ali R. Khan")
        self.assertEqual((updated.priority, updated.status), (Priority.CRITICAL, Status.IN_PROGRESS))
        self.assertEqual((updated.issue, updated.customer_name), ("Printer jams on every page", "Ali R. Khan"))
        self.assertEqual((updated.created_at, updated.updated_at), ("2026-11-13 10:00:00", "2026-11-13 12:00:00"))

    def test_update_rules(self):
        ticket = self.make()
        with self.assertRaisesRegex(ValidationError, "Nothing to update"):
            self.service.update_ticket(ticket.id)
        with self.assertRaisesRegex(InvalidOperationError, "No changes"):
            self.service.update_ticket(ticket.id, priority="Medium")
        with self.assertRaisesRegex(InvalidOperationError, "Close ticket"):
            self.service.update_ticket(ticket.id, status="Closed")
        with self.assertRaises(ValidationError):
            self.service.update_ticket(ticket.id, priority="whatever")
        self.assertEqual(self.service.get_ticket(ticket.id).priority, Priority.MEDIUM)

    def test_close_ticket(self):
        ticket = self.make()
        self.clock.advance(days=2)
        closed = self.service.close_ticket(ticket.id, "  Replaced the toner  ")
        self.assertEqual((closed.status, closed.resolution), (Status.CLOSED, "Replaced the toner"))
        self.assertEqual(closed.closed_at, "2026-11-15 10:00:00")
        self.assertEqual(closed.age_days(date(2026, 12, 1)), 2)           # age stops when closed
        with self.assertRaisesRegex(InvalidOperationError, "already closed"):
            self.service.close_ticket(ticket.id)

    def test_closing_without_a_note_is_allowed(self):
        self.assertIsNone(self.service.close_ticket(self.make().id).resolution)

    def test_closed_ticket_is_read_only_until_reopened(self):
        ticket = self.make()
        self.service.close_ticket(ticket.id, "Done")
        with self.assertRaisesRegex(InvalidOperationError, "is closed"):
            self.service.update_ticket(ticket.id, priority="High")
        reopened = self.service.update_ticket(ticket.id, status="Open")
        self.assertEqual((reopened.status, reopened.closed_at, reopened.resolution), (Status.OPEN, None, None))
        self.assertIs(self.service.update_ticket(ticket.id, priority="High").priority, Priority.HIGH)

    def test_list_and_search(self):
        a = self.make("Ayesha Khan", "Email is slow today", "High")
        b = self.make("Bilal Ahmed", "VPN keeps dropping", "Low")
        self.service.close_ticket(b.id)
        self.assertEqual([t.id for t in self.service.list_tickets()], [a.id, b.id])
        self.assertEqual([t.id for t in self.service.list_tickets(status="closed")], [b.id])
        self.assertEqual([t.id for t in self.service.list_tickets(priority="High")], [a.id])
        self.assertEqual([t.id for t in self.service.search_tickets("vpn")], [b.id])
        with self.assertRaises(ValidationError):
            self.service.search_tickets("v")
        with self.assertRaises(ValidationError):
            self.service.list_tickets(status="finished")

    def test_summary_counts_open_tickets_by_priority(self):
        a = self.make(priority="Critical")
        b = self.make(priority="Critical")
        self.make(priority="Low")
        c = self.make(priority="High")
        self.service.update_ticket(b.id, status="In Progress")
        self.service.close_ticket(c.id)
        summary = self.service.summary()
        self.assertEqual(summary.open_by_priority, {Priority.CRITICAL: 2, Priority.HIGH: 0,
                                                    Priority.MEDIUM: 0, Priority.LOW: 1})
        self.assertEqual((summary.total, summary.total_open, summary.total_closed), (4, 3, 1))
        self.assertEqual(summary.oldest_open.id, a.id)

    def test_summary_of_empty_database(self):
        summary = self.service.summary()
        self.assertEqual((summary.total, summary.total_open), (0, 0))
        self.assertIsNone(summary.oldest_open)


class DemoDataTests(ServiceCase):
    def test_seed_fills_an_empty_database_once(self):
        self.assertEqual(seed_demo(self.repo), 15)
        self.assertEqual(seed_demo(self.repo), 0)                          # never duplicates
        summary = self.service.summary()
        self.assertEqual((summary.total, summary.total_open, summary.total_closed), (15, 11, 4))


# ───────────────────────────── reports ───────────────────────────────
class ReportTests(ServiceCase):
    def test_summary_report_text_and_markdown(self):
        self.make(priority="Critical")
        self.make(priority="Low")
        text = reports.summary_report(self.service.summary(), self.service.today())
        self.assertIn("OPEN TICKETS BY PRIORITY", text)
        self.assertRegex(text, r"\| Critical \|\s+1 \|")
        markdown = reports.summary_report(self.service.summary(), self.service.today(), markdown=True)
        self.assertIn("| Priority", markdown)
        self.assertIn("# 🎫 Help-Desk Summary", markdown)

    def test_report_with_no_tickets_does_not_crash(self):
        text = reports.summary_report(self.service.summary(), self.service.today())
        self.assertIn("none (no open tickets)", text)

    def test_ticket_detail_shows_resolution_for_closed_tickets(self):
        ticket = self.service.close_ticket(self.make().id, "Replaced toner")
        detail = reports.ticket_detail(ticket, self.service.today())
        self.assertIn("Resolution : Replaced toner", detail)
        self.assertIn("Closed", detail)

    def test_export_creates_files_and_folders(self):
        self.make()
        with tempfile.TemporaryDirectory() as tmp:
            txt = reports.export_summary(self.service.summary(), Path(tmp) / "out" / "s.txt", self.service.today())
            md = reports.export_summary(self.service.summary(), Path(tmp) / "s.md", self.service.today())
            self.assertIn("HELP-DESK SUMMARY", txt.read_text(encoding="utf-8"))
            self.assertIn("## Overview", md.read_text(encoding="utf-8"))


# ───────────────────────────── user interface ────────────────────────
class CLITests(ServiceCase):
    def run_cli(self, answers):
        feed, output = iter(answers), []

        def fake_input(prompt=""):
            output.append(prompt)
            try:
                return next(feed)
            except StopIteration:
                raise EOFError

        HelpDeskCLI(self.service, fake_input, output.append).run()
        return "\n".join(output)

    def test_create_ticket_with_retries_after_invalid_input(self):
        text = self.run_cli(["1", "", "Ali Raza", "bad", "Cannot print invoices", "9", "2", "0"])
        self.assertIn("Customer name cannot be empty", text)
        self.assertIn("Issue description must be 5 to 500", text)
        self.assertIn("Priority must be one of", text)
        self.assertIn("Ticket #1 created (High priority", text)
        self.assertEqual(self.service.get_ticket(1).customer_name, "Ali Raza")

    def test_blank_priority_uses_medium(self):
        self.run_cli(["1", "Ali Raza", "Cannot print invoices", "", "0"])
        self.assertIs(self.service.get_ticket(1).priority, Priority.MEDIUM)

    def test_invalid_and_missing_ids_are_reported_not_crashed(self):
        self.make()
        text = self.run_cli(["3", "abc", "999", "6", "xyz", "42", "5", "0", "0"])
        self.assertIn("Ticket ID must be a whole number", text)
        self.assertIn("No ticket with ID 999 exists", text)
        self.assertIn("No ticket with ID 42 exists", text)
        self.assertIn("Goodbye", text)

    def test_update_flow(self):
        self.make()
        text = self.run_cli(["5", "1", "", "", "1", "2", "0"])
        ticket = self.service.get_ticket(1)
        self.assertEqual((ticket.priority, ticket.status), (Priority.CRITICAL, Status.IN_PROGRESS))
        self.assertIn("Ticket #1 updated", text)

    def test_update_with_no_values_shows_a_message(self):
        self.make()
        text = self.run_cli(["5", "1", "", "", "", "", "0"])
        self.assertIn("Nothing to update", text)

    def test_close_flow_with_cancel_then_confirm(self):
        self.make()
        text = self.run_cli(["6", "1", "Fixed", "n", "6", "1", "Fixed", "y", "6", "1", "0"])
        self.assertIn("Cancelled", text)
        self.assertIn("Ticket #1 closed", text)
        self.assertIn("is already closed", text)
        self.assertEqual(self.service.get_ticket(1).resolution, "Fixed")

    def test_list_search_and_summary_screens(self):
        self.make("Ayesha Khan", "Email is slow today", "High")
        text = self.run_cli(["2", "", "", "4", "ayesha", "4", "zzzz", "7", "0"])
        self.assertIn("1 ticket(s): 1 open, 0 closed", text)
        self.assertIn("matching 'ayesha'", text)
        self.assertIn("No tickets found matching 'zzzz'", text)
        self.assertIn("OPEN TICKETS BY PRIORITY", text)

    def test_unknown_menu_option_and_end_of_input(self):
        text = self.run_cli(["x", "99"])                    # input ends: must exit cleanly
        self.assertEqual(text.count("Please choose a number from the menu"), 2)
        self.assertIn("Goodbye", text)

    def test_export_flow(self):
        self.make()
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "summary.md")
            text = self.run_cli(["8", target, "0"])
            self.assertIn("Report saved", text)
            self.assertTrue(Path(target).exists())

    def test_export_to_an_impossible_path_is_reported(self):
        self.make()
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "file"
            blocker.write_text("x")
            text = self.run_cli(["8", str(blocker / "out.txt"), "0"])
            self.assertIn("Could not write the report", text)


# ───────────────────────────── architecture & entry point ─────────────
class ArchitectureTests(unittest.TestCase):
    """The task asks to separate database operations from user interaction."""

    def source(self, name):
        return (ROOT / "helpdesk" / name).read_text(encoding="utf-8")

    def test_only_database_py_contains_sql(self):
        for name in ("cli.py", "service.py", "reports.py", "validation.py", "models.py"):
            text = self.source(name)
            self.assertNotIn("sqlite3", text, name)
            for keyword in ("SELECT ", "INSERT ", "UPDATE tickets", "DELETE FROM"):
                self.assertNotIn(keyword, text, name)
        self.assertIn("SELECT", self.source("database.py"))

    def test_database_layer_has_no_user_interaction(self):
        text = self.source("database.py")
        self.assertNotIn("input(", text)
        self.assertNotIn("print(", text)


class MainTests(unittest.TestCase):
    def test_init_creates_database_and_exits(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            path = Path(tmp) / "data" / "t.db"
            self.assertEqual(main_module.main(["--db", str(path), "--init"]), 0)
            self.assertTrue(path.exists())
            self.assertIn("Database ready", out.getvalue())

    def test_seed_demo_flag(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            path = str(Path(tmp) / "t.db")
            main_module.main(["--db", path, "--seed-demo", "--init"])
            main_module.main(["--db", path, "--seed-demo", "--init"])
            self.assertIn("Added 15 demo ticket(s).", out.getvalue())
            self.assertIn("demo data was not added", out.getvalue())

    def test_damaged_database_returns_error_code(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            path = Path(tmp) / "bad.db"
            path.write_bytes(b"garbage" * 100)
            self.assertEqual(main_module.main(["--db", str(path)]), 1)
            self.assertIn("Cannot open the database", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
