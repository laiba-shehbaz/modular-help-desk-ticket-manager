"""
Formatting of tables, ticket details and the summary report.

Pure functions: they take objects and return text. No database access, no input().
"""
from __future__ import annotations

import textwrap
from datetime import date, datetime
from pathlib import Path

from .models import Priority, Status, Ticket, TicketSummary


def render_table(headers, rows, aligns=None, markdown: bool = False) -> str:
    aligns = aligns or ["<"] * len(headers)
    rows = [[str(c) for c in row] for row in rows]
    widths = [max([3, len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]

    def fmt(cells):
        return "| " + " | ".join(f"{c:{a}{w}}" for c, a, w in zip(cells, aligns, widths)) + " |"

    if markdown:
        sep = "| " + " | ".join(("-" * (w - 1) + ":") if a == ">" else (":" + "-" * (w - 1))
                                for a, w in zip(aligns, widths)) + " |"
        return "\n".join([fmt(headers), sep] + [fmt(r) for r in rows])
    line = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    return "\n".join([line, fmt(headers), line] + [fmt(r) for r in rows] + [line])


def shorten(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def tickets_table(tickets: list[Ticket]) -> str:
    rows = [[t.id, t.created_date, shorten(t.customer_name, 20), t.priority.value, t.status.value,
             shorten(t.issue, 38)] for t in tickets]
    return render_table(["ID", "Created", "Customer", "Priority", "Status", "Issue"], rows,
                        [">", "<", "<", "<", "<", "<"])


def ticket_detail(ticket: Ticket, today: date) -> str:
    age = ticket.age_days(today)
    lines = [f"Ticket #{ticket.id}",
             f"  Customer   : {ticket.customer_name}",
             f"  Priority   : {ticket.priority.value}",
             f"  Status     : {ticket.status.value}",
             f"  Created    : {ticket.created_at}",
             f"  Updated    : {ticket.updated_at}",
             f"  Age        : {age} day(s) {'(still open)' if ticket.is_open else '(until closed)'}"]
    issue = textwrap.wrap(ticket.issue, 60) or [""]
    lines.append(f"  Issue      : {issue[0]}")
    lines += [f"               {part}" for part in issue[1:]]
    if not ticket.is_open:
        lines.append(f"  Closed     : {ticket.closed_at}")
        lines.append(f"  Resolution : {ticket.resolution or '(no note)'}")
    return "\n".join(lines)


def _bar(count: int, total: int) -> str:
    return "█" * max(1, round(count / total * 20)) if total and count else ""


def summary_report(summary: TicketSummary, today: date, markdown: bool = False, generated: datetime | None = None) -> str:
    stamp = (generated or datetime.now()).strftime("%Y-%m-%d %H:%M")
    open_total = summary.total_open
    matrix = summary.open_matrix

    # open tickets by priority (the main requirement)
    rows = []
    for priority in Priority.by_urgency():
        opened, working = matrix[priority][Status.OPEN], matrix[priority][Status.IN_PROGRESS]
        total = opened + working
        share = f"{total / open_total * 100:.0f}%" if open_total else "-"
        rows.append([priority.value, opened, working, total, share, _bar(total, open_total)])
    rows.append(["TOTAL", sum(matrix[p][Status.OPEN] for p in Priority), sum(matrix[p][Status.IN_PROGRESS] for p in Priority),
                 open_total, "100%" if open_total else "-", ""])
    priority_table = render_table(["Priority", "Open", "In Progress", "Total open", "Share", "Chart"], rows,
                                  ["<", ">", ">", ">", ">", "<"], markdown)

    status_rows = [[s.value, summary.status_counts.get(s, 0),
                    f"{summary.status_counts.get(s, 0) / summary.total * 100:.0f}%" if summary.total else "-"]
                   for s in Status]
    status_table = render_table(["Status", "Tickets", "Share"], status_rows, ["<", ">", ">"], markdown)

    oldest = summary.oldest_open
    oldest_text = (f"#{oldest.id}, {oldest.age_days(today)} day(s) old, {oldest.priority.value}, {oldest.customer_name}"
                   if oldest else "none (no open tickets)")
    overview = [
        ("Total tickets", summary.total),
        ("Open tickets", f"{open_total}  (Open {summary.status_counts.get(Status.OPEN, 0)}, "
                         f"In Progress {summary.status_counts.get(Status.IN_PROGRESS, 0)})"),
        ("Closed tickets", summary.total_closed),
        ("Oldest open ticket", oldest_text),
    ]

    def heading(title: str) -> str:
        return f"\n## {title}\n" if markdown else f"\n{title}\n{'-' * len(title)}"

    out = ["# 🎫 Help-Desk Summary: Open Tickets by Priority" if markdown else "HELP-DESK SUMMARY: OPEN TICKETS BY PRIORITY",
           f"_Generated: {stamp}_" if markdown else f"Generated: {stamp}", heading("Overview")]
    out += [f"- **{k}:** {v}" if markdown else f"  {k:<20}{v}" for k, v in overview]
    out += [heading("Open tickets by priority"), priority_table, heading("All tickets by status"), status_table]
    return "\n".join(out) + "\n"


def export_summary(summary: TicketSummary, path: str | Path, today: date) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summary_report(summary, today, markdown=path.suffix.lower() == ".md"), encoding="utf-8")
    return path
