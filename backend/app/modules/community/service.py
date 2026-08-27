from __future__ import annotations

from datetime import date, datetime
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from hmac import compare_digest, new as hmac_new
import json
from typing import Any

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import new_uuid, utc_now
from app.core.settings import Settings
from app.models.outbox import OutboxEvent
from app.modules.chat.models import Conversation, ConversationMember, UserBlock
from app.models.user import User, UserSettings
from app.modules.community.models import Comment, CompanionApplication, CompanionRequest, ContentReport, Follow, Post, PostFavorite, PostMedia, PostReaction
from app.modules.community.schemas import CompanionActivityCreate, CompanionApplicationResponse, CompanionPlanCreate, CompanionPlanDetailResponse, CompanionPlanMemberResponse, CompanionPlanPage, CompanionPlanSummaryResponse, FieldNoteAuthorResponse, FieldNoteResponse
from app.modules.itineraries.models import Itinerary, ItineraryVersion, TripCollaborator
from app.modules.media.models import MediaAsset


class CommunityError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)


class CommunityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_post(
        self,
        author_id: str,
        title: str,
        body_text: str,
        city_code: str | None = None,
        content_type: str = "note",
    ) -> Post:
        if content_type != "note":
            raise CommunityError("INVALID_CONTENT_TYPE", "Field notes must be created from a frozen itinerary version.")
        post = Post(
            author_id=author_id,
            content_type=content_type,
            title=title,
            body_text=body_text,
            city_code=city_code,
        )
        self.session.add(post)
        await self.session.flush()
        return post

    async def create_field_note(
        self,
        author_id: str,
        itinerary_id: str,
        *,
        version_no: int,
        title: str,
        recap_text: str,
        cover_media_id: str,
        media_ids: list[str],
    ) -> Post:
        itinerary = await self.session.get(Itinerary, itinerary_id)
        if itinerary is None:
            raise CommunityError("ITINERARY_NOT_FOUND", "The itinerary does not exist.")
        if not await self._can_publish_field_note(itinerary, author_id):
            raise CommunityError("FORBIDDEN", "Only the itinerary owner or an accepted editor can publish a field note.")
        if cover_media_id not in media_ids or len(set(media_ids)) != len(media_ids):
            raise CommunityError("INVALID_FIELD_NOTE_MEDIA", "The cover must be included and images must not be duplicated.")
        version = await self.session.scalar(select(ItineraryVersion).where(
            ItineraryVersion.itinerary_id == itinerary.id,
            ItineraryVersion.version == version_no,
        ))
        if version is None:
            raise CommunityError("INVALID_FIELD_NOTE_VERSION", "The selected itinerary version is unavailable.")
        snapshot = _public_itinerary_snapshot(version.snapshot)
        if not any(day["events"] for day in snapshot["days"]):
            raise CommunityError("INVALID_FIELD_NOTE_ITINERARY", "The selected itinerary version must contain at least one stop.")
        await self._validate_field_note_media(author_id, media_ids)
        post = Post(
            author_id=author_id,
            content_type="itinerary",
            title=title,
            body_text="",
            city_code=_field_note_city_code(version.snapshot),
            status="pending_review",
            itinerary_id=itinerary.id,
            itinerary_version_id=version.id,
            itinerary_snapshot_json=snapshot,
            recap_text=recap_text,
            cover_media_id=cover_media_id,
        )
        self.session.add(post)
        await self.session.flush()
        self.session.add_all(PostMedia(post_id=post.id, media_id=media_id, sort_order=sort_order) for sort_order, media_id in enumerate(media_ids))
        await self.session.flush()
        return post

    async def field_note_response(self, post: Post) -> FieldNoteResponse:
        snapshot = post.itinerary_snapshot_json
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("days"), list):
            raise CommunityError("INVALID_FIELD_NOTE_ITINERARY", "The field-note snapshot is unavailable.")
        media_ids = list((await self.session.scalars(
            select(PostMedia.media_id).where(PostMedia.post_id == post.id).order_by(PostMedia.sort_order, PostMedia.id)
        )).all())
        days = snapshot["days"]
        return FieldNoteResponse(
            id=post.id, author_id=post.author_id, title=post.title, body_text=post.body_text,
            city_code=post.city_code, status=post.status, published_at=post.published_at,
            recap_text=post.recap_text or "", itinerary_snapshot=snapshot,
            cover_media_id=post.cover_media_id, media_ids=media_ids, day_count=len(days),
            stop_count=sum(len(day.get("events", [])) for day in days if isinstance(day, dict)), copy_count=post.copy_count,
        )

    async def field_note_author_response(self, post: Post) -> FieldNoteAuthorResponse:
        response = await self.field_note_response(post)
        return FieldNoteAuthorResponse(**response.model_dump(), moderation_reason=post.moderation_reason)

    async def list_owned_field_notes(self, author_id: str) -> list[Post]:
        return list((await self.session.scalars(
            select(Post).where(
                Post.author_id == author_id,
                Post.content_type == "itinerary",
            ).order_by(Post.created_at.desc(), Post.id.desc())
        )).all())

    async def list_field_notes(
        self,
        *,
        city_code: str | None,
        query: str | None,
        sort: str,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Post], str | None]:
        if sort not in {"latest", "recommended"}:
            raise CommunityError("INVALID_SORT", "The field-note sort is unavailable.")
        statement = select(Post).where(Post.status == "published", Post.content_type == "itinerary")
        if city_code:
            statement = statement.where(Post.city_code == city_code)
        if query and query.strip():
            term = f"%{query.strip()}%"
            statement = statement.where(or_(Post.title.ilike(term), Post.recap_text.ilike(term)))

        cursor_data = _decode_field_note_cursor(cursor) if cursor else None
        if cursor_data:
            if cursor_data["sort"] != sort:
                raise CommunityError("INVALID_CURSOR", "The cursor is unavailable.")
            if sort == "latest":
                published_at, post_id = cursor_data["published_at"], cursor_data["id"]
                statement = statement.where(
                    (Post.published_at < published_at)
                    | ((Post.published_at == published_at) & (Post.id < post_id))
                )
                statement = statement.order_by(Post.published_at.desc(), Post.id.desc())
            else:
                copy_count, published_at, post_id = cursor_data["copy_count"], cursor_data["published_at"], cursor_data["id"]
                statement = statement.where(
                    (Post.copy_count < copy_count)
                    | ((Post.copy_count == copy_count) & (Post.published_at < published_at))
                    | ((Post.copy_count == copy_count) & (Post.published_at == published_at) & (Post.id < post_id))
                )
                statement = statement.order_by(Post.copy_count.desc(), Post.published_at.desc(), Post.id.desc())
        elif sort == "latest":
            statement = statement.order_by(Post.published_at.desc(), Post.id.desc())
        else:
            statement = statement.order_by(Post.copy_count.desc(), Post.published_at.desc(), Post.id.desc())

        posts = list((await self.session.scalars(statement.limit(limit + 1))).all())
        next_cursor = None
        if len(posts) > limit:
            last = posts.pop()
            next_cursor = _encode_field_note_cursor(last, sort)
        return posts, next_cursor

    async def get_published_field_note(self, post_id: str) -> Post:
        post = await self.session.get(Post, post_id)
        if post is None or post.status != "published" or post.content_type != "itinerary":
            raise CommunityError("POST_NOT_FOUND", "The published field note does not exist.")
        return post

    async def submit_for_review(self, post_id: str, actor_id: str) -> Post:
        post = await self._owned_post(post_id, actor_id)
        if post.status != "draft":
            raise CommunityError("INVALID_POST_TRANSITION", "Only drafts can be submitted for review.")
        post.status = "pending_review"
        return post

    async def publish(
        self,
        post_id: str,
        reviewer_id: str,
        reason: str | None = None,
        *,
        is_admin: bool = False,
    ) -> Post:
        post = await self.session.get(Post, post_id)
        if post is None:
            raise CommunityError("POST_NOT_FOUND", "The post does not exist.")
        if not is_admin and post.author_id != reviewer_id:
            raise CommunityError("FORBIDDEN", "Only the post author can publish this post.")
        if post.status != "pending_review":
            raise CommunityError("INVALID_POST_TRANSITION", "Only pending posts can be published.")
        post.status, post.published_at, post.moderation_reason = "published", utc_now(), reason
        if post.city_code:
            from app.modules.admin.models import CommunityKnowledgeReview

            self.session.add(CommunityKnowledgeReview(post_id=post.id, status="pending"))
        self._event("post.published", "post", post.id, {"post_id": post.id, "author_id": post.author_id, "content_type": post.content_type, "city_code": post.city_code})
        return post

    async def hide(self, post_id: str, reviewer_id: str, reason: str) -> Post:
        if not reason.strip():
            raise CommunityError("MODERATION_REASON_REQUIRED", "A moderation reason is required.")
        post = await self.session.get(Post, post_id)
        if post is None or post.status != "published":
            raise CommunityError("INVALID_POST_TRANSITION", "Only published posts can be hidden.")
        post.status, post.moderation_reason = "hidden", reason
        self._event("post.hidden", "post", post.id, {"post_id": post.id, "reason_code": reason})
        return post

    async def reject(self, post_id: str, reviewer_id: str, reason: str) -> Post:
        if not reason.strip():
            raise CommunityError("MODERATION_REASON_REQUIRED", "A moderation reason is required.")
        post = await self.session.get(Post, post_id)
        if post is None or post.status != "pending_review":
            raise CommunityError("INVALID_POST_TRANSITION", "Only pending posts can be rejected.")
        post.status, post.moderation_reason = "rejected", reason
        return post

    async def react(self, post_id: str, user_id: str, reaction_type: str = "like") -> PostReaction:
        if reaction_type != "like":
            raise CommunityError("UNSUPPORTED_REACTION", "Only like reactions are supported.")
        post = await self._published_post(post_id)
        existing = await self.session.scalar(select(PostReaction).where(PostReaction.post_id == post.id, PostReaction.user_id == user_id))
        if existing:
            return existing
        reaction = PostReaction(post_id=post.id, user_id=user_id, reaction_type=reaction_type)
        self.session.add(reaction)
        await self.session.flush()
        return reaction

    async def remove_reaction(self, post_id: str, user_id: str) -> None:
        await self._published_post(post_id)
        await self.session.execute(delete(PostReaction).where(PostReaction.post_id == post_id, PostReaction.user_id == user_id))

    async def favorite(self, post_id: str, user_id: str) -> PostFavorite:
        post = await self._published_post(post_id)
        existing = await self.session.scalar(select(PostFavorite).where(PostFavorite.post_id == post.id, PostFavorite.user_id == user_id))
        if existing:
            return existing
        favorite = PostFavorite(post_id=post.id, user_id=user_id)
        self.session.add(favorite)
        await self.session.flush()
        return favorite

    async def remove_favorite(self, post_id: str, user_id: str) -> None:
        await self._published_post(post_id)
        await self.session.execute(delete(PostFavorite).where(PostFavorite.post_id == post_id, PostFavorite.user_id == user_id))

    async def follow(self, follower_id: str, followee_id: str) -> Follow:
        if follower_id == followee_id:
            raise CommunityError("SELF_FOLLOW", "You cannot follow yourself.")
        if await self.session.get(User, followee_id) is None:
            raise CommunityError("USER_NOT_FOUND", "The user does not exist.")
        existing = await self.session.scalar(
            select(Follow).where(Follow.follower_id == follower_id, Follow.followee_id == followee_id)
        )
        if existing:
            return existing
        follow = Follow(follower_id=follower_id, followee_id=followee_id)
        self.session.add(follow)
        await self.session.flush()
        return follow

    async def unfollow(self, follower_id: str, followee_id: str) -> None:
        await self.session.execute(
            delete(Follow).where(Follow.follower_id == follower_id, Follow.followee_id == followee_id)
        )

    async def list_favorites(self, user_id: str, *, limit: int, cursor: str | None) -> tuple[list[Post], str | None]:
        statement = (
            select(Post)
            .join(PostFavorite, PostFavorite.post_id == Post.id)
            .where(PostFavorite.user_id == user_id, Post.status == "published")
            .order_by(PostFavorite.created_at.desc(), PostFavorite.id.desc())
            .limit(limit + 1)
        )
        if cursor:
            favorite = await self.session.get(PostFavorite, cursor)
            if favorite is None or favorite.user_id != user_id:
                raise CommunityError("INVALID_CURSOR", "The cursor is unavailable.")
            statement = statement.where(
                (PostFavorite.created_at < favorite.created_at)
                | ((PostFavorite.created_at == favorite.created_at) & (PostFavorite.id < favorite.id))
            )
        posts = list((await self.session.scalars(statement)).all())
        next_cursor = None
        if len(posts) > limit:
            posts.pop()
            last_favorite = await self.session.scalar(select(PostFavorite).where(PostFavorite.post_id == posts[-1].id, PostFavorite.user_id == user_id))
            next_cursor = last_favorite.id if last_favorite else None
        return posts, next_cursor

    async def get_post_for_reader(self, post_id: str, reader_id: str, *, is_admin: bool) -> Post:
        post = await self.session.get(Post, post_id)
        if post is None:
            raise CommunityError("POST_NOT_FOUND", "The post does not exist.")
        if post.status == "published" or post.author_id == reader_id or is_admin:
            return post
        raise CommunityError("POST_NOT_FOUND", "The post is unavailable.")

    async def list_comments(self, post_id: str, *, limit: int, cursor: str | None) -> tuple[list[Comment], str | None]:
        await self._published_post(post_id)
        statement = select(Comment).where(Comment.post_id == post_id, Comment.status == "visible").order_by(Comment.created_at.asc(), Comment.id.asc()).limit(limit + 1)
        if cursor:
            comment = await self.session.get(Comment, cursor)
            if comment is None or comment.post_id != post_id:
                raise CommunityError("INVALID_CURSOR", "The cursor is unavailable.")
            statement = statement.where(
                (Comment.created_at > comment.created_at)
                | ((Comment.created_at == comment.created_at) & (Comment.id > comment.id))
            )
        comments = list((await self.session.scalars(statement)).all())
        next_cursor = comments[limit].id if len(comments) > limit else None
        return comments[:limit], next_cursor

    async def comment(self, post_id: str, author_id: str, body_text: str, parent_id: str | None = None) -> Comment:
        post = await self._published_post(post_id)
        if parent_id:
            parent = await self.session.get(Comment, parent_id)
            if parent is None or parent.post_id != post.id or parent.status != "visible":
                raise CommunityError("COMMENT_NOT_FOUND", "The parent comment is unavailable.")
        comment = Comment(post_id=post.id, author_id=author_id, body_text=body_text, parent_id=parent_id)
        self.session.add(comment)
        await self.session.flush()
        return comment

    async def report(self, reporter_id: str, target_type: str, target_id: str, reason_code: str, detail: str | None = None) -> ContentReport:
        if target_type not in {"post", "comment"}:
            raise CommunityError("INVALID_REPORT_TARGET", "Reports can target posts or comments.")
        target = await self.session.get(Post if target_type == "post" else Comment, target_id)
        if target is None:
            raise CommunityError("REPORT_TARGET_NOT_FOUND", "The report target does not exist.")
        report = ContentReport(reporter_id=reporter_id, target_type=target_type, target_id=target_id, reason_code=reason_code, detail=detail)
        self.session.add(report)
        await self.session.flush()
        return report

    async def apply_to_companion(self, request_id: str, applicant_id: str, message: str) -> CompanionApplication:
        if not message.strip():
            raise CommunityError("INVALID_COMPANION_APPLICATION", "An application message is required.")
        async with self.session.begin_nested():
            request = await self.session.scalar(select(CompanionRequest).where(CompanionRequest.id == request_id).with_for_update())
            if request is None:
                raise CommunityError("COMPANION_REQUEST_NOT_FOUND", "The companion plan does not exist.")
            if request.owner_id == applicant_id:
                raise CommunityError("SELF_APPLICATION", "You cannot apply to your own companion request.")
            existing = await self.session.scalar(select(CompanionApplication).where(
                CompanionApplication.request_id == request_id,
                CompanionApplication.applicant_id == applicant_id,
            ))
            if existing is not None and existing.status in {"pending", "accepted"}:
                return existing
            self._require_application_allowed(request)
            await self._require_no_block(applicant_id, request.owner_id)
            if existing is None:
                application = CompanionApplication(request_id=request_id, applicant_id=applicant_id, message=message.strip())
                self.session.add(application)
            else:
                application = existing
                application.status = "pending"
                application.message = message.strip()
                application.conversation_id = None
            await self.session.flush()
            self._event("companion_application.created", "companion_application", application.id, {"application_id": application.id, "request_id": request.id, "owner_id": request.owner_id, "applicant_id": applicant_id})
            return application

    async def create_companion_request(
        self,
        owner_id: str,
        title: str,
        city_code: str | None,
        description: str,
    ) -> CompanionRequest:
        request = CompanionRequest(
            owner_id=owner_id,
            title=title,
            city_code=city_code,
            description=description,
        )
        self.session.add(request)
        await self.session.flush()
        return request

    async def create_companion_plan_from_itinerary(
        self, actor_id: str, itinerary_id: str, body: CompanionPlanCreate
    ) -> CompanionRequest:
        self._validate_companion_metadata(body)
        itinerary = await self.session.get(Itinerary, itinerary_id)
        if itinerary is None:
            raise CommunityError("ITINERARY_NOT_FOUND", "The itinerary does not exist.")
        if not await self._can_publish_field_note(itinerary, actor_id):
            raise CommunityError("FORBIDDEN", "Only the itinerary owner or an accepted editor can publish a companion plan.")
        snapshot = await self._current_itinerary_snapshot(itinerary)
        city_code = _companion_city_code(snapshot) or body.city_code
        if city_code is None:
            raise CommunityError("COMPANION_DESTINATION_REQUIRED", "请选择目的地城市后再发布同行计划。")
        return await self._create_companion_plan(
            owner_id=actor_id, itinerary=itinerary, city_code=city_code, title=snapshot["title"], body=body, trip_kind="trip",
        )

    async def create_companion_activity(self, actor_id: str, body: CompanionActivityCreate) -> CompanionRequest:
        self._validate_companion_metadata(body)
        from app.modules.itineraries.service import ItineraryService

        try:
            async with self.session.begin_nested():
                itinerary = await ItineraryService(self.session).create_companion_activity_itinerary(
                    actor_id, title=body.title, activity_date=body.activity_date, starts_at=body.starts_at,
                    ends_at=body.ends_at, poi_id=body.poi_id, city_code=body.city_code,
                )
                plan = await self._create_companion_plan(
                    owner_id=actor_id, itinerary=itinerary, city_code=body.city_code, title=body.title,
                    body=body, trip_kind="activity",
                )
        except ValueError as error:
            raise CommunityError("INVALID_COMPANION_ACTIVITY", str(error)) from error
        return plan

    async def _create_companion_plan(
        self, *, owner_id: str, itinerary: Itinerary, city_code: str, title: str,
        body: CompanionPlanCreate, trip_kind: str,
    ) -> CompanionRequest:
        plan = CompanionRequest(
            owner_id=owner_id, itinerary_id=itinerary.id, title=title, city_code=city_code,
            description=body.intro_text, trip_kind=trip_kind, start_date=itinerary.start_date,
            end_date=itinerary.end_date, party_size=body.party_size, accepted_count=1,
            budget_min=body.budget_min, budget_max=body.budget_max, currency=body.currency,
            travel_pace=body.travel_pace, interest_tags=list(body.interest_tags), intro_text=body.intro_text,
            status="open", review_status="pending_review",
        )
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def _current_itinerary_snapshot(self, itinerary: Itinerary) -> dict[str, Any]:
        version = await self.session.scalar(select(ItineraryVersion).where(
            ItineraryVersion.itinerary_id == itinerary.id, ItineraryVersion.version == itinerary.version,
        ))
        if version is None:
            raise CommunityError("INVALID_COMPANION_ITINERARY", "The current itinerary version is unavailable.")
        snapshot = version.snapshot
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("title"), str) or not isinstance(snapshot.get("days"), list):
            raise CommunityError("INVALID_COMPANION_ITINERARY", "The current itinerary version is invalid.")
        if not any(isinstance(day, dict) and isinstance(day.get("events"), list) and day["events"] for day in snapshot["days"]):
            raise CommunityError("INVALID_COMPANION_ITINERARY", "The itinerary must contain at least one stop.")
        return snapshot

    @staticmethod
    def _validate_companion_metadata(body: CompanionPlanCreate) -> None:
        if body.party_size < 2 or body.party_size > 12:
            raise CommunityError("INVALID_COMPANION_CAPACITY", "Party size must be between 2 and 12.")
        if (body.budget_min is None) != (body.budget_max is None) or (body.budget_min is None) != (body.currency is None):
            raise CommunityError("INVALID_COMPANION_BUDGET", "Budget range and currency must be provided together.")
        if body.budget_min is not None and body.budget_min > body.budget_max:
            raise CommunityError("INVALID_COMPANION_BUDGET", "The budget range is invalid.")

    async def list_owned_companion_requests(self, owner_id: str) -> list[CompanionRequest]:
        return list((await self.session.scalars(select(CompanionRequest).where(CompanionRequest.owner_id == owner_id).order_by(CompanionRequest.created_at.desc()))).all())

    async def list_public_companion_plans(self, *, city_code: str | None, start_date: date | None, end_date: date | None, trip_kind: str | None, travel_pace: str | None, tags: list[str] | None, has_slots: bool, limit: int, cursor: str | None, viewer_id: str | None = None) -> CompanionPlanPage:
        statement = select(CompanionRequest).where(CompanionRequest.review_status == "approved", CompanionRequest.status == "open")
        if city_code:
            statement = statement.where(CompanionRequest.city_code == city_code)
        if start_date:
            statement = statement.where(CompanionRequest.end_date >= start_date)
        if end_date:
            statement = statement.where(CompanionRequest.start_date <= end_date)
        if trip_kind:
            statement = statement.where(CompanionRequest.trip_kind == trip_kind)
        if travel_pace:
            statement = statement.where(CompanionRequest.travel_pace == travel_pace)
        if tags:
            for tag in tags:
                statement = statement.where(CompanionRequest.interest_tags.contains(tag))
        if has_slots:
            statement = statement.where(CompanionRequest.accepted_count < CompanionRequest.party_size)
        cursor_data = _decode_companion_cursor(cursor) if cursor else None
        if cursor_data:
            statement = statement.where(
                (CompanionRequest.start_date > cursor_data["start_date"])
                | ((CompanionRequest.start_date == cursor_data["start_date"]) & (CompanionRequest.created_at < cursor_data["created_at"]))
                | ((CompanionRequest.start_date == cursor_data["start_date"]) & (CompanionRequest.created_at == cursor_data["created_at"]) & (CompanionRequest.id < cursor_data["id"]))
            )
        statement = statement.order_by(CompanionRequest.start_date.asc(), CompanionRequest.created_at.desc(), CompanionRequest.id.desc())
        plans = list((await self.session.scalars(statement.limit(limit + 1))).all())
        next_cursor = None
        if len(plans) > limit:
            plans.pop()
            next_cursor = _encode_companion_cursor(plans[-1])
        return CompanionPlanPage(items=[await self._companion_summary(plan, viewer_id) for plan in plans], next_cursor=next_cursor)

    async def get_companion_plan_detail(self, request_id: str, viewer_id: str | None) -> CompanionPlanDetailResponse:
        plan = await self.session.get(CompanionRequest, request_id)
        if plan is None:
            raise CommunityError("COMPANION_REQUEST_NOT_FOUND", "The companion plan does not exist.")
        application_status = await self._viewer_application_status(plan.id, viewer_id)
        is_member = viewer_id == plan.owner_id or application_status == "accepted"
        if not is_member and (plan.review_status != "approved" or plan.status != "open"):
            raise CommunityError("COMPANION_REQUEST_NOT_FOUND", "The companion plan is unavailable.")
        summary = await self._companion_summary(plan, viewer_id, application_status=application_status)
        detail = CompanionPlanDetailResponse(**summary.model_dump())
        if viewer_id == plan.owner_id:
            detail.review_status = plan.review_status
        if not is_member:
            return detail
        detail.itinerary_id, detail.conversation_id = plan.itinerary_id, plan.conversation_id
        if plan.itinerary_id:
            itinerary = await self.session.get(Itinerary, plan.itinerary_id)
            if itinerary is not None:
                detail.protected_itinerary = await self._current_itinerary_snapshot(itinerary)
        detail.members = await self._companion_members(plan, viewer_id)
        return detail

    async def list_my_companion_plans(self, viewer_id: str) -> list[CompanionPlanSummaryResponse]:
        statement = select(CompanionRequest).outerjoin(CompanionApplication, CompanionApplication.request_id == CompanionRequest.id).where(or_(
            CompanionRequest.owner_id == viewer_id,
            and_(CompanionApplication.applicant_id == viewer_id, CompanionApplication.status.in_(("accepted", "pending"))),
        )).order_by(CompanionRequest.created_at.desc(), CompanionRequest.id.desc())
        plans = list((await self.session.scalars(statement)).unique().all())
        return [await self._companion_summary(plan, viewer_id) for plan in plans]

    async def get_itinerary_companion_workspace(self, itinerary_id: str, viewer_id: str) -> dict[str, Any] | None:
        """Return only workspace facts visible to a current itinerary collaborator."""
        itinerary = await self.session.get(Itinerary, itinerary_id)
        if itinerary is None or not await self._can_publish_field_note(itinerary, viewer_id):
            raise CommunityError("ITINERARY_NOT_FOUND", "The itinerary is unavailable.")
        plan = await self.session.scalar(
            select(CompanionRequest)
            .where(
                CompanionRequest.itinerary_id == itinerary_id,
                CompanionRequest.status.in_(("open", "full", "closed")),
            )
            .order_by(CompanionRequest.created_at.desc(), CompanionRequest.id.desc())
        )
        if plan is None:
            return None
        application_status = await self._viewer_application_status(plan.id, viewer_id)
        role = "owner" if plan.owner_id == viewer_id else "member" if application_status == "accepted" else "collaborator"
        return {
            "id": plan.id,
            "status": plan.status,
            "review_status": plan.review_status if role == "owner" else None,
            "party_size": plan.party_size,
            "accepted_count": plan.accepted_count,
            "role": role,
            "conversation_id": plan.conversation_id if role in ("owner", "member") else None,
        }

    async def _companion_summary(self, plan: CompanionRequest, viewer_id: str | None, *, application_status: str | None = None) -> CompanionPlanSummaryResponse:
        route_count, cover_candidate = _companion_route_summary(await self._companion_snapshot(plan))
        if application_status is None:
            application_status = await self._viewer_application_status(plan.id, viewer_id)
        viewer_role = (
            "owner" if viewer_id == plan.owner_id else
            "member" if application_status == "accepted" else
            "applicant" if viewer_id is not None else
            "public"
        )
        return CompanionPlanSummaryResponse(
            id=plan.id, title=plan.title, city_code=plan.city_code, trip_kind=plan.trip_kind, start_date=plan.start_date,
            end_date=plan.end_date, party_size=plan.party_size, accepted_count=plan.accepted_count,
            budget_min=plan.budget_min, budget_max=plan.budget_max, currency=plan.currency, travel_pace=plan.travel_pace,
            interest_tags=plan.interest_tags or [], intro_text=plan.intro_text, route_count=route_count,
            cover_candidate=cover_candidate, status=plan.status, application_status=application_status,
            viewer_role=viewer_role,
        )

    async def _companion_snapshot(self, plan: CompanionRequest) -> dict[str, Any] | None:
        if not plan.itinerary_id:
            return None
        itinerary = await self.session.get(Itinerary, plan.itinerary_id)
        if itinerary is None:
            return None
        version = await self.session.scalar(select(ItineraryVersion).where(ItineraryVersion.itinerary_id == itinerary.id, ItineraryVersion.version == itinerary.version))
        return version.snapshot if version is not None and isinstance(version.snapshot, dict) else None

    async def _viewer_application_status(self, request_id: str, viewer_id: str | None) -> str | None:
        if viewer_id is None:
            return None
        return await self.session.scalar(select(CompanionApplication.status).where(CompanionApplication.request_id == request_id, CompanionApplication.applicant_id == viewer_id))

    async def _companion_members(self, plan: CompanionRequest, viewer_id: str) -> list[CompanionPlanMemberResponse]:
        member_ids = [plan.owner_id] + list((await self.session.scalars(select(CompanionApplication.applicant_id).where(CompanionApplication.request_id == plan.id, CompanionApplication.status == "accepted"))).all())
        users = {user.id: user for user in (await self.session.scalars(select(User).where(User.id.in_(member_ids)))).all()}
        settings_by_user_id = {
            settings.user_id: settings
            for settings in (await self.session.scalars(select(UserSettings).where(UserSettings.user_id.in_(member_ids)))).all()
        }
        members: list[CompanionPlanMemberResponse] = []
        for user_id in member_ids:
            user = users.get(user_id)
            if user is None:
                continue
            settings = settings_by_user_id.get(user_id)
            visible = user_id == viewer_id or (settings is not None and settings.profile_visibility == "collaborators")
            members.append(CompanionPlanMemberResponse(
                display_name=(user.nickname or "Traveler") if visible else None,
                avatar_asset_id=user.avatar_asset_id if visible else None,
                role="owner" if user_id == plan.owner_id else "member",
            ))
        return members

    async def update_companion_request(self, request_id: str, owner_id: str, **values: Any) -> CompanionRequest:
        request = await self._locked_plan_for_owner(request_id, owner_id)
        if request.status in {"cancelled", "completed"}:
            raise CommunityError("INVALID_COMPANION_REQUEST_TRANSITION", "Completed or cancelled companion plans cannot be edited.")

        budget_fields = {"budget_min", "budget_max", "currency"}
        if budget_fields.intersection(values) and not budget_fields.issubset(values):
            raise CommunityError("INVALID_COMPANION_BUDGET", "Budget range and currency must be updated together.")
        party_size = values.get("party_size", request.party_size)
        budget_min = values.get("budget_min", request.budget_min)
        budget_max = values.get("budget_max", request.budget_max)
        currency = values.get("currency", request.currency)
        if party_size is None or party_size < request.accepted_count:
            raise CommunityError("INVALID_COMPANION_CAPACITY", "Party size cannot be smaller than the accepted member count.")
        if (budget_min is None) != (budget_max is None) or (budget_min is None) != (currency is None):
            raise CommunityError("INVALID_COMPANION_BUDGET", "Budget range and currency must be provided together.")
        if budget_min is not None and budget_min > budget_max:
            raise CommunityError("INVALID_COMPANION_BUDGET", "The budget range is invalid.")
        for field, value in values.items():
            setattr(request, field, value)
        if party_size == request.accepted_count:
            request.status = "full"
        elif request.status == "full" and request.review_status == "approved":
            request.status = "open"
        return request

    async def transition_companion_request(self, request_id: str, owner_id: str, target: str) -> CompanionRequest:
        request = await self._locked_plan_for_owner(request_id, owner_id)
        if request.review_status != "approved":
            raise CommunityError("INVALID_COMPANION_REQUEST_TRANSITION", "The companion request cannot transition before approval.")
        if target == "closed" and request.status == "open":
            request.status = target
        elif target == "cancelled" and request.status == "open":
            request.status = target
        elif target == "open" and request.status == "closed" and request.review_status == "approved" and request.accepted_count < (request.party_size or 0):
            request.status = target
        else:
            raise CommunityError("INVALID_COMPANION_REQUEST_TRANSITION", "The companion request cannot make that transition.")
        applicant_ids = list((await self.session.scalars(select(CompanionApplication.applicant_id).where(CompanionApplication.request_id == request.id, CompanionApplication.status == "pending"))).all())
        self._event("companion_request.closed", "companion_request", request.id, {"request_id": request.id, "owner_id": owner_id, "status": target, "applicant_ids": applicant_ids})
        return request

    async def list_request_applications(self, request_id: str, owner_id: str) -> list[CompanionApplicationResponse]:
        await self._owned_companion_request(request_id, owner_id)
        applications = list((await self.session.scalars(select(CompanionApplication).where(CompanionApplication.request_id == request_id).order_by(CompanionApplication.created_at.desc()))).all())
        applicant_ids = [application.applicant_id for application in applications]
        users = {
            user.id: user
            for user in (await self.session.scalars(select(User).where(User.id.in_(applicant_ids)))).all()
        } if applicant_ids else {}
        return [CompanionApplicationResponse(
            **CompanionApplicationResponse.model_validate(application).model_dump(exclude={"applicant_display_name"}),
            applicant_display_name=(users[application.applicant_id].nickname or "申请人") if application.applicant_id in users else "申请人",
        ) for application in applications]

    async def list_my_applications(self, applicant_id: str) -> list[CompanionApplication]:
        return list((await self.session.scalars(select(CompanionApplication).where(CompanionApplication.applicant_id == applicant_id).order_by(CompanionApplication.created_at.desc()))).all())

    async def withdraw_application(self, application_id: str, applicant_id: str) -> CompanionApplication:
        application = await self.session.get(CompanionApplication, application_id)
        if application is None:
            raise CommunityError("APPLICATION_NOT_FOUND", "The application does not exist.")
        if application.applicant_id != applicant_id:
            raise CommunityError("FORBIDDEN", "Only the applicant can withdraw an application.")
        if application.status != "pending":
            raise CommunityError("INVALID_APPLICATION_TRANSITION", "Only pending applications can be withdrawn.")
        application.status = "withdrawn"
        request = await self.session.get(CompanionRequest, application.request_id)
        if request:
            self._event("companion_application.withdrawn", "companion_application", application.id, {"application_id": application.id, "request_id": request.id, "owner_id": request.owner_id, "applicant_id": applicant_id})
        return application

    async def decide_application(
        self,
        application_id: str,
        owner_id: str,
        accept: bool,
        reason: str | None = None,
    ) -> tuple[CompanionApplication, str | None]:
        if accept:
            application, conversation = await self.accept_companion_application(application_id, owner_id)
            return application, conversation.id
        application = await self.session.scalar(select(CompanionApplication).where(CompanionApplication.id == application_id).with_for_update())
        if application is None:
            raise CommunityError("APPLICATION_NOT_FOUND", "The application does not exist.")
        request = await self._locked_plan_for_owner(application.request_id, owner_id)
        if application.status != "pending":
            raise CommunityError("INVALID_APPLICATION_TRANSITION", "Only pending applications can be decided.")
        application.status = "rejected"
        self._event("companion_application.rejected", "companion_application", application.id, {"application_id": application.id, "request_id": request.id, "applicant_id": application.applicant_id, "owner_id": owner_id})
        return application, None

    async def accept_companion_application(
        self,
        application_id: str,
        owner_id: str,
        *,
        group_name: str | None = None,
        group_avatar_asset_id: str | None = None,
    ) -> tuple[CompanionApplication, Conversation]:
        """Accept an application without committing the caller's transaction."""
        async with self.session.begin_nested():
            application = await self.session.scalar(select(CompanionApplication).where(CompanionApplication.id == application_id).with_for_update())
            if application is None:
                raise CommunityError("APPLICATION_NOT_FOUND", "The application does not exist.")
            plan = await self._locked_plan_for_owner(application.request_id, owner_id)
            self._require_acceptance_allowed(plan, application)
            await self._require_no_member_blocks(application.applicant_id, plan)
            conversation = await self._get_or_create_companion_group(
                plan,
                owner_id=owner_id,
                group_name=group_name,
                group_avatar_asset_id=group_avatar_asset_id,
            )
            await self._activate_conversation_member(conversation.id, application.applicant_id)
            await self._grant_editor(plan.itinerary_id, application.applicant_id)
            application.status = "accepted"
            application.conversation_id = conversation.id
            plan.accepted_count += 1
            if plan.accepted_count == plan.party_size:
                plan.status = "full"
                self._event("companion_request.full", "companion_request", plan.id, {"request_id": plan.id, "owner_id": owner_id})
            self._event("companion_application.accepted", "companion_application", application.id, {"application_id": application.id, "request_id": plan.id, "conversation_id": conversation.id, "applicant_id": application.applicant_id, "owner_id": owner_id})
            await self.session.flush()
            return application, conversation

    async def remove_companion_member(self, request_id: str, owner_id: str, user_id: str) -> CompanionRequest:
        if owner_id == user_id:
            raise CommunityError("FORBIDDEN", "The owner cannot remove themselves from a companion plan.")
        async with self.session.begin_nested():
            plan = await self._locked_plan_for_owner(request_id, owner_id)
            application = await self.session.scalar(select(CompanionApplication).where(
                CompanionApplication.request_id == plan.id,
                CompanionApplication.applicant_id == user_id,
            ).with_for_update())
            if application is None or application.status != "accepted":
                raise CommunityError("COMPANION_MEMBER_NOT_FOUND", "The companion member is unavailable.")
            await self._revoke_member(plan, user_id)
            application.status = "rejected"
            self._event("companion_member.removed", "companion_request", plan.id, {"request_id": plan.id, "owner_id": owner_id, "user_id": user_id})
            return plan

    async def leave_companion_plan(self, request_id: str, user_id: str) -> CompanionRequest:
        async with self.session.begin_nested():
            plan = await self.session.scalar(select(CompanionRequest).where(CompanionRequest.id == request_id).with_for_update())
            if plan is None:
                raise CommunityError("COMPANION_REQUEST_NOT_FOUND", "The companion plan does not exist.")
            if plan.owner_id == user_id:
                raise CommunityError("FORBIDDEN", "The owner cannot leave a companion plan.")
            application = await self.session.scalar(select(CompanionApplication).where(
                CompanionApplication.request_id == plan.id,
                CompanionApplication.applicant_id == user_id,
            ).with_for_update())
            if application is None or application.status != "accepted":
                raise CommunityError("FORBIDDEN", "Only accepted members can leave a companion plan.")
            await self._revoke_member(plan, user_id)
            application.status = "withdrawn"
            self._event("companion_member.left", "companion_request", plan.id, {"request_id": plan.id, "owner_id": plan.owner_id, "user_id": user_id})
            return plan

    async def complete_companion_plan(self, request_id: str, owner_id: str) -> CompanionRequest:
        async with self.session.begin_nested():
            plan = await self._locked_plan_for_owner(request_id, owner_id)
            if plan.review_status != "approved" or plan.status in {"cancelled", "completed"}:
                raise CommunityError("INVALID_COMPANION_REQUEST_TRANSITION", "The companion plan cannot be completed.")
            if plan.itinerary_id:
                collaborators = list((await self.session.scalars(select(TripCollaborator).where(
                    TripCollaborator.itinerary_id == plan.itinerary_id,
                    TripCollaborator.user_id != plan.owner_id,
                    TripCollaborator.status == "accepted",
                ))).all())
                for collaborator in collaborators:
                    collaborator.status = "revoked"
            plan.status = "completed"
            self._event("companion_request.completed", "companion_request", plan.id, {"request_id": plan.id, "owner_id": owner_id})
            return plan

    def _require_application_allowed(self, plan: CompanionRequest | None) -> None:
        if plan is None:
            raise CommunityError("COMPANION_REQUEST_NOT_FOUND", "The companion plan does not exist.")
        if plan.party_size is None or plan.accepted_count >= plan.party_size:
            raise CommunityError("COMPANION_PLAN_FULL", "This companion plan is full.")
        if plan.review_status != "approved" or plan.status != "open":
            raise CommunityError("COMPANION_REQUEST_UNAVAILABLE", "This companion plan is not accepting applications.")

    def _require_acceptance_allowed(self, plan: CompanionRequest, application: CompanionApplication) -> None:
        self._require_application_allowed(plan)
        if application.status != "pending":
            raise CommunityError("INVALID_APPLICATION_TRANSITION", "Only pending applications can be accepted.")

    async def _locked_plan_for_owner(self, request_id: str, owner_id: str) -> CompanionRequest:
        plan = await self.session.scalar(select(CompanionRequest).where(CompanionRequest.id == request_id).with_for_update())
        if plan is None:
            raise CommunityError("COMPANION_REQUEST_NOT_FOUND", "The companion request does not exist.")
        if plan.owner_id != owner_id:
            raise CommunityError("FORBIDDEN", "Only the request owner can manage this companion request.")
        return plan

    async def _require_no_block(self, first_user_id: str, second_user_id: str) -> None:
        blocked = await self.session.scalar(select(UserBlock.id).where(or_(
            and_(UserBlock.blocker_id == first_user_id, UserBlock.blocked_id == second_user_id),
            and_(UserBlock.blocker_id == second_user_id, UserBlock.blocked_id == first_user_id),
        )))
        if blocked is not None:
            raise CommunityError("USER_BLOCKED", "A block prevents this companion relationship.")

    async def _require_no_member_blocks(self, applicant_id: str, plan: CompanionRequest) -> None:
        member_ids = [plan.owner_id] + list((await self.session.scalars(select(CompanionApplication.applicant_id).where(
            CompanionApplication.request_id == plan.id,
            CompanionApplication.status == "accepted",
        ))).all())
        for member_id in member_ids:
            await self._require_no_block(applicant_id, member_id)

    async def _get_or_create_companion_group(
        self,
        plan: CompanionRequest,
        *,
        owner_id: str,
        group_name: str | None,
        group_avatar_asset_id: str | None,
    ) -> Conversation:
        if plan.conversation_id:
            conversation = await self.session.get(Conversation, plan.conversation_id)
            if conversation is not None:
                await self._activate_conversation_member(conversation.id, plan.owner_id)
                return conversation
        if not group_name or not group_name.strip():
            raise CommunityError("GROUP_NAME_REQUIRED", "首次创建群聊必须填写群名称。")
        if not group_avatar_asset_id:
            raise CommunityError("GROUP_AVATAR_REQUIRED", "首次创建群聊必须上传群头像。")
        await self._validate_group_avatar(owner_id, group_avatar_asset_id)
        conversation = Conversation(
            conversation_type="companion_group",
            title=group_name.strip(),
            avatar_asset_id=group_avatar_asset_id,
        )
        self.session.add(conversation)
        await self.session.flush()
        plan.conversation_id = conversation.id
        self.session.add(ConversationMember(conversation_id=conversation.id, user_id=plan.owner_id, joined_at=utc_now()))
        return conversation

    async def _validate_group_avatar(self, owner_id: str, asset_id: str) -> None:
        asset = await self.session.get(MediaAsset, asset_id)
        if asset is None or asset.owner_id != owner_id:
            raise CommunityError("MEDIA_ASSET_NOT_FOUND", "群头像媒体资源不可用。")
        if asset.status != "completed":
            raise CommunityError("MEDIA_ASSET_NOT_COMPLETED", "群头像上传尚未完成。")
        if asset.mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise CommunityError("INVALID_GROUP_AVATAR", "群头像必须是 JPEG、PNG 或 WebP 图片。")

    async def _activate_conversation_member(self, conversation_id: str, user_id: str) -> None:
        member = await self.session.scalar(select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
        ).with_for_update())
        if member is None:
            self.session.add(ConversationMember(conversation_id=conversation_id, user_id=user_id, joined_at=utc_now()))
        elif member.left_at is not None:
            member.left_at = None
            member.joined_at = utc_now()

    async def _grant_editor(self, itinerary_id: str | None, user_id: str) -> None:
        if not itinerary_id:
            raise CommunityError("INVALID_COMPANION_ITINERARY", "The companion itinerary is unavailable.")
        itinerary = await self.session.get(Itinerary, itinerary_id)
        if itinerary is None:
            raise CommunityError("INVALID_COMPANION_ITINERARY", "The companion itinerary is unavailable.")
        if itinerary.owner_id == user_id:
            return
        collaborator = await self.session.scalar(select(TripCollaborator).where(
            TripCollaborator.itinerary_id == itinerary_id,
            TripCollaborator.user_id == user_id,
        ).with_for_update())
        if collaborator is None:
            self.session.add(TripCollaborator(itinerary_id=itinerary_id, user_id=user_id, role="editor", status="accepted"))
        else:
            collaborator.role, collaborator.status = "editor", "accepted"

    async def _revoke_member(self, plan: CompanionRequest, user_id: str) -> None:
        if plan.itinerary_id:
            collaborator = await self.session.scalar(select(TripCollaborator).where(
                TripCollaborator.itinerary_id == plan.itinerary_id,
                TripCollaborator.user_id == user_id,
            ).with_for_update())
            if collaborator is not None:
                collaborator.status = "revoked"
        if plan.conversation_id:
            member = await self.session.scalar(select(ConversationMember).where(
                ConversationMember.conversation_id == plan.conversation_id,
                ConversationMember.user_id == user_id,
            ).with_for_update())
            if member is not None and member.left_at is None:
                member.left_at = utc_now()
        plan.accepted_count = max(1, plan.accepted_count - 1)
        if plan.status == "full":
            plan.status = "open"

    async def _owned_companion_request(self, request_id: str, owner_id: str) -> CompanionRequest:
        request = await self.session.get(CompanionRequest, request_id)
        if request is None:
            raise CommunityError("COMPANION_REQUEST_NOT_FOUND", "The companion request does not exist.")
        if request.owner_id != owner_id:
            raise CommunityError("FORBIDDEN", "Only the request owner can manage this companion request.")
        return request

    async def _can_publish_field_note(self, itinerary: Itinerary, actor_id: str) -> bool:
        if itinerary.owner_id == actor_id:
            return True
        collaborator = await self.session.scalar(select(TripCollaborator.id).where(
            TripCollaborator.itinerary_id == itinerary.id,
            TripCollaborator.user_id == actor_id,
            TripCollaborator.role == "editor",
            TripCollaborator.status == "accepted",
        ))
        return collaborator is not None

    async def _validate_field_note_media(self, author_id: str, media_ids: list[str]) -> None:
        assets = list((await self.session.scalars(select(MediaAsset).where(MediaAsset.id.in_(media_ids)))).all())
        assets_by_id = {asset.id: asset for asset in assets}
        for media_id in media_ids:
            asset = assets_by_id.get(media_id)
            if asset is None:
                raise CommunityError("INVALID_FIELD_NOTE_MEDIA", "A field-note image is unavailable.")
            if asset.owner_id != author_id:
                raise CommunityError("FORBIDDEN", "Field-note images must belong to the publishing user.")
            if asset.status != "completed":
                raise CommunityError("INVALID_FIELD_NOTE_MEDIA", "Field-note images must be fully uploaded.")
            if asset.mime_type not in {"image/jpeg", "image/png", "image/webp"}:
                raise CommunityError("INVALID_FIELD_NOTE_MEDIA", "Field-note images must be JPEG, PNG, or WebP files.")

    async def _owned_post(self, post_id: str, user_id: str) -> Post:
        post = await self.session.get(Post, post_id)
        if post is None:
            raise CommunityError("POST_NOT_FOUND", "The post does not exist.")
        if post.author_id != user_id:
            raise CommunityError("FORBIDDEN", "Only the post author can perform this action.")
        return post

    async def _published_post(self, post_id: str) -> Post:
        post = await self.session.get(Post, post_id)
        if post is None or post.status != "published":
            raise CommunityError("POST_NOT_FOUND", "The published post does not exist.")
        return post

    def _event(self, event_type: str, aggregate_type: str, aggregate_id: str, payload: dict[str, Any]) -> None:
        self.session.add(OutboxEvent(event_type=event_type, aggregate_type=aggregate_type, aggregate_id=aggregate_id, trace_id=new_uuid(), payload_json=payload))


def _encode_field_note_cursor(post: Post, sort: str) -> str:
    payload = {"id": post.id, "published_at": post.published_at.isoformat(), "sort": sort}
    if sort == "recommended":
        payload["copy_count"] = post.copy_count
    return urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()


def _decode_field_note_cursor(cursor: str) -> dict[str, Any]:
    try:
        payload = json.loads(urlsafe_b64decode(cursor.encode()).decode())
        if not isinstance(payload, dict) or not isinstance(payload.get("id"), str) or not isinstance(payload.get("published_at"), str):
            raise ValueError
        if payload.get("sort") not in {"latest", "recommended"}:
            raise ValueError
        payload["published_at"] = datetime.fromisoformat(payload["published_at"])
        if payload["sort"] == "recommended" and not isinstance(payload.get("copy_count"), int):
            raise ValueError
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError, Base64Error):
        raise CommunityError("INVALID_CURSOR", "The cursor is unavailable.") from None


def _encode_companion_cursor(plan: CompanionRequest) -> str:
    if plan.start_date is None:
        raise CommunityError("INVALID_CURSOR", "The cursor is unavailable.")
    data = {"id": plan.id, "start_date": plan.start_date.isoformat(), "created_at": plan.created_at.isoformat()}
    encoded = urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
    signature = hmac_new(_companion_cursor_secret(), encoded.encode(), "sha256").hexdigest()
    return f"{encoded}.{signature}"


def _decode_companion_cursor(cursor: str) -> dict[str, Any]:
    try:
        encoded, signature = cursor.rsplit(".", 1)
        expected = hmac_new(_companion_cursor_secret(), encoded.encode(), "sha256").hexdigest()
        if not compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(urlsafe_b64decode(encoded.encode()).decode())
        if not isinstance(payload, dict) or not isinstance(payload.get("id"), str) or not isinstance(payload.get("start_date"), str) or not isinstance(payload.get("created_at"), str):
            raise ValueError
        payload["start_date"] = date.fromisoformat(payload["start_date"])
        payload["created_at"] = datetime.fromisoformat(payload["created_at"])
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError, Base64Error):
        raise CommunityError("INVALID_CURSOR", "The cursor is unavailable.") from None


def _companion_cursor_secret() -> bytes:
    return (Settings().jwt_secret or "development-companion-cursor-secret").encode()


def _field_note_city_code(snapshot: dict[str, Any]) -> str | None:
    destination = snapshot.get("destination") if isinstance(snapshot, dict) else None
    city_code = destination.get("city_code") if isinstance(destination, dict) else None
    return city_code if isinstance(city_code, str) and city_code else None


def _companion_city_code(snapshot: dict[str, Any]) -> str | None:
    destination = snapshot.get("destination") if isinstance(snapshot, dict) else None
    if isinstance(destination, dict):
        city_code = destination.get("city_code")
        if isinstance(city_code, str) and city_code:
            return city_code
    days = snapshot.get("days") if isinstance(snapshot, dict) else None
    if not isinstance(days, list):
        return None
    for day in days:
        if not isinstance(day, dict) or not isinstance(day.get("events"), list):
            continue
        for event in day["events"]:
            poi_snapshot = event.get("poi_snapshot") if isinstance(event, dict) else None
            city_code = poi_snapshot.get("city") if isinstance(poi_snapshot, dict) else None
            if isinstance(city_code, str) and city_code:
                return city_code
    return None


def _companion_route_summary(snapshot: dict[str, Any] | None) -> tuple[int, str | None]:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("days"), list):
        return 0, None
    route_count, cover_candidate = 0, None
    for day in snapshot["days"]:
        events = day.get("events") if isinstance(day, dict) else None
        if not isinstance(events, list):
            continue
        route_count += len(events)
        if cover_candidate is None:
            for event in events:
                poi = event.get("poi_snapshot") if isinstance(event, dict) else None
                name = poi.get("name") if isinstance(poi, dict) else None
                if isinstance(name, str) and name:
                    cover_candidate = name
                    break
    return route_count, cover_candidate


def _public_itinerary_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Project a version snapshot to the immutable, route-only public contract."""
    if not isinstance(snapshot, dict):
        raise CommunityError("INVALID_FIELD_NOTE_VERSION", "The selected itinerary version is invalid.")
    title, start_date, end_date, days = snapshot.get("title"), snapshot.get("start_date"), snapshot.get("end_date"), snapshot.get("days")
    if not isinstance(title, str) or not isinstance(start_date, str) or not isinstance(end_date, str) or not isinstance(days, list):
        raise CommunityError("INVALID_FIELD_NOTE_VERSION", "The selected itinerary version is invalid.")
    try:
        date.fromisoformat(start_date)
        date.fromisoformat(end_date)
    except ValueError:
        raise CommunityError("INVALID_FIELD_NOTE_VERSION", "The selected itinerary version is invalid.") from None
    public_days: list[dict[str, Any]] = []
    for day in sorted(days, key=lambda item: item.get("display_order") if isinstance(item, dict) else -1):
        if not isinstance(day, dict) or not isinstance(day.get("day_date"), str) or not isinstance(day.get("display_order"), int) or not isinstance(day.get("events"), list):
            raise CommunityError("INVALID_FIELD_NOTE_VERSION", "The selected itinerary version is invalid.")
        public_events: list[dict[str, Any]] = []
        for event in sorted(day["events"], key=lambda item: item.get("display_order") if isinstance(item, dict) else -1):
            if not isinstance(event, dict) or not isinstance(event.get("poi_id"), str) or not event["poi_id"] or not isinstance(event.get("poi_snapshot"), dict) or not isinstance(event.get("display_order"), int):
                raise CommunityError("INVALID_FIELD_NOTE_VERSION", "The selected itinerary version is invalid.")
            starts_at, ends_at, notes = event.get("starts_at"), event.get("ends_at"), event.get("notes")
            if (starts_at is not None and not isinstance(starts_at, str)) or (ends_at is not None and not isinstance(ends_at, str)) or (notes is not None and not isinstance(notes, str)):
                raise CommunityError("INVALID_FIELD_NOTE_VERSION", "The selected itinerary version is invalid.")
            public_events.append({"poi_id": event["poi_id"], "poi_snapshot": dict(event["poi_snapshot"]), "starts_at": starts_at, "ends_at": ends_at, "display_order": event["display_order"], "notes": notes})
        public_days.append({"day_date": day["day_date"], "display_order": day["display_order"], "events": public_events})
    return {"title": title, "start_date": start_date, "end_date": end_date, "days": public_days}
