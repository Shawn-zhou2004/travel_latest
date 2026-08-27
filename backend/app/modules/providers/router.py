from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.auth.dependencies import CurrentBackoffice, CurrentConsumer
from app.modules.providers.models import Experience, ExperienceSession, Provider
from app.modules.providers.schemas import (
    BookingCreate,
    ExperienceCreated,
    ExperienceCreate,
    ExperienceUpdate,
    ProviderExperience,
    ProviderExperienceBooking,
    ProviderExperienceBookingPage,
    ProviderExperiencePage,
    ProviderExperienceSession,
    ProviderExperienceSessionPage,
    ProviderApplicationCreate,
    PublicExperience,
    PublicExperienceDetail,
    PublicExperiencePage,
    PublicExperienceSession,
    PublicProvider,
    ReviewCreate,
    SessionCreated,
    SessionCreate,
    SessionUpdate,
    VerifiedPoi,
    VerifyBooking,
)
from app.modules.providers.service import ProviderError, ProviderService

router = APIRouter(tags=["providers"])
Session = Annotated[AsyncSession, Depends(get_session)]


def _service(session: Session) -> ProviderService:
    return ProviderService(session)


Service = Annotated[ProviderService, Depends(_service)]


def _public_experience(item: Experience, provider: Provider) -> PublicExperience:
    return PublicExperience(
        id=item.id,
        title=item.title,
        poi=VerifiedPoi(id=item.poi_id, name=item.poi_name, address=item.poi_address),
        provider=PublicProvider(id=provider.id, name=provider.legal_name),
        price_amount=item.price_amount,
        currency=item.currency,
        status="published",
    )


def _provider_experience(item: Experience) -> ProviderExperience:
    return ProviderExperience(
        id=item.id,
        provider_id=item.provider_id,
        title=item.title,
        description=item.description,
        poi=VerifiedPoi(id=item.poi_id, name=item.poi_name, address=item.poi_address),
        price_amount=item.price_amount,
        currency=item.currency,
        cancellation_policy=item.cancellation_policy,
        status=item.status,
    )


def _provider_session(session: ExperienceSession) -> ProviderExperienceSession:
    return ProviderExperienceSession(
        id=session.id,
        experience_id=session.experience_id,
        starts_at=session.starts_at,
        capacity=session.capacity,
        reserved_count=session.reserved_count,
        remaining_capacity=session.capacity - session.reserved_count,
        price_amount=session.price_amount,
        currency=session.currency,
        status=session.status,
    )


def _error(error: ProviderError) -> HTTPException:
    return HTTPException(409 if error.code in {"INVALID_PROVIDER_TRANSITION", "DUPLICATE_BOOKING", "SESSION_CAPACITY_EXCEEDED", "BOOKING_NOT_VERIFIABLE", "DUPLICATE_REVIEW"} else 403 if "FORBIDDEN" in error.code else 404 if error.code.endswith("NOT_FOUND") else 503 if error.code == "MAP_UNAVAILABLE" else 422, detail={"code": error.code, "message": error.message})


@router.get("/experiences", response_model=PublicExperiencePage)
async def list_public_experiences(
    service: Service,
    provider_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> PublicExperiencePage:
    experiences = await service.list_public_experiences(provider_id, limit)
    return PublicExperiencePage(items=[_public_experience(item, provider) for item, provider in experiences])


@router.get("/experiences/{experience_id}", response_model=PublicExperienceDetail)
async def get_public_experience(experience_id: str, service: Service) -> PublicExperienceDetail:
    try:
        item, provider, sessions = await service.get_public_experience(experience_id)
    except ProviderError as error:
        raise _error(error) from error
    public = _public_experience(item, provider)
    return PublicExperienceDetail(
        **public.model_dump(),
        description=item.description,
        cancellation_policy=item.cancellation_policy,
        sessions=[
            PublicExperienceSession(
                id=session.id,
                starts_at=session.starts_at,
                price_amount=session.price_amount if session.price_amount is not None else item.price_amount,
                currency=session.currency if session.currency is not None else item.currency,
                remaining_capacity=session.capacity - session.reserved_count,
                status="scheduled",
            )
            for session in sessions
        ],
    )


@router.post("/provider-applications", status_code=status.HTTP_201_CREATED)
async def apply(body: ProviderApplicationCreate, claims: CurrentConsumer, service: Service) -> dict:
    try: provider = await service.apply(claims.user_id, **body.model_dump())
    except ProviderError as error: raise _error(error) from error
    return {"id": provider.id, "status": provider.status}


@router.get("/provider/experiences", response_model=ProviderExperiencePage)
async def list_provider_experiences(provider_id: str, claims: CurrentBackoffice, service: Service) -> ProviderExperiencePage:
    try:
        items = await service.list_workspace_experiences(provider_id, claims.user_id, claims.roles)
    except ProviderError as error:
        raise _error(error) from error
    return ProviderExperiencePage(items=[_provider_experience(item) for item in items])


@router.get("/provider/experiences/{experience_id}", response_model=ProviderExperience)
async def get_provider_experience(experience_id: str, claims: CurrentBackoffice, service: Service) -> ProviderExperience:
    try:
        item = await service.get_workspace_experience(experience_id, claims.user_id, claims.roles)
    except ProviderError as error:
        raise _error(error) from error
    return _provider_experience(item)


@router.patch("/provider/experiences/{experience_id}", response_model=ProviderExperience)
async def update_provider_experience(
    experience_id: str, body: ExperienceUpdate, claims: CurrentBackoffice, service: Service
) -> ProviderExperience:
    try:
        item = await service.update_workspace_experience(experience_id, claims.user_id, claims.roles, **body.model_dump(exclude_unset=True))
    except ProviderError as error:
        raise _error(error) from error
    return _provider_experience(item)


@router.get("/provider/experiences/{experience_id}/sessions", response_model=ProviderExperienceSessionPage)
async def list_provider_sessions(
    experience_id: str, claims: CurrentBackoffice, service: Service
) -> ProviderExperienceSessionPage:
    try:
        items = await service.list_workspace_sessions(experience_id, claims.user_id, claims.roles)
    except ProviderError as error:
        raise _error(error) from error
    return ProviderExperienceSessionPage(items=[_provider_session(item) for item in items])


@router.get("/provider/experience-bookings", response_model=ProviderExperienceBookingPage)
async def list_provider_bookings(
    provider_id: str,
    claims: CurrentBackoffice,
    service: Service,
    status_filter: str | None = Query(default=None, alias="status"),
) -> ProviderExperienceBookingPage:
    try:
        items = await service.list_workspace_bookings(provider_id, claims.user_id, claims.roles, status_filter)
    except ProviderError as error:
        raise _error(error) from error
    return ProviderExperienceBookingPage(items=[
        ProviderExperienceBooking(
            id=booking.id,
            experience_title=experience.title,
            starts_at=session.starts_at,
            traveler_count=booking.traveler_count,
            status=booking.status,
            verified_at=booking.verified_at,
        )
        for booking, session, experience in items
    ])


@router.patch("/provider/experiences/{experience_id}/sessions/{session_id}", response_model=ProviderExperienceSession)
async def update_provider_session(
    experience_id: str, session_id: str, body: SessionUpdate, claims: CurrentBackoffice, service: Service
) -> ProviderExperienceSession:
    try:
        item = await service.update_workspace_session(
            experience_id, session_id, claims.user_id, claims.roles, **body.model_dump(exclude_unset=True)
        )
    except ProviderError as error:
        raise _error(error) from error
    return _provider_session(item)


@router.post("/provider/experiences", response_model=ExperienceCreated, status_code=status.HTTP_201_CREATED)
async def create_experience(provider_id: str, body: ExperienceCreate, claims: CurrentBackoffice, service: Service) -> ExperienceCreated:
    try: item = await service.create_experience(provider_id, claims.user_id, claims.roles, **body.model_dump())
    except ProviderError as error: raise _error(error) from error
    return ExperienceCreated(id=item.id, status=item.status)


@router.post("/provider/experiences/{experience_id}/sessions", response_model=SessionCreated, status_code=status.HTTP_201_CREATED)
async def create_session(experience_id: str, body: SessionCreate, claims: CurrentBackoffice, service: Service) -> SessionCreated:
    try: item = await service.create_session(experience_id, claims.user_id, claims.roles, **body.model_dump())
    except ProviderError as error: raise _error(error) from error
    return SessionCreated(id=item.id, status=item.status, remaining_capacity=item.capacity - item.reserved_count)


@router.post("/experience-bookings", status_code=status.HTTP_201_CREATED)
async def create_booking(body: BookingCreate, claims: CurrentConsumer, service: Service) -> dict:
    try: item = await service.book(claims.user_id, body.experience_session_id, body.traveler_count)
    except ProviderError as error: raise _error(error) from error
    return {"id": item.id, "status": item.status, "travel_order_id": None, "verification_code": item.verification_code}


@router.post("/provider/experience-bookings/{booking_id}:verify")
async def verify_booking(booking_id: str, provider_id: str, body: VerifyBooking, claims: CurrentBackoffice, service: Service) -> dict:
    try: item = await service.verify(booking_id, provider_id, claims.user_id, claims.roles, body.verification_code)
    except ProviderError as error: raise _error(error) from error
    return {"id": item.id, "status": item.status, "verified_at": item.verified_at}


@router.post("/experience-bookings/{booking_id}/evaluations", status_code=status.HTTP_201_CREATED)
async def create_review(booking_id: str, body: ReviewCreate, claims: CurrentConsumer, service: Service) -> dict:
    try: item = await service.review_booking(booking_id, claims.user_id, body.rating, body.body)
    except ProviderError as error: raise _error(error) from error
    return {"id": item.id, "rating": item.rating, "body": item.body, "status": "published"}
