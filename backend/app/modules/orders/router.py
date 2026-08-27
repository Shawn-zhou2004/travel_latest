from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.integrations.alipay.adapter import AlipayAdapter, get_alipay_adapter
from app.integrations.mcp.transport import (
    FlightOfferProvider,
    MagicFlightOfferProvider,
    MagicMcpTransportConfig,
    MagicTrainOfferProvider,
    TrainOfferProvider,
    TransportOfferSearchRequest,
)
from app.integrations.suppliers.client import (
    SupplierAdapter,
    SupplierFulfillmentConfirmationRequest,
    SupplierFulfillmentConfirmationResult,
    SupplierOffer,
    SupplierSearchRequest,
    SupplierSearchResult,
    UnavailableSupplierAdapter,
)
from app.modules.auth.dependencies import CurrentAuthenticated, CurrentConsumer
from app.modules.orders.models import MockTransportTicket, TravelOffer, TravelOrder, TravelSearchJob
from app.modules.orders.schemas import MockTicketResponse, OfferResponse, OrderCreate, OrderResponse, PaymentCreate, PaymentResponse, RefundCreate, RefundResponse, SearchJobCreate, SearchJobResponse
from app.modules.orders.services import DomainError, OrderService, PaymentService, RefundService, SearchService

# Integration hook: app.api.router must include this router under its existing /api/v1 prefix.
router = APIRouter(tags=["travel-orders"])
Session = Annotated[AsyncSession, Depends(get_session)]


class _TransportSupplierAdapter:
    def __init__(self, provider: TrainOfferProvider | FlightOfferProvider) -> None:
        self._provider = provider

    async def search(self, request: SupplierSearchRequest) -> SupplierSearchResult:
        result = await self._provider.search(
            TransportOfferSearchRequest(
                origin=request.origin,
                destination=request.destination,
                depart_date=request.depart_date,
                passenger_count=request.passenger_count,
            )
        )
        return SupplierSearchResult(
            available=result.available,
            code=result.code,
            message=result.message,
            offers=tuple(
                SupplierOffer(
                    source=offer.source,
                    external_offer_id=offer.external_offer_id,
                    title=f"{offer.carrier_number} {offer.seat_or_cabin_class}",
                    amount=str(offer.amount),
                    currency=offer.currency,
                    valid_until=offer.valid_until,
                    availability=offer.availability,
                    change_rules=dict(offer.change_rules),
                    snapshot={
                        "transport_type": offer.transport_type,
                        "origin": offer.origin,
                        "destination": offer.destination,
                        "carrier_number": offer.carrier_number,
                        "seat_or_cabin_class": offer.seat_or_cabin_class,
                        "departure_at": offer.departure_at.isoformat(),
                        "arrival_at": offer.arrival_at.isoformat(),
                    },
                )
                for offer in result.offers
            ),
        )

    async def confirm_fulfillment(
        self,
        request: SupplierFulfillmentConfirmationRequest,
    ) -> SupplierFulfillmentConfirmationResult:
        return await UnavailableSupplierAdapter().confirm_fulfillment(request)


def get_supplier_adapter(body: SearchJobCreate) -> SupplierAdapter:
    from app.core.settings import Settings

    settings = Settings()
    config = MagicMcpTransportConfig(
        train_url=settings.magic_mcp_train_url,
        train_tool=settings.magic_mcp_train_tool,
        flight_url=settings.magic_mcp_flight_url,
        flight_tool=settings.magic_mcp_flight_tool,
        api_key=settings.magic_mcp_api_key,
        timeout_seconds=settings.magic_mcp_timeout_seconds,
    )
    if body.search_type == "train" and all((config.train_url, config.train_tool, config.api_key)) and config.timeout_seconds > 0:
        return _TransportSupplierAdapter(MagicTrainOfferProvider(config))
    if body.search_type == "flight" and all((config.flight_url, config.flight_tool, config.api_key)) and config.timeout_seconds > 0:
        return _TransportSupplierAdapter(MagicFlightOfferProvider(config))
    return UnavailableSupplierAdapter()


def provide_alipay_adapter() -> AlipayAdapter:
    from app.core.settings import Settings

    return get_alipay_adapter(Settings())


def _offer_response(offer: TravelOffer) -> OfferResponse:
    return OfferResponse(id=offer.id, source=offer.source, title=offer.title, amount=offer.amount, currency=offer.currency, availability=offer.availability, valid_until=offer.valid_until, retrieved_at=offer.retrieved_at, change_rules=dict(offer.change_rules))


async def _job_response(session: AsyncSession, job: TravelSearchJob) -> SearchJobResponse:
    offers = list((await session.scalars(select(TravelOffer).where(TravelOffer.search_job_id == job.id))).all())
    return SearchJobResponse(id=job.id, status=job.status, source=job.source, unavailable_code=job.unavailable_code, retrieved_at=job.retrieved_at, offers=[_offer_response(offer) for offer in offers])


@router.post("/travel-search-jobs", response_model=SearchJobResponse, status_code=status.HTTP_201_CREATED)
async def create_search_job(body: SearchJobCreate, claims: CurrentConsumer, session: Session, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)], supplier: Annotated[SupplierAdapter, Depends(get_supplier_adapter)]) -> SearchJobResponse:
    job = await SearchService(session, supplier).create(claims.user_id, idempotency_key, SupplierSearchRequest(**body.model_dump()))
    return await _job_response(session, job)


@router.get("/travel-search-jobs/{job_id}", response_model=SearchJobResponse)
async def get_search_job(job_id: str, claims: CurrentConsumer, session: Session) -> SearchJobResponse:
    job = await session.get(TravelSearchJob, job_id)
    if job is None or job.user_id != claims.user_id:
        raise HTTPException(404, "Search job not found.")
    return await _job_response(session, job)


@router.get("/travel-search-jobs/{job_id}/offers", response_model=list[OfferResponse])
async def list_offers(job_id: str, claims: CurrentConsumer, session: Session) -> list[OfferResponse]:
    job = await session.get(TravelSearchJob, job_id)
    if job is None or job.user_id != claims.user_id:
        raise HTTPException(404, "Search job not found.")
    return [_offer_response(offer) for offer in (await session.scalars(select(TravelOffer).where(TravelOffer.search_job_id == job_id))).all()]


@router.post("/travel-orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(body: OrderCreate, claims: CurrentConsumer, session: Session, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> OrderResponse:
    try:
        order = await OrderService(session).create_from_offer(claims.user_id, body.offer_id, idempotency_key, [passenger.model_dump() for passenger in body.passengers])
    except DomainError as error:
        raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message}) from error
    return OrderResponse.model_validate(order, from_attributes=True)


@router.get("/travel-orders/{order_id}/mock-ticket", response_model=MockTicketResponse)
async def get_mock_ticket(order_id: str, claims: CurrentConsumer, session: Session) -> MockTicketResponse:
    order = await session.get(TravelOrder, order_id)
    if order is None or order.user_id != claims.user_id:
        raise HTTPException(404, "Order not found.")
    ticket = await session.scalar(select(MockTransportTicket).where(MockTransportTicket.order_id == order_id))
    if ticket is None:
        raise HTTPException(404, "Mock ticket not found.")
    return MockTicketResponse.model_validate(ticket, from_attributes=True)


@router.get("/travel-orders", response_model=list[OrderResponse])
async def list_orders(claims: CurrentConsumer, session: Session) -> list[OrderResponse]:
    orders = (await session.scalars(select(TravelOrder).where(TravelOrder.user_id == claims.user_id).order_by(TravelOrder.created_at.desc()))).all()
    return [OrderResponse.model_validate(order, from_attributes=True) for order in orders]


@router.post("/travel-orders/{order_id}/payments", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(order_id: str, body: PaymentCreate, claims: CurrentConsumer, session: Session, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)], adapter: Annotated[AlipayAdapter, Depends(provide_alipay_adapter)]) -> PaymentResponse:
    order = await session.get(TravelOrder, order_id)
    if order is None or order.user_id != claims.user_id:
        raise HTTPException(404, "Order not found.")
    try:
        payment, redirect_url = await PaymentService(session, adapter).create_checkout(order, idempotency_key)
    except DomainError as error:
        raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message}) from error
    return PaymentResponse(id=payment.id, payment_no=payment.payment_no, amount=payment.amount, currency=payment.currency, status=payment.status, redirect_url=redirect_url)


@router.post("/travel-orders/{order_id}:query-payment", response_model=OrderResponse)
async def query_payment(order_id: str, claims: CurrentAuthenticated, session: Session, adapter: Annotated[AlipayAdapter, Depends(provide_alipay_adapter)]) -> OrderResponse:
    order = await session.get(TravelOrder, order_id)
    is_admin = claims.audience == "admin" and "platform_admin" in claims.roles
    if order is None or (not is_admin and order.user_id != claims.user_id):
        raise HTTPException(404, detail={"code": "ORDER_NOT_FOUND", "message": "Order not found."})
    try:
        order = await PaymentService(session, adapter).query_order_payment(order)
    except DomainError as error:
        raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message}) from error
    return OrderResponse.model_validate(order, from_attributes=True)


@router.post("/travel-orders/{order_id}/refunds", response_model=RefundResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_refund(order_id: str, body: RefundCreate, claims: CurrentConsumer, session: Session, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)], adapter: Annotated[AlipayAdapter, Depends(provide_alipay_adapter)]) -> RefundResponse:
    try:
        refund = await RefundService(session, adapter).create(order_id, claims.user_id, idempotency_key, body.amount, body.currency, body.reason)
    except DomainError as error:
        raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message}) from error
    return RefundResponse(id=refund.id, status=refund.status, amount=refund.amount, currency=refund.currency)


@router.post("/payments/alipay/callback", response_class=PlainTextResponse)
async def alipay_callback(request: Request, session: Session, adapter: Annotated[AlipayAdapter, Depends(provide_alipay_adapter)]) -> PlainTextResponse:
    raw_body = await request.body()
    if len(raw_body) > 16_384:
        return PlainTextResponse("failure", status_code=status.HTTP_400_BAD_REQUEST)
    try:
        pairs = parse_qsl(raw_body.decode("utf-8"), keep_blank_values=True, strict_parsing=True, max_num_fields=32)
    except (UnicodeDecodeError, ValueError):
        return PlainTextResponse("failure", status_code=status.HTTP_400_BAD_REQUEST)
    if len({key for key, _ in pairs}) != len(pairs):
        return PlainTextResponse("failure", status_code=status.HTTP_400_BAD_REQUEST)
    payload = dict(pairs)
    try:
        await PaymentService(session, adapter).handle_callback(payload)
    except DomainError:
        return PlainTextResponse("failure", status_code=status.HTTP_400_BAD_REQUEST)
    return PlainTextResponse("success")
