# Personal Settings Design

## Status

Approved design for implementation planning. This specification covers the consumer frontend and the user-settings API only. The admin frontend remains unchanged.

## Goal

Add a discoverable, persistent personal settings center for consumer users. The center must combine account profile management, travel preferences, notification controls, and basic privacy controls. Saved travel preferences must be used by new AI planning requests while allowing explicit values in the current planning session to override them.

## Scope

### Included

- New consumer route: `/me/settings`.
- Account profile section for avatar, nickname, read-only phone number, and read-only user ID.
- Travel preference section for departure city, budget level, travel pace, interest tags, and traveler type.
- Notification section with a master switch and order, itinerary collaboration, and community interaction switches.
- Privacy section with `private` and `collaborators` profile visibility options.
- Independent `user_settings` persistence model and migration.
- `GET /api/v1/users/me/settings` and `PATCH /api/v1/users/me/settings`.
- AI planning preference merge: explicit current-plan values take precedence over saved defaults.
- A settings entry in the authenticated consumer navigation and account area.
- Compatibility behavior for the existing `/me/profile` route.

### Explicitly excluded

- Phone-number change or re-binding.
- Password authentication.
- Login-device management or remote session revocation.
- Account deletion.
- Blocking, muting, or social moderation controls.
- Per-channel push/email/SMS delivery settings.
- Recomputing existing itineraries after a preference change.
- Admin settings management UI.

## Information Architecture

The settings page is a grouped settings center, not a generic form dump.

### Account profile

- Editable avatar.
- Editable nickname.
- Read-only bound phone number.
- Read-only account ID.
- Save profile action using the existing profile endpoints.

### Travel preferences

- Common departure city, optional.
- Budget: `economy`, `balanced`, `premium`.
- Pace: `relaxed`, `balanced`, `packed`.
- Interest tags from the controlled product vocabulary: food, nature, city walk, history, culture, shopping, and the existing planning tags where applicable.
- Traveler type: `solo`, `couple`, `friends`, `family`.
- Save preference action using the settings endpoint.

### Notifications

- Master notification switch.
- Order and payment updates.
- Itinerary collaboration updates.
- Community interaction updates.

When the master switch is off, category switches remain stored but no new notification in those categories is delivered. Existing inbox entries are not deleted, and read/unread behavior remains unchanged.

### Privacy

- Profile visibility: `private` or `collaborators`.
- Phone number is never exposed to other users regardless of this setting.
- The setting changes presentation eligibility only; backend resource authorization remains mandatory.

## Navigation And Compatibility

- Add `个人设置` to the authenticated account area and mobile navigation.
- Prefer an avatar or nickname account control that links to `/me/settings`.
- Keep `/me/profile` as a compatibility route. It should direct users to the account-profile section of the settings center, either through a redirect with an anchor or an explicit link, without breaking bookmarked URLs.
- No settings route is available to unauthenticated users; the existing consumer route guard redirects to login.

## Backend Data Model

Add a `user_settings` table with one row per user:

- `user_id`: primary key and foreign key to `users.id`.
- `departure_city`: nullable string.
- `budget_level`: nullable or defaulted enum/string constrained to `economy`, `balanced`, `premium`.
- `travel_pace`: nullable or defaulted enum/string constrained to `relaxed`, `balanced`, `packed`.
- `interest_tags`: JSON array of controlled strings.
- `traveler_type`: nullable or defaulted enum/string constrained to `solo`, `couple`, `friends`, `family`.
- `notifications_enabled`: boolean, default `true`.
- `order_notifications`: boolean, default `true`.
- `itinerary_notifications`: boolean, default `true`.
- `community_notifications`: boolean, default `true`.
- `profile_visibility`: enum/string constrained to `private` and `collaborators`, default `collaborators`.
- `created_at` and `updated_at`.

The migration must create the table, primary key, foreign key, timestamps, and indexes/constraints required by the existing MySQL conventions. Reading settings for a user without a row creates the default row transactionally or returns the same defaults through a service-level get-or-create operation.

## API Contract

### Read settings

```text
GET /api/v1/users/me/settings
```

Returns the complete settings object, including defaults. It never returns another user's settings.

### Partial update

```text
PATCH /api/v1/users/me/settings
```

The request is partial. Only fields present in the request are changed. The response is the complete normalized settings object.

The API must validate:

- Enum values for budget, pace, traveler type, and visibility.
- Interest tags against the controlled allow-list.
- String length for departure city.
- JSON shape and duplicate tags.
- Consumer ownership through the existing `CurrentConsumer` dependency.

Invalid input returns the project's standard `422` validation shape. Missing authenticated users use the existing authentication error contract.

The existing `/auth/me` and `PATCH /users/me` contracts remain responsible for session-facing identity and profile fields. The new settings endpoints do not duplicate nickname or avatar mutation.

## AI Preference Integration

New AI planning requests build an effective preference object:

1. Load saved settings for the authenticated user.
2. Apply saved departure city, budget, pace, traveler type, and interests as defaults.
3. Apply explicit values from the current planning form or assistant request over those defaults.
4. Pass only the effective values to the existing planning workflow contract.

An empty explicit value means the user intentionally cleared that field and must not be replaced by the saved value. Changing settings does not mutate existing itineraries or replay prior jobs.

The frontend should show which planning values came from saved preferences where that improves clarity, but users must be able to override or clear them in the current planning flow.

## Privacy Integration

`profile_visibility` is applied where consumer profile data is serialized for community, companion, chat, or collaboration contexts:

- `private`: do not expose profile details outside the owner-facing context.
- `collaborators`: expose the minimum allowed nickname/avatar data to users with an existing authorized collaboration relationship.
- Never expose phone numbers through consumer-facing profile responses.

This setting is not an authorization mechanism. Existing ownership, membership, collaboration, and moderation checks continue to run on every protected resource.

## Frontend Design And States

Use the current C-side travel visual system and the approved taste-skill principles. The settings center should feel like a calm travel control room, not an admin table.

- Desktop: constrained content area with a compact left section index and a right content column.
- Mobile: single-column sections with a sticky or repeated section heading; no horizontal overflow.
- Use existing Vue 3 Composition API, Element Plus primitives already installed, and the existing Lucide icon family.
- Keep one clear save action per section; do not use a global save button that obscures which data is dirty.
- Use semantic labels above controls, visible keyboard focus, and switch/segmented controls for binary and enumerated settings.
- Avoid nested cards; use whitespace, section dividers, and one framed group only where hierarchy requires it.

Required states:

- Skeleton loading for the settings page.
- Retryable load error that preserves page structure.
- Per-section saving state that disables only the active section.
- Success confirmation scoped to the saved section.
- Inline validation and actionable API errors.
- Dirty-state tracking and a leave confirmation when changes are not saved.
- Empty optional departure city and interest tags with clear defaults.
- Reduced-motion behavior for any transitions.

## Error And Consistency Rules

- Optimistic UI is not used for persisted settings; controls reflect server-confirmed values after save.
- On failed save, preserve the user's local edits and show the server error.
- Concurrent saves from different sections must not overwrite unrelated fields; PATCH requests are partial and the client should reconcile from the complete response.
- Defaults are defined once in the backend schema/service and mirrored as typed frontend constants for rendering only.

## Testing And Verification

### Backend

- Schema tests for all enum and tag validation.
- Router tests for get-or-create defaults, partial updates, user isolation, and authentication.
- Tests verifying the complete response shape and that omitted PATCH fields are preserved.
- Tests for notification master/category semantics where notifications are emitted or delivered.
- Tests for profile visibility serialization in affected consumer contexts.
- Alembic verification: `upgrade head`, `downgrade -1`, `upgrade head` against MySQL.

### Frontend

- Settings API client tests.
- Settings page tests for loading, save success, save failure, dirty navigation, and mobile-compatible sections.
- Tests for AI preference merge precedence: explicit current-plan values, explicit clears, and saved defaults.
- Regression tests for profile, notifications, planning, assistant, community, and companion flows.

### Commands

```text
cd backend
alembic upgrade head
alembic downgrade -1
alembic upgrade head

cd frontend-c
npm run typecheck
npm run test
npm run build
```

## Acceptance Criteria

- An authenticated consumer can find and open `个人设置` from desktop and mobile navigation.
- The page loads complete defaults for a first-time settings user.
- Profile changes use existing profile APIs and remain visible after refresh.
- Travel preferences persist and are automatically used in new AI planning requests.
- Explicit planning inputs override saved preferences, including intentional clears.
- Notification master and category switches persist with the documented semantics.
- Privacy visibility is enforced in consumer-facing profile serialization without exposing phone numbers.
- Unauthenticated access redirects to login.
- All required loading, error, success, dirty, and responsive states work without changing admin behavior.
