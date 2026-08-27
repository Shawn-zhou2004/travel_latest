from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping, Protocol

from app.modules.orders.models import MockTransportTicket


@dataclass(frozen=True)
class MockTicketIssueResult:
    issued: bool
    code: str
    mock_ticket_no: str | None = None
    seat_assignments: Mapping[str, object] | None = None


class MockTransportTicketIssuer(Protocol):
    async def issue(self, ticket: MockTransportTicket) -> MockTicketIssueResult: ...


class DeterministicMockTransportTicketIssuer:
    """Demonstration-only issuer. Its identifiers are never supplier confirmations."""

    async def issue(self, ticket: MockTransportTicket) -> MockTicketIssueResult:
        suffix = sha256(ticket.order_id.encode()).hexdigest()[:10].upper()
        passengers = ticket.passenger_facts.get("passengers", [])
        assignments = {
            "is_mock": True,
            "seats": [f"{index + 1:02d}{'A' if index % 2 == 0 else 'C'}" for index, _ in enumerate(passengers)],
        }
        return MockTicketIssueResult(True, "ISSUED", f"MOCK-{ticket.transport_type.upper()}-{suffix}", assignments)
