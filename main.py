#!/usr/bin/env python3
"""
🎫 Help-Desk Ticket Manager - entry point.

    python main.py                  start the menu (database: data/helpdesk.db)
    python main.py --init           only create the database and tables, then exit
    python main.py --seed-demo      fill an EMPTY database with 15 demo tickets, then start
    python main.py --db other.db    use a different database file
"""
from __future__ import annotations

import argparse
import sys

from helpdesk.cli import HelpDeskCLI
from helpdesk.database import TicketRepository
from helpdesk.demo_data import seed_demo
from helpdesk.errors import DatabaseError
from helpdesk.service import TicketService


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Small help-desk ticket manager (SQLite).")
    parser.add_argument("--db", default="data/helpdesk.db", help="SQLite database file (default: data/helpdesk.db)")
    parser.add_argument("--init", action="store_true", help="create the database and tables, then exit")
    parser.add_argument("--seed-demo", action="store_true", help="add demo tickets if the database is empty")
    args = parser.parse_args(argv)

    try:
        repository = TicketRepository(args.db)
    except DatabaseError as err:
        print(f"Cannot open the database: {err}")
        return 1

    with repository:
        if args.seed_demo:
            added = seed_demo(repository)
            print(f"Added {added} demo ticket(s)." if added else "Database is not empty: demo data was not added.")
        if args.init:
            print(f"Database ready: {args.db} ({repository.count()} ticket(s)).")
            return 0
        try:
            HelpDeskCLI(TicketService(repository)).run()
        except DatabaseError as err:
            print(f"Database problem: {err}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
