"""All custom exceptions in one place, so every layer can raise and catch them."""


class HelpDeskError(Exception):
    """Base class: the user interface catches this and shows the message."""


class ValidationError(HelpDeskError):
    """Input is not acceptable (empty, too long, wrong format...)."""


class TicketNotFoundError(HelpDeskError):
    """No ticket exists with the requested ID."""

    def __init__(self, ticket_id: int):
        super().__init__(f"No ticket with ID {ticket_id} exists.")
        self.ticket_id = ticket_id


class InvalidOperationError(HelpDeskError):
    """The request is valid input but breaks a rule (e.g. closing a closed ticket)."""


class DatabaseError(HelpDeskError):
    """The database could not be opened, read or written."""
