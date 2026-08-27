# Design System

## Direction

Field / Travel is a living route desk for ordinary travelers planning a real trip at a desktop browser. The visual world borrows from field notebooks, route diagrams, and a well-used map table without pretending to be a paper simulation. The product should feel calm enough for repeated editing and specific enough to be remembered as a planning instrument.

The assigned direction seed is `3a80d583`. The chosen form is a route-led desk: a branded route preview introduces the mechanism, then the planning surface becomes denser and more operational.

## Palette

- Deep sea ink: `#102B3A`, navigation, primary actions, and high-contrast structure.
- Route ink: `#142638`, headings and readable foreground text.
- Sea-glass teal: `#167A76`, selection, links, saved state, and route context.
- Paper white: `#F3F7F5`, the main working surface.
- Saffron waypoint: `#D99824`, dates, route markers, and attention points.
- Coral exception: `#CE644E`, destructive actions and conflict emphasis.

Color is restrained in the workbench. Teal is reserved for active controls and route state; saffron and coral communicate meaning rather than decoration.

## Type

The product uses an Avenir Next and Chinese system sans stack for headings, body copy, controls, and labels. IBM Plex Mono or an installed monospace fallback is reserved for route metadata, versions, dates, and operational labels. Headings use compact weight and modest negative tracking; utility text is small, explicit, and never used as costume.

## Structure

The global shell is a deep-ink navigation band with a compact brand lockup and icon-plus-label navigation. Public discovery is a route-led visual entry. `/plan` uses a two-mode desk: destination planning and honest guide parsing. The itinerary workspace uses three columns on desktop:

1. A dark day rail for date navigation and day creation.
2. A white timeline for ordered stops and direct editing.
3. A contextual map and selected-place panel for route geometry, notes, and unavailable-service states.

Rules are mostly one-pixel lines and unrounded controls. Cards are used only for repeated route entries or genuinely framed tools. Mobile collapses the day rail into a horizontal strip and stacks map context below the timeline.

## Signature

The memorable interaction is the relationship between the timeline and route geometry: selecting, moving, removing, or annotating a stop changes the planning context while preserving the traveler's explicit order. Route recalculation is visibly separate from event ordering, and unavailable map services never fabricate a result.

## States

Loading, empty, saved, conflict, unavailable, and route-updating states are explicit in the itinerary workspace. Errors name the failed action and the recovery path. Keyboard focus uses the saffron outline consistently. Reduced-motion users receive the same information without animated transitions.

## Asset Note

The discovery hero currently uses an external Unsplash landscape as an authored placeholder for the route-led entry. It should be replaced with approved product photography or a locally managed image before production deployment.
