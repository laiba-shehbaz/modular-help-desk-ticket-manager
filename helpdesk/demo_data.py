"""
Demo data for the fictional company "NovaTech Solutions" (all names and issues are invented).

It creates tickets through TicketService with a fixed clock, so the creation dates are
reproducible and the normal rules (validation, status changes, closing) are exercised.
"""
from __future__ import annotations

from datetime import datetime

from .models import Priority, Status
from .service import TicketService

_F = "%Y-%m-%d %H:%M"

# (customer, issue, priority, created, final status, status changed at, resolution)
DEMO_TICKETS = [
    ("Ayesha Khan", "Office internet is down since the morning, all staff are offline.", "Critical",
     "2026-11-02 08:40", "Open", None, None),
    ("Bilal Ahmed", "Payment gateway returns an error at checkout for every customer.", "Critical",
     "2026-11-10 11:05", "In Progress", "2026-11-10 11:30", None),
    ("Sana Malik", "Cannot log in to the customer portal after the password reset.", "High",
     "2026-11-04 09:15", "In Progress", "2026-11-04 14:00", None),
    ("Usman Raza", "Invoice INV-2041 shows the wrong tax amount.", "High",
     "2026-11-06 10:20", "Open", None, None),
    ("Hira Siddiqui", "Email attachments larger than 5 MB are not being delivered.", "High",
     "2026-11-09 15:45", "Open", None, None),
    ("Imran Sheikh", "Printer on the second floor shows a paper jam error constantly.", "Medium",
     "2026-11-03 13:10", "Open", None, None),
    ("Nadia Hussain", "Request to add two new users to the shared project folder.", "Medium",
     "2026-11-05 09:50", "In Progress", "2026-11-05 10:30", None),
    ("Faisal Qureshi", "Mobile app crashes when opening the order history page.", "Medium",
     "2026-11-08 16:25", "Open", None, None),
    ("Mehwish Tariq", "VPN disconnects every 20 minutes when working from home.", "Medium",
     "2026-11-11 08:55", "Open", None, None),
    ("Zain Abbas", "Please change the company logo on the email signature template.", "Low",
     "2026-11-07 12:00", "Open", None, None),
    ("Rabia Noor", "Monitor in meeting room B has a slight flicker.", "Low",
     "2026-11-12 10:10", "Open", None, None),
    ("Kamran Ali", "Forgot the Wi-Fi password for the guest network.", "Low",
     "2026-10-30 09:00", "Closed", "2026-10-30 09:20", "Sent the new guest password by email."),
    ("Saima Javed", "Laptop battery drains within one hour.", "Medium",
     "2026-10-31 14:30", "Closed", "2026-11-03 11:00", "Battery replaced under warranty."),
    ("Tariq Mehmood", "Website contact form does not send messages.", "High",
     "2026-11-01 10:00", "Closed", "2026-11-01 16:45", "Fixed the mail server settings and tested the form."),
    ("Farah Naeem", "Software licence for the design tool has expired.", "Medium",
     "2026-11-02 15:05", "Closed", "2026-11-04 09:30", "Licence renewed for one year."),
]


def _at(repository, moment: str) -> TicketService:
    when = datetime.strptime(moment, _F)
    return TicketService(repository, clock=lambda: when)


def seed_demo(repository) -> int:
    """Insert the demo tickets if the database is empty. Returns how many were added."""
    if repository.count() > 0:
        return 0
    for customer, issue, priority, created, final, changed, resolution in DEMO_TICKETS:
        ticket = _at(repository, created).create_ticket(customer, issue, Priority(priority))
        if final == Status.IN_PROGRESS.value:
            _at(repository, changed).update_ticket(ticket.id, status=Status.IN_PROGRESS)
        elif final == Status.CLOSED.value:
            _at(repository, changed).close_ticket(ticket.id, resolution)
    return len(DEMO_TICKETS)
