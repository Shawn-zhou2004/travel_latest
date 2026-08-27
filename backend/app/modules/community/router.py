from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.auth.dependencies import CurrentAdmin, CurrentAuthenticated, CurrentConsumer, OptionalCurrentConsumer
from app.modules.community.models import CompanionRequest, Post
from app.modules.community.schemas import CommentCreate, CommentPage, CommentResponse, CompanionActivityCreate, CompanionApplicationAcceptanceResponse, CompanionApplicationAcceptRequest, CompanionApplicationCreate, CompanionApplicationResponse, CompanionPlanDetailResponse, CompanionPlanPage, CompanionPlanResponse, CompanionPlanSummaryResponse, CompanionRequestResponse, CompanionRequestUpdate, FieldNoteAuthorResponse, FieldNotePage, FieldNoteResponse, FollowResponse, InteractionResponse, ModerationDecision, PostCreate, PostPage, PostResponse, ReactionCreate, ReportCreate, ReportResponse
from app.modules.community.service import CommunityError, CommunityService
from app.modules.itineraries.schemas import FieldNoteCopyResponse, ItineraryResponse


router = APIRouter(prefix="/posts", tags=["community"])
companion_router = APIRouter(prefix="/companion-requests", tags=["community"])
companion_application_router = APIRouter(prefix="/companion-applications", tags=["community"])
users_router = APIRouter(prefix="/users", tags=["community"])
Session = Annotated[AsyncSession, Depends(get_session)]


def _error(error: CommunityError) -> HTTPException:
    status_code = 403 if error.code in {"FORBIDDEN", "USER_BLOCKED"} else 404 if error.code.endswith("NOT_FOUND") else 422 if error.code.startswith("INVALID_COMPANION") or error.code in {"COMPANION_DESTINATION_REQUIRED", "GROUP_NAME_REQUIRED", "GROUP_AVATAR_REQUIRED", "INVALID_GROUP_AVATAR"} else 400 if error.code in {"INVALID_CURSOR", "INVALID_REPORT_TARGET", "UNSUPPORTED_REACTION", "INVALID_SORT"} else 409
    return HTTPException(status_code, detail={"code": error.code, "message": error.message})


@router.get("", response_model=FieldNotePage | PostPage)
async def list_published_posts(
    session: Session,
    content_type: str | None = Query(default=None),
    city_code: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    sort: str = Query(default="latest"),
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
) -> FieldNotePage | PostPage:
    if content_type == "itinerary":
        try:
            posts, next_cursor = await CommunityService(session).list_field_notes(
                city_code=city_code, query=q, sort=sort, limit=limit, cursor=cursor,
            )
        except CommunityError as error:
            raise _error(error) from error
        return FieldNotePage(
            items=[await CommunityService(session).field_note_response(post) for post in posts],
            next_cursor=next_cursor,
        )
    if content_type is not None:
        raise HTTPException(400, detail={"code": "INVALID_CONTENT_TYPE", "message": "The content type is unavailable."})
    statement = select(Post).where(Post.status == "published").order_by(Post.published_at.desc(), Post.id.desc()).limit(limit + 1)
    if city_code:
        statement = statement.where(Post.city_code == city_code)
    if cursor:
        item = await session.get(Post, cursor)
        if item is None or item.status != "published":
            raise HTTPException(400, detail={"code": "INVALID_CURSOR", "message": "The cursor is unavailable."})
        statement = statement.where((Post.published_at < item.published_at) | ((Post.published_at == item.published_at) & (Post.id < item.id)))
    posts = list((await session.scalars(statement)).all())
    return PostPage(items=[PostResponse.model_validate(post) for post in posts[:limit]], next_cursor=posts[limit].id if len(posts) > limit else None)


@router.get("/me/favorites", response_model=PostPage)
async def list_my_favorites(claims: CurrentConsumer, session: Session, cursor: str | None = None, limit: int = Query(default=20, ge=1, le=50)) -> PostPage:
    try:
        posts, next_cursor = await CommunityService(session).list_favorites(claims.user_id, limit=limit, cursor=cursor)
        return PostPage(items=[PostResponse.model_validate(post) for post in posts], next_cursor=next_cursor)
    except CommunityError as error:
        raise _error(error) from error


@router.get("/me/field-notes", response_model=list[FieldNoteAuthorResponse])
async def list_my_field_notes(claims: CurrentConsumer, session: Session) -> list[FieldNoteAuthorResponse]:
    service = CommunityService(session)
    return [await service.field_note_author_response(post) for post in await service.list_owned_field_notes(claims.user_id)]


@router.get("/{post_id}", response_model=FieldNoteResponse | PostResponse)
async def get_published_post(post_id: str, session: Session) -> FieldNoteResponse | PostResponse:
    post = await session.get(Post, post_id)
    if post is None or post.status != "published":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "POST_NOT_FOUND"})
    if post.content_type == "itinerary":
        try:
            return await CommunityService(session).field_note_response(post)
        except CommunityError as error:
            raise _error(error) from error
    return PostResponse.model_validate(post)


@router.post("/{post_id}:copy-itinerary", response_model=FieldNoteCopyResponse, status_code=status.HTTP_201_CREATED)
async def copy_field_note(
    post_id: str,
    claims: CurrentConsumer,
    session: Session,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> FieldNoteCopyResponse:
    try:
        post = await CommunityService(session).get_published_field_note(post_id)
        from app.modules.itineraries.service import ItineraryCopyError, ItineraryService

        result = await ItineraryService(session).copy_field_note(post, claims.user_id, idempotency_key)
        return FieldNoteCopyResponse(
            itinerary=ItineraryResponse.model_validate(result.itinerary),
            source_post_id=post.id,
            idempotent=result.idempotent,
        )
    except CommunityError as error:
        raise _error(error) from error
    except ItineraryCopyError as error:
        raise HTTPException(422, detail={"code": "INVALID_FIELD_NOTE_ITINERARY", "message": str(error)}) from error


@router.get("/{post_id}/private", response_model=PostResponse)
async def get_post_for_author_or_admin(post_id: str, claims: CurrentAuthenticated, session: Session) -> PostResponse:
    try:
        post = await CommunityService(session).get_post_for_reader(post_id, claims.user_id, is_admin="platform_admin" in claims.roles)
        return PostResponse.model_validate(post)
    except CommunityError as error:
        raise _error(error) from error


@router.post("", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
async def create_post(body: PostCreate, claims: CurrentConsumer, session: Session) -> Post:
    post = await CommunityService(session).create_post(claims.user_id, body.title, body.body_text, body.city_code, body.content_type)
    await session.commit()
    return post


@router.post("/{post_id}:submit", response_model=PostResponse)
async def submit_post(post_id: str, claims: CurrentConsumer, session: Session) -> Post:
    try:
        post = await CommunityService(session).submit_for_review(post_id, claims.user_id)
        await session.commit()
        return post
    except CommunityError as error:
        raise _error(error) from error


@router.post("/{post_id}:publish", response_model=PostResponse)
async def publish_post_by_author(post_id: str, claims: CurrentConsumer, session: Session) -> Post:
    try:
        post = await CommunityService(session).publish(post_id, claims.user_id)
        await session.commit()
        return post
    except CommunityError as error:
        raise _error(error) from error


@router.post("/{post_id}/reactions", response_model=InteractionResponse, status_code=status.HTTP_201_CREATED)
async def react_to_post(post_id: str, body: ReactionCreate, claims: CurrentConsumer, session: Session) -> InteractionResponse:
    try:
        reaction = await CommunityService(session).react(post_id, claims.user_id, body.reaction_type)
        await session.commit()
        return InteractionResponse(id=reaction.id, post_id=reaction.post_id, created_at=reaction.created_at)
    except CommunityError as error:
        raise _error(error) from error


@router.delete("/{post_id}/reactions/like", status_code=status.HTTP_204_NO_CONTENT)
async def remove_reaction(post_id: str, claims: CurrentConsumer, session: Session) -> Response:
    try:
        await CommunityService(session).remove_reaction(post_id, claims.user_id)
        await session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except CommunityError as error:
        raise _error(error) from error


@router.post("/{post_id}/favorites", response_model=InteractionResponse, status_code=status.HTTP_201_CREATED)
async def favorite_post(post_id: str, claims: CurrentConsumer, session: Session) -> InteractionResponse:
    try:
        favorite = await CommunityService(session).favorite(post_id, claims.user_id)
        await session.commit()
        return InteractionResponse(id=favorite.id, post_id=favorite.post_id, created_at=favorite.created_at)
    except CommunityError as error:
        raise _error(error) from error


@router.delete("/{post_id}/favorites", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(post_id: str, claims: CurrentConsumer, session: Session) -> Response:
    try:
        await CommunityService(session).remove_favorite(post_id, claims.user_id)
        await session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except CommunityError as error:
        raise _error(error) from error


@users_router.post("/{user_id}/follows", response_model=FollowResponse, status_code=status.HTTP_201_CREATED)
async def follow_user(user_id: str, claims: CurrentConsumer, session: Session) -> FollowResponse:
    try:
        follow = await CommunityService(session).follow(claims.user_id, user_id)
        await session.commit()
        return FollowResponse(user_id=follow.followee_id, created_at=follow.created_at)
    except CommunityError as error:
        raise _error(error) from error


@users_router.delete("/{user_id}/follows", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow_user(user_id: str, claims: CurrentConsumer, session: Session) -> Response:
    await CommunityService(session).unfollow(claims.user_id, user_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{post_id}/comments", response_model=CommentPage)
async def list_comments(post_id: str, session: Session, cursor: str | None = None, limit: int = Query(default=50, ge=1, le=100)) -> CommentPage:
    try:
        comments, next_cursor = await CommunityService(session).list_comments(post_id, limit=limit, cursor=cursor)
        return CommentPage(items=[CommentResponse.model_validate(comment) for comment in comments], next_cursor=next_cursor)
    except CommunityError as error:
        raise _error(error) from error


@router.post("/{post_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def comment_on_post(post_id: str, body: CommentCreate, claims: CurrentConsumer, session: Session) -> CommentResponse:
    try:
        comment = await CommunityService(session).comment(post_id, claims.user_id, body.body_text, body.parent_id)
        await session.commit()
        return CommentResponse.model_validate(comment)
    except CommunityError as error:
        raise _error(error) from error


@router.post("/{post_id}/reports", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
async def report_post(post_id: str, body: ReportCreate, claims: CurrentConsumer, session: Session) -> ReportResponse:
    try:
        report = await CommunityService(session).report(claims.user_id, "post", post_id, body.reason_code, body.detail)
        await session.commit()
        return ReportResponse.model_validate(report)
    except CommunityError as error:
        raise _error(error) from error


# Main API composition should include this router only behind an admin dependency.
moderation_router = APIRouter(prefix="/moderation/posts", tags=["community-moderation"])


@moderation_router.post("/{post_id}:publish", response_model=PostResponse)
async def publish_post(post_id: str, body: ModerationDecision, claims: CurrentAdmin, session: Session) -> Post:
    if "platform_admin" not in claims.roles:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Platform admin role required."})
    try:
        post = await CommunityService(session).publish(post_id, claims.user_id, body.reason, is_admin=True)
        await session.commit()
        return post
    except CommunityError as error:
        raise _error(error) from error


@moderation_router.post("/{post_id}:hide", response_model=PostResponse)
async def hide_post(post_id: str, body: ModerationDecision, claims: CurrentAdmin, session: Session) -> Post:
    if "platform_admin" not in claims.roles:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Platform admin role required."})
    try:
        post = await CommunityService(session).hide(post_id, claims.user_id, body.reason or "")
        await session.commit()
        return post
    except CommunityError as error:
        raise _error(error) from error


@companion_router.post("/{request_id}/applications", status_code=status.HTTP_201_CREATED)
async def apply_to_companion(request_id: str, body: CompanionApplicationCreate, claims: CurrentConsumer, session: Session) -> dict[str, str]:
    try:
        application = await CommunityService(session).apply_to_companion(request_id, claims.user_id, body.message)
        await session.commit()
        return {"id": application.id, "status": application.status}
    except CommunityError as error:
        raise _error(error) from error


@companion_router.get("/mine", response_model=list[CompanionPlanSummaryResponse])
async def list_my_companion_requests(claims: CurrentConsumer, session: Session) -> list[CompanionPlanSummaryResponse]:
    return await CommunityService(session).list_my_companion_plans(claims.user_id)


@companion_router.get("/{request_id}", response_model=CompanionPlanDetailResponse, response_model_exclude_none=True)
async def get_companion_request(request_id: str, session: Session, claims: OptionalCurrentConsumer) -> CompanionPlanDetailResponse:
    try:
        return await CommunityService(session).get_companion_plan_detail(request_id, claims.user_id if claims else None)
    except CommunityError as error:
        raise _error(error) from error


@companion_router.patch("/{request_id}", response_model=CompanionPlanDetailResponse, response_model_exclude_none=True)
async def update_companion_request(request_id: str, body: CompanionRequestUpdate, claims: CurrentConsumer, session: Session) -> CompanionPlanDetailResponse:
    try:
        service = CommunityService(session)
        await service.update_companion_request(request_id, claims.user_id, **body.model_dump(exclude_unset=True))
        await session.commit()
        return await service.get_companion_plan_detail(request_id, claims.user_id)
    except CommunityError as error:
        raise _error(error) from error


@companion_router.post("/{request_id}:close", response_model=CompanionRequestResponse)
async def close_companion_request(request_id: str, claims: CurrentConsumer, session: Session) -> CompanionRequestResponse:
    try:
        request = await CommunityService(session).transition_companion_request(request_id, claims.user_id, "closed")
        await session.commit()
        return CompanionRequestResponse.model_validate(request)
    except CommunityError as error:
        raise _error(error) from error


@companion_router.post("/{request_id}:reopen", response_model=CompanionRequestResponse)
async def reopen_companion_request(request_id: str, claims: CurrentConsumer, session: Session) -> CompanionRequestResponse:
    try:
        request = await CommunityService(session).transition_companion_request(request_id, claims.user_id, "open")
        await session.commit()
        return CompanionRequestResponse.model_validate(request)
    except CommunityError as error:
        raise _error(error) from error


@companion_router.post("/{request_id}:cancel", response_model=CompanionRequestResponse)
async def cancel_companion_request(request_id: str, claims: CurrentConsumer, session: Session) -> CompanionRequestResponse:
    try:
        request = await CommunityService(session).transition_companion_request(request_id, claims.user_id, "cancelled")
        await session.commit()
        return CompanionRequestResponse.model_validate(request)
    except CommunityError as error:
        raise _error(error) from error


@companion_router.get("/{request_id}/applications", response_model=list[CompanionApplicationResponse])
async def list_companion_applications(request_id: str, claims: CurrentConsumer, session: Session) -> list[CompanionApplicationResponse]:
    try:
        return await CommunityService(session).list_request_applications(request_id, claims.user_id)
    except CommunityError as error:
        raise _error(error) from error


@companion_router.get("", response_model=CompanionPlanPage)
async def list_companion_requests(
    session: Session,
    claims: OptionalCurrentConsumer,
    city_code: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    trip_kind: str | None = Query(default=None, pattern="^(trip|activity)$"),
    travel_pace: str | None = Query(default=None, pattern="^(slow|balanced|packed)$"),
    tags: list[str] | None = Query(default=None),
    has_slots: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
) -> CompanionPlanPage:
    try:
        return await CommunityService(session).list_public_companion_plans(
            city_code=city_code, start_date=start_date, end_date=end_date, trip_kind=trip_kind,
            travel_pace=travel_pace, tags=tags, has_slots=has_slots, limit=limit, cursor=cursor,
            viewer_id=claims.user_id if claims else None,
        )
    except CommunityError as error:
        raise _error(error) from error


@companion_router.post(":activity", response_model=CompanionPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_companion_activity(body: CompanionActivityCreate, claims: CurrentConsumer, session: Session) -> CompanionPlanResponse:
    try:
        plan = await CommunityService(session).create_companion_activity(claims.user_id, body)
        await session.commit()
        return CompanionPlanResponse.model_validate(plan)
    except CommunityError as error:
        await session.rollback()
        raise _error(error) from error


async def _decide_application(application_id: str, claims: CurrentConsumer, session: Session, accept: bool) -> dict[str, str | None]:
    try:
        application, conversation_id = await CommunityService(session).decide_application(application_id, claims.user_id, accept)
        await session.commit()
        return {"id": application.id, "status": application.status, "conversation_id": conversation_id}
    except CommunityError as error:
        raise _error(error) from error


@companion_application_router.post("/{application_id}:accept", response_model=CompanionApplicationAcceptanceResponse)
async def accept_companion_application(application_id: str, claims: CurrentConsumer, session: Session, body: CompanionApplicationAcceptRequest | None = None) -> CompanionApplicationAcceptanceResponse:
    try:
        application, conversation = await CommunityService(session).accept_companion_application(
            application_id,
            claims.user_id,
            group_name=body.group_name if body else None,
            group_avatar_asset_id=body.group_avatar_asset_id if body else None,
        )
        plan = await session.get(CompanionRequest, application.request_id)
        assert plan is not None
        await session.commit()
        return CompanionApplicationAcceptanceResponse(
            application=CompanionApplicationResponse.model_validate(application), conversation_id=conversation.id,
            group_name=conversation.title, group_avatar_asset_id=conversation.avatar_asset_id,
            plan_status=plan.status, accepted_count=plan.accepted_count,
        )
    except CommunityError as error:
        await session.rollback()
        raise _error(error) from error


@companion_application_router.post("/{application_id}:reject")
async def reject_companion_application(application_id: str, claims: CurrentConsumer, session: Session) -> dict[str, str | None]:
    return await _decide_application(application_id, claims, session, False)


@companion_application_router.get("/mine", response_model=list[CompanionApplicationResponse])
async def list_my_companion_applications(claims: CurrentConsumer, session: Session) -> list[CompanionApplicationResponse]:
    return [CompanionApplicationResponse.model_validate(item) for item in await CommunityService(session).list_my_applications(claims.user_id)]


@companion_application_router.post("/{application_id}:withdraw", response_model=CompanionApplicationResponse)
async def withdraw_companion_application(application_id: str, claims: CurrentConsumer, session: Session) -> CompanionApplicationResponse:
    try:
        application = await CommunityService(session).withdraw_application(application_id, claims.user_id)
        await session.commit()
        return CompanionApplicationResponse.model_validate(application)
    except CommunityError as error:
        raise _error(error) from error


@companion_router.delete("/{request_id}/members/{user_id}", response_model=CompanionRequestResponse)
async def remove_companion_member(request_id: str, user_id: str, claims: CurrentConsumer, session: Session) -> CompanionRequestResponse:
    try:
        plan = await CommunityService(session).remove_companion_member(request_id, claims.user_id, user_id)
        await session.commit()
        return CompanionRequestResponse.model_validate(plan)
    except CommunityError as error:
        await session.rollback()
        raise _error(error) from error


@companion_router.post("/{request_id}:leave", response_model=CompanionRequestResponse)
async def leave_companion_plan(request_id: str, claims: CurrentConsumer, session: Session) -> CompanionRequestResponse:
    try:
        plan = await CommunityService(session).leave_companion_plan(request_id, claims.user_id)
        await session.commit()
        return CompanionRequestResponse.model_validate(plan)
    except CommunityError as error:
        await session.rollback()
        raise _error(error) from error


@companion_router.post("/{request_id}:complete", response_model=CompanionRequestResponse)
async def complete_companion_plan(request_id: str, claims: CurrentConsumer, session: Session) -> CompanionRequestResponse:
    try:
        plan = await CommunityService(session).complete_companion_plan(request_id, claims.user_id)
        await session.commit()
        return CompanionRequestResponse.model_validate(plan)
    except CommunityError as error:
        await session.rollback()
        raise _error(error) from error
