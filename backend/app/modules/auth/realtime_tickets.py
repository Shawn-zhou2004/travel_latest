from app.modules.auth.service import AuthService


def consume_realtime_ticket(
    service: AuthService, ticket: str, user_id: str, resource_type: str, resource_id: str
) -> bool:
    """Consume a ticket before the WebSocket layer checks resource membership."""
    return service.consume_realtime_ticket(ticket, user_id, resource_type, resource_id)
