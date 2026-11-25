# ECHO dashboard design

M6 is a local document workspace for finding explicitly imported research
material. Research evaluation remains the project's primary deliverable.

## Design direction

Use a left-aligned file-manager layout with a persistent navigation rail.
Search opens with a pine-green composer, a filter disclosure, and panels for
recent searches and library activity. Results retain a separate reading panel.
Library uses document rows. Activity shows extraction and indexing work with
status, timestamps, preview access, and retry.

```text
Navigation      Page title                         Import documents
                Search composer / filters
                Recent searches                    Library activity
                Results                            Document preview
Local status    Pagination                         Source / collection actions
```

The composer puts the query first. The reading panel pairs the matched passage
with source metadata and collection controls. Empty states offer an action.
Activity and library counts use data from the running local server.

## Tokens

- Light canvas `#f6f7f5`, navigation `#edf0ed`, and workspace surface `#ffffff`.
- Light ink `#17251e`, secondary text `#516058`, and accent `#245942`.
- Dark canvas `#181d1b`, workspace surface `#222a26`, and text `#edf2ef`.
- Pine-green search composer with pale text in both themes.
- Typography: locally available Segoe UI / system sans for navigation and
  controls; Georgia for the document reading surface only. No font downloads.
- Spacing: 4px base; 8/12/16/24/32px steps. Controls at least 40px high;
  comfortable touch controls on narrow displays. Subtle 6–12px radii.
- Native focus rings, semantic labels, native modal dialog focus containment,
  skip navigation, reduced-motion support and independently checked themes.

## Guidance and scope

Applied frontend-design, UI UX Pro Max and Vercel React guidance. The skill's
document-product lookup supports flat, low-cost desktop UI and visible focus.
Its marketing-page pattern, remote fonts and scroll effects do not fit this
local research workspace and are omitted. The palette above deliberately uses
one restrained accent and consistent document rows rather than feature cards.

Use native fetch, bounded pages, request cancellation and parallel independent
requests. Keep tokens, queries and document content out of browser storage and
URLs. Only the versioned theme preference persists. Render document text as
text, never HTML. No remote assets, telemetry, account system or cloud hosting.

## Dependencies

React, React DOM, TypeScript, Vite and Tailwind are the requested stack.
The official Vite React/Tailwind plugins and TypeScript declarations support
that toolchain. Playwright is development-only for real browser workflows;
axe-core's Playwright adapter checks accessibility in both themes. No router,
component framework, icon package, animation package or backend dependency is
needed. Small shared SVG icons and native dialogs keep runtime weight modest.
Prettier is development-only for consistent, reviewable TypeScript/JSX/CSS.
