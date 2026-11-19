# ECHO dashboard design

M6 is a local document workspace for finding explicitly imported research
material. Research evaluation remains the project's primary deliverable.

## Design direction

Use a compact, left-aligned file-manager layout. A persistent navigation rail
holds Search, Library, Collections, Sources and Settings. Search uses a broad
query field, explicit filters, a result list and a separate reading panel.
Library uses document rows; Sources shows ingestion and indexing work.

```text
Navigation      Page title                         Import documents
                Query / filters
                Results or library rows            Document preview
Local status    Pagination                         Source / collection actions
```

The distinctive element is the reading panel: a quiet document surface with
the matched passage, source metadata and collection controls together. Avoid
chat bubbles, marketing heroes, ornamental charts, gradients, decorative
animation and fabricated documents or statistics. Empty states offer an action.

## Tokens

- Canvas: `#f6f7f4`; navigation: `#eef0eb`; surface: `#ffffff`.
- Ink: `#202a25`; secondary text: `#58645d`; accent: `#275c45`.
- Dark canvas: `#18211d`; dark surface: `#202d26`; text: `#edf2ee`.
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
