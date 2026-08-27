import asyncio
from types import SimpleNamespace

from app.workers import domain_handlers


def test_notification_categories_are_deterministic() -> None:
    cases = (
        ("travel_order.created", "order"),
        ("payment.succeeded", "order"),
        ("fulfillment.completed", "order"),
        ("refund.completed", "order"),
        ("itinerary.export.completed", "itinerary"),
        ("route_calculation.completed", "itinerary"),
        ("ai.generation_completed", "itinerary"),
        ("companion_application.created", "community"),
        ("companion_application.accepted", "community"),
        ("message.created", "community"),
    )

    for event_type, category in cases:
        assert domain_handlers.notification_category(event_type) == category


def test_companion_acceptance_notification_targets_applicant_only() -> None:
    event = {
        "event_type": "companion_application.accepted",
        "payload": {"applicant_id": "user-2", "owner_id": "user-1", "request_id": "plan-1"},
    }
    assert domain_handlers.notification_targets(event) == ["user-2"]


def test_companion_application_created_notification_targets_owner_only() -> None:
    event = {
        "event_type": "companion_application.created",
        "payload": {"applicant_id": "user-2", "owner_id": "user-1", "request_id": "plan-1"},
    }
    assert domain_handlers.notification_targets(event) == ["user-1"]


def test_companion_application_created_notification_keeps_payload_and_respects_preferences() -> None:
    payload = {
        "applicant_id": "11111111-1111-4111-8111-111111111111",
        "owner_id": "22222222-2222-4222-8222-222222222222",
        "request_id": "33333333-3333-4333-8333-333333333333",
    }

    class Session:
        def __init__(self, settings: object) -> None:
            self.settings = settings
            self.notifications: list[object] = []

        async def get(self, _model: object, _user_id: str) -> object:
            return self.settings

        def add(self, notification: object) -> None:
            self.notifications.append(notification)

    enabled_session = Session(SimpleNamespace(notifications_enabled=True, community_notifications=True))
    asyncio.run(domain_handlers._notify_user(enabled_session, {"event_type": "companion_application.created", "payload": payload}))

    assert len(enabled_session.notifications) == 1
    notification = enabled_session.notifications[0]
    assert notification.user_id == "22222222-2222-4222-8222-222222222222"
    assert notification.notification_type == "companion_application.created"
    assert notification.payload_json == payload

    disabled_session = Session(SimpleNamespace(notifications_enabled=True, community_notifications=False))
    asyncio.run(domain_handlers._notify_user(disabled_session, {"event_type": "companion_application.created", "payload": payload}))

    assert disabled_session.notifications == []


def test_companion_lifecycle_notifications_use_only_their_safe_recipient_id() -> None:
    cases = (
        ("companion_application.rejected", {"applicant_id": "applicant", "owner_id": "owner"}, ["applicant"]),
        ("companion_application.withdrawn", {"applicant_id": "applicant", "owner_id": "owner"}, ["owner"]),
        ("companion_member.removed", {"user_id": "member", "owner_id": "owner"}, ["member"]),
        ("companion_member.left", {"user_id": "member", "owner_id": "owner"}, ["owner"]),
        ("companion_request.full", {"owner_id": "owner"}, ["owner"]),
        ("companion_request.completed", {"owner_id": "owner"}, ["owner"]),
    )
    for event_type, payload, expected in cases:
        assert domain_handlers.notification_targets({"event_type": event_type, "payload": payload}) == expected


def test_companion_lifecycle_notification_routes_are_registered_once() -> None:
    domain_handlers.register_domain_handlers()
    domain_handlers.register_domain_handlers()
    routes = domain_handlers.registered_routes.snapshot()
    event_types = (
        "companion_application.created",
        "companion_application.accepted",
        "companion_application.rejected",
        "companion_application.withdrawn",
        "companion_member.removed",
        "companion_member.left",
        "companion_request.full",
        "companion_request.completed",
    )
    for event_type in event_types:
        matching = [route for route in routes[event_type] if route.consumer_name == "notifications.companion"]
        assert len(matching) == 1
        assert matching[0].handler is domain_handlers._notify_user
