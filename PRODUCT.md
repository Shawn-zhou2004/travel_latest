# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary user is an ordinary traveler using a desktop browser to plan, edit, and save a multi-day trip. This audience and workflow are inferred from the confirmed consumer application routes, itinerary domain, and the supplied Pi Travel reference pages.

## Product Purpose

The product helps travelers turn a destination and a set of places into an editable itinerary with dates, ordered stops, route context, community notes, companions, and travel orders. Success means a traveler can start a plan quickly and adjust it between a timeline and a map without losing the intended stop order.

## Positioning

The product treats a trip as a living, versioned workspace rather than a static generated document. It preserves user-controlled order while exposing route, place, community, and transaction context around that plan.

## Operating Context

The main consumer workflow is desktop-first: open the planning entry, choose or describe a trip, review a multi-day timeline, inspect a map or recommendations, and return to saved plans. External map, AI, supplier, and payment services may be unavailable during development and must surface explicit states rather than fabricated results.

## Capabilities and Constraints

- Consumer authentication uses phone verification; development environments may expose a temporary debug code.
- Itineraries have a one-to-seven-day range, versioned edits, collaborators, ordered days, and ordered events.
- Route recalculation must not silently change the user's explicit event order.
- Community, companion, chat, search, and order routes are part of the consumer shell, but the itinerary workspace is the primary redesign surface.
- The current visual redesign is desktop-first. Basic responsive behavior remains useful but is not the primary acceptance target.
- MySQL is the business fact source. API errors, conflicts, unavailable integrations, and empty states must remain explicit.

## Brand Commitments

- Product is an AI travel planning platform with a consumer application and a separate administration console.
- The supplied Pi Travel introduction page and planning page are reference material for the new consumer visual language and itinerary editing interaction, not content or brand assets to copy.
- The consumer redesign should combine a calm branded entry with a dense, practical planning workbench.

## Evidence on Hand

- Reference product introduction: https://www.pitravel.cn/
- Reference planning workspace: https://www.pitravel.cn/plan
- Current consumer source under `frontend-c/src/`.
- Current itinerary API, store, timeline, map panel, and workspace components under `frontend-c/src/features/itineraries/`.
- No approved production photography or final product logo has been supplied; new visual assets must be treated as authored UI material or replaced with verified assets later.

## Product Principles

- Start with an actionable plan, not a marketing explanation.
- Keep the itinerary editable, legible, and version-safe.
- Make external-service limits visible and honest.
- Preserve the traveler's explicit choices while adding useful context.
- Keep public inspiration and private planning clearly separated.

## Accessibility & Inclusion

Use semantic landmarks, keyboard-visible focus, labeled controls, readable contrast, stable control dimensions, and explicit loading, error, conflict, empty, and unavailable states. Desktop is the primary surface for this redesign; smaller screens should remain usable without defining the main composition.
