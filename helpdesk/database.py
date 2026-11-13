"""
Database layer. This is the ONLY file that contains SQL.

It knows nothing about the menu, about printing, or about business rules: it just
stores and fetches tickets. Every query is parameterised (`?`), so user text can never
change the meaning of a SQL statement.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .errors import DatabaseError
from .models import Priority, Status, Ticket

SCHEMA_FILE = Path(__file__).with_name("schema.sql")

_URGENCY_ORDER = "CASE priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END"
_STATUS_ORDER = "CASE status WHEN 'Closed' THEN 1 ELSE 0 END"      # open tickets first
_UPDATABLE_COLUMNS = {"customer_name", "issue", "priority", "status", "updated_at", "closed_at", "resolution"}


def _escape_like(text: str) -> str:
    """Make % and _ in the user's text match literally inside a LIKE pattern."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class TicketRepository:
    """Stores tickets in a SQLite database (a file, or ':memory:' for tests)."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        try:
            if self.db_path != ":memory:":
                Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            try:
                self._conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
            except Exception:
                self._conn.close()
                raise
        except (sqlite3.Error, OSError) as err:
            raise DatabaseError(self._explain(err)) from err

    # ---- housekeeping ------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "TicketRepository":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @staticmethod
    def _explain(err: Exception) -> str:
        text = str(err).lower()
        if "not a database" in text or "malformed" in text:
            return "The file is not a valid SQLite database (it may be damaged or a different file type)."
        if "locked" in text:
            return "The database is locked by another program. Close it and try again."
        if "unable to open" in text or isinstance(err, OSError):
            return f"The database file could not be opened or created: {err}"
        if isinstance(err, sqlite3.IntegrityError):
            return f"The database rejected the data: {err}"
        return f"Database error: {err}"

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        try:
            return self._conn.execute(sql, params).fetchall()
        except sqlite3.Error as err:
            raise DatabaseError(self._explain(err)) from err

    def _write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        try:
            with self._conn:                       # commits on success, rolls back on error
                return self._conn.execute(sql, params)
        except sqlite3.Error as err:
            raise DatabaseError(self._explain(err)) from err

    # ---- create / update ---------------------------------------------
    def add(self, customer_name: str, issue: str, priority: Priority, status: Status, created_at: str) -> int:
        cursor = self._write(
            "INSERT INTO tickets (customer_name, issue, priority, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (customer_name, issue, priority.value, status.value, created_at, created_at))
        return int(cursor.lastrowid)

    def update(self, ticket_id: int, **changes) -> bool:
        """Update the given columns. Returns False when no ticket has that ID."""
        unknown = set(changes) - _UPDATABLE_COLUMNS
        if unknown:
            raise ValueError(f"Cannot update column(s): {', '.join(sorted(unknown))}")
        if not changes:
            return self.get(ticket_id) is not None
        values = [v.value if hasattr(v, "value") else v for v in changes.values()]
        assignments = ", ".join(f"{column} = ?" for column in changes)       # column names come from the whitelist
        cursor = self._write(f"UPDATE tickets SET {assignments} WHERE id = ?", (*values, ticket_id))
        return cursor.rowcount > 0

    # ---- read ----------------------------------------------------------
    def get(self, ticket_id: int) -> Ticket | None:
        rows = self._query("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        return Ticket.from_row(rows[0]) if rows else None

    def list_all(self, status: Status | None = None, priority: Priority | None = None) -> list[Ticket]:
        return self._select("", [], status, priority)

    def search(self, keyword: str, status: Status | None = None, priority: Priority | None = None) -> list[Ticket]:
        """Tickets whose customer name or issue contains `keyword`, or whose ID equals it."""
        pattern = f"%{_escape_like(keyword)}%"
        clause = "(customer_name LIKE ? ESCAPE '\\' OR issue LIKE ? ESCAPE '\\' OR CAST(id AS TEXT) = ?)"
        return self._select(clause, [pattern, pattern, keyword.lstrip("#")], status, priority)

    def _select(self, clause: str, params: list, status, priority) -> list[Ticket]:
        conditions = [clause] if clause else []
        if status is not None:
            conditions.append("status = ?")
            params.append(status.value)
        if priority is not None:
            conditions.append("priority = ?")
            params.append(priority.value)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._query(f"SELECT * FROM tickets {where} "
                           f"ORDER BY {_STATUS_ORDER}, {_URGENCY_ORDER}, created_at, id", tuple(params))
        return [Ticket.from_row(r) for r in rows]

    # ---- statistics ----------------------------------------------------
    def count(self) -> int:
        return int(self._query("SELECT COUNT(*) AS n FROM tickets")[0]["n"])

    def count_by_status(self) -> dict[Status, int]:
        counts = {s: 0 for s in Status}
        for row in self._query("SELECT status, COUNT(*) AS n FROM tickets GROUP BY status"):
            counts[Status(row["status"])] = row["n"]
        return counts

    def count_open_by_priority_and_status(self) -> dict[Priority, dict[Status, int]]:
        matrix = {p: {s: 0 for s in Status.active()} for p in Priority}
        for row in self._query("SELECT priority, status, COUNT(*) AS n FROM tickets "
                               "WHERE status <> 'Closed' GROUP BY priority, status"):
            matrix[Priority(row["priority"])][Status(row["status"])] = row["n"]
        return matrix

    def oldest_open(self) -> Ticket | None:
        rows = self._query("SELECT * FROM tickets WHERE status <> 'Closed' ORDER BY created_at, id LIMIT 1")
        return Ticket.from_row(rows[0]) if rows else None
