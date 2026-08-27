"""Integration hook: ``api_router.include_router(router)`` in app.api.router."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.auth.dependencies import CurrentConsumer
from app.modules.community.schemas import CompanionPlanCreate, CompanionPlanResponse, FieldNoteCreate, FieldNoteResponse
from app.modules.community.service import CommunityError, CommunityService
from app.modules.itineraries.schemas import CollaboratorResponse, CompanionWorkspaceSummaryResponse, CreateItineraryRequest, CreateShareTokenRequest, InviteCollaboratorRequest, ItineraryDetailResponse, ItineraryResponse, ItineraryVersionDetailResponse, ItineraryVersionResponse, ManualPlanCreateRequest, OperationRequest, OperationResponse, PublicItineraryResponse, RestoreVersionRequest, RouteCalculationJobResponse, ShareTokenResponse, UpdateCollaboratorRequest
from app.modules.itineraries.service import ItineraryError, ItineraryService
from app.modules.trip_support.router import router as trip_support_router

router = APIRouter(prefix="/itineraries", tags=["itineraries"])
router.include_router(trip_support_router)
Session = Annotated[AsyncSession, Depends(get_session)]


def _service(session: Session) -> ItineraryService:
    return ItineraryService(session)


Service = Annotated[ItineraryService, Depends(_service)]


def _itinerary_error(error: ItineraryError) -> HTTPException:
    status_code = {
        "FORBIDDEN": status.HTTP_403_FORBIDDEN,
        "ITINERARY_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "COMPANION_PLAN_ACTIVE": status.HTTP_409_CONFLICT,
    }.get(error.code, status.HTTP_422_UNPROCESSABLE_CONTENT)
    return HTTPException(status_code, detail={"code": error.code, "message": error.message})


def _community_error(error: CommunityError) -> HTTPException:
    status_code = 403 if error.code == "FORBIDDEN" else 404 if error.code.endswith("NOT_FOUND") else 422
    return HTTPException(status_code, detail={"code": error.code, "message": error.message})


@router.post("", response_model=ItineraryResponse, status_code=status.HTTP_201_CREATED)
async def create_itinerary(body: CreateItineraryRequest, claims: CurrentConsumer, service: Service) -> ItineraryResponse:
    return ItineraryResponse.model_validate(await service.create_itinerary(claims.user_id, **body.model_dump()))


@router.post(":manual-plan", response_model=ItineraryResponse, status_code=status.HTTP_201_CREATED)
async def create_manual_plan(body: ManualPlanCreateRequest, claims: CurrentConsumer, service: Service) -> ItineraryResponse:
    return ItineraryResponse.model_validate(await service.create_manual_plan(
        claims.user_id,
        title=body.title,
        start_date=body.start_date,
        end_date=body.end_date,
        destination=body.destination.model_dump(),
    ))


@router.get("", response_model=list[ItineraryResponse])
async def list_itineraries(claims: CurrentConsumer, service: Service) -> list[ItineraryResponse]:
    itineraries = await service.list_itineraries(claims.user_id)
    return [
        ItineraryResponse.model_validate({
            **ItineraryResponse.model_validate(itinerary).model_dump(),
            "access_role": await service.get_access_role(itinerary, claims.user_id),
        })
        for itinerary in itineraries
    ]


@router.delete("/{itinerary_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_itinerary(itinerary_id: str, claims: CurrentConsumer, service: Service) -> Response:
    try:
        await service.delete_itinerary(itinerary_id, claims.user_id)
    except ItineraryError as error:
        await service.session.rollback()
        raise _itinerary_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{itinerary_id}", response_model=ItineraryDetailResponse)
async def get_itinerary(itinerary_id: str, claims: CurrentConsumer, service: Service) -> ItineraryDetailResponse:
    itinerary = await service.get_itinerary(itinerary_id, claims.user_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail={"code": "ITINERARY_NOT_FOUND", "message": "The itinerary is unavailable."})
    response = ItineraryResponse.model_validate(itinerary).model_dump()
    response["snapshot"] = await service.get_snapshot(itinerary)
    response["access_role"] = await service.get_access_role(itinerary, claims.user_id)
    return ItineraryDetailResponse.model_validate(response)


@router.get("/{itinerary_id}/companion-workspace", response_model=CompanionWorkspaceSummaryResponse | None)
async def get_companion_workspace(itinerary_id: str, claims: CurrentConsumer, session: Session) -> CompanionWorkspaceSummaryResponse | None:
    try:
        summary = await CommunityService(session).get_itinerary_companion_workspace(itinerary_id, claims.user_id)
        return CompanionWorkspaceSummaryResponse.model_validate(summary) if summary else None
    except CommunityError as error:
        raise _community_error(error) from error


@router.get("/{itinerary_id}/versions", response_model=list[ItineraryVersionResponse])
async def list_versions(itinerary_id: str, claims: CurrentConsumer, service: Service) -> list[ItineraryVersionResponse]:
    versions = await service.list_versions(itinerary_id, claims.user_id)
    if versions is None:
        raise HTTPException(status_code=404, detail={"code": "ITINERARY_NOT_FOUND", "message": "The itinerary is unavailable."})
    return [ItineraryVersionResponse.model_validate(version) for version in versions]


@router.get("/{itinerary_id}/versions/{version_no}", response_model=ItineraryVersionDetailResponse)
async def get_version(itinerary_id: str, version_no: Annotated[int, Path(ge=1)], claims: CurrentConsumer, service: Service) -> ItineraryVersionDetailResponse:
    version = await service.get_version(itinerary_id, version_no, claims.user_id)
    if version is None:
        raise HTTPException(status_code=404, detail={"code": "ITINERARY_VERSION_NOT_FOUND", "message": "The itinerary version is unavailable."})
    return ItineraryVersionDetailResponse.model_validate(version)


@router.post("/{itinerary_id}/field-notes", response_model=FieldNoteResponse, status_code=status.HTTP_201_CREATED)
async def create_field_note(itinerary_id: str, body: FieldNoteCreate, claims: CurrentConsumer, session: Session) -> FieldNoteResponse:
    service = CommunityService(session)
    try:
        post = await service.create_field_note(claims.user_id, itinerary_id, **body.model_dump())
        await session.commit()
        return await service.field_note_response(post)
    except CommunityError as error:
        raise _community_error(error) from error


@router.post("/{itinerary_id}/companion-requests", response_model=CompanionPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_companion_plan(
    itinerary_id: str, body: CompanionPlanCreate, claims: CurrentConsumer, session: Session,
) -> CompanionPlanResponse:
    try:
        plan = await CommunityService(session).create_companion_plan_from_itinerary(claims.user_id, itinerary_id, body)
        await session.commit()
        return CompanionPlanResponse.model_validate(plan)
    except CommunityError as error:
        await session.rollback()
        raise _community_error(error) from error


@router.get("/{itinerary_id}/shared", response_model=PublicItineraryResponse)
async def get_shared_itinerary(itinerary_id: str, share_token: Annotated[str, Query(min_length=20)], service: Service) -> PublicItineraryResponse:
    itinerary = await service.get_shared_itinerary(itinerary_id, share_token)
    if itinerary is None:
        raise HTTPException(status_code=404, detail={"code": "SHARE_LINK_UNAVAILABLE", "message": "This share link is unavailable."})
    return PublicItineraryResponse(
        id=itinerary.id, title=itinerary.title, start_date=itinerary.start_date, end_date=itinerary.end_date,
        version=itinerary.version, status=itinerary.status, snapshot=await service.get_snapshot(itinerary),
    )


@router.post("/{itinerary_id}/share-tokens", response_model=ShareTokenResponse, status_code=status.HTTP_201_CREATED)
async def create_share_token(itinerary_id: str, body: CreateShareTokenRequest, claims: CurrentConsumer, service: Service) -> ShareTokenResponse:
    created = await service.create_share_token(itinerary_id, claims.user_id, expires_at=body.expires_at)
    if created is None:
        raise HTTPException(status_code=404, detail={"code": "ITINERARY_NOT_FOUND", "message": "The itinerary is unavailable."})
    share_token, token = created
    return ShareTokenResponse(id=share_token.id, share_url=f"/shared/itineraries/{itinerary_id}?token={token}", token=token, expires_at=share_token.expires_at)


@router.delete("/{itinerary_id}/share-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share_token(itinerary_id: str, token_id: str, claims: CurrentConsumer, service: Service) -> Response:
    if not await service.revoke_share_token(itinerary_id, token_id, claims.user_id):
        raise HTTPException(status_code=404, detail={"code": "SHARE_TOKEN_NOT_FOUND", "message": "The share link is unavailable."})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{itinerary_id}/collaborators", response_model=CollaboratorResponse, status_code=status.HTTP_201_CREATED)
async def invite_collaborator(itinerary_id: str, body: InviteCollaboratorRequest, claims: CurrentConsumer, service: Service) -> CollaboratorResponse:
    collaborator = await service.invite_collaborator(itinerary_id, claims.user_id, **body.model_dump())
    if collaborator is None:
        raise HTTPException(status_code=404, detail={"code": "COLLABORATOR_UNAVAILABLE", "message": "The collaborator or itinerary is unavailable."})
    return CollaboratorResponse(id=collaborator.id, user_id=collaborator.user_id, role=collaborator.role, invite_status=collaborator.status)


@router.patch("/{itinerary_id}/collaborators/{collaborator_id}", response_model=CollaboratorResponse)
async def update_collaborator(itinerary_id: str, collaborator_id: str, body: UpdateCollaboratorRequest, claims: CurrentConsumer, service: Service) -> CollaboratorResponse:
    collaborator = await service.update_collaborator(itinerary_id, collaborator_id, claims.user_id, **body.model_dump())
    if collaborator is None:
        raise HTTPException(status_code=404, detail={"code": "COLLABORATOR_UNAVAILABLE", "message": "The collaborator or itinerary is unavailable."})
    return CollaboratorResponse(id=collaborator.id, user_id=collaborator.user_id, role=collaborator.role, invite_status=collaborator.status)


@router.post("/{itinerary_id}/collaborators/{collaborator_id}:accept", response_model=CollaboratorResponse)
async def accept_collaborator(itinerary_id: str, collaborator_id: str, claims: CurrentConsumer, service: Service) -> CollaboratorResponse:
    collaborator = await service.accept_collaborator(itinerary_id, collaborator_id, claims.user_id)
    if collaborator is None:
        raise HTTPException(status_code=404, detail={"code": "COLLABORATOR_UNAVAILABLE", "message": "The invitation is unavailable."})
    return CollaboratorResponse(id=collaborator.id, user_id=collaborator.user_id, role=collaborator.role, invite_status=collaborator.status)


@router.post("/{itinerary_id}:operations", response_model=OperationResponse)
async def apply_operation(
    itinerary_id: str,
    body: OperationRequest,
    claims: CurrentConsumer,
    service: Service,
    if_match_version: Annotated[int, Header(alias="If-Match-Version", ge=1)],
    operation_id: Annotated[str, Header(alias="X-Operation-ID", min_length=1, max_length=128)],
) -> OperationResponse:
    result = await service.apply_operation(
        itinerary_id, claims.user_id, base_version=if_match_version, operation_id=operation_id, **body.model_dump()
    )
    return OperationResponse.model_validate(result.__dict__)


@router.get("/{itinerary_id}/route-calculations/{job_id}", response_model=RouteCalculationJobResponse)
async def get_route_calculation(itinerary_id: str, job_id: str, claims: CurrentConsumer, service: Service) -> RouteCalculationJobResponse:
    job = await service.get_route_calculation_job(itinerary_id, job_id, claims.user_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "ROUTE_CALCULATION_NOT_FOUND", "message": "The route calculation is unavailable."})
    return RouteCalculationJobResponse.model_validate(job)


@router.post("/{itinerary_id}:versions", response_model=OperationResponse)
async def create_version(itinerary_id: str, claims: CurrentConsumer, service: Service) -> OperationResponse:
    return OperationResponse.model_validate((await service.create_version(itinerary_id, claims.user_id)).__dict__)


@router.post("/{itinerary_id}:restore", response_model=OperationResponse)
async def restore_version(
    itinerary_id: str,
    body: RestoreVersionRequest,
    claims: CurrentConsumer,
    service: Service,
    if_match_version: Annotated[int, Header(alias="If-Match-Version", ge=1)],
    operation_id: Annotated[str, Header(alias="X-Operation-ID", min_length=1, max_length=128)],
) -> OperationResponse:
    return OperationResponse.model_validate((await service.restore_version(
        itinerary_id, claims.user_id, base_version=if_match_version, version=body.version, operation_id=operation_id
    )).__dict__)
