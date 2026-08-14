# askgrey.ai

Revolutionizing AI agent for corporate biomedical researchers — literature, screening, protocol
creation, regulatory and grants, each driven by an agent in a dual-pane workspace.

This repository currently contains the **foundation only** — design system, navigation shell,
workspace layout and authentication. No agent or tab-specific logic has been built yet.

```
backend/    FastAPI service (auth, health) — Python 3.10+
frontend/   React + TypeScript + Vite client
```

## Running locally

```bash
# Backend — http://localhost:8000 (docs at /docs)
cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env
.venv/bin/uvicorn app.main:app --reload

# Frontend — http://localhost:5173, proxies /api to the backend
cd frontend
npm install
npm run dev
```

The first account to register becomes the workspace `owner`; later accounts join as `member`.

## Checks

| Package    | Lint            | Types       | Tests     |
| ---------- | --------------- | ----------- | --------- |
| `backend`  | `ruff check .`  | `mypy app`  | `pytest`  |
| `frontend` | `npm run lint`  | `npm run typecheck` | `npm test` |

CI runs all six on every pull request.

---

## Design tokens

**Every colour, size, space and duration in the product comes from a token.** Tokens are CSS
custom properties declared once in `frontend/src/styles/tokens.css`. Literal colours in any other
stylesheet fail the test in `frontend/src/styles/tokens.test.ts`, so this is enforced, not just
convention.

```css
/* Do this */
.cell {
  background: var(--color-surface-panel);
  border-bottom: 1px solid var(--color-border-subtle);
  font-size: var(--font-size-xs);
}

/* Never this */
.cell {
  background: #101317;
  font-size: 12px;
}
```

### Surfaces

Panels stack from the deepest workspace layer upward. Pick by elevation, not by appearance.

| Token                        | Use                                            |
| ---------------------------- | ---------------------------------------------- |
| `--color-surface-workspace`  | The workspace canvas behind everything          |
| `--color-surface-panel`      | Off-black panels docked on the workspace        |
| `--color-surface-raised`     | Cards, panel headers, sticky table headers      |
| `--color-surface-overlay`    | Modals, menus, hover fills                      |
| `--color-surface-inset`      | Inputs, wells, code blocks                      |

### Text and borders

`--color-text-primary` is stark white and reserved for primary content; `--color-text-secondary`
for supporting copy; `--color-text-tertiary` for metadata and placeholders. Borders run
`--color-border-subtle` → `--color-border-default` → `--color-border-strong` in slate gray.

### Accents — semantic, not decorative

Accents carry meaning. Do not use them for emphasis.

| Token                       | Colour                | Reserved for                                        |
| --------------------------- | --------------------- | --------------------------------------------------- |
| `--color-accent-pipeline`   | Acid blue             | Active multi-agent pipeline execution, focus rings   |
| `--color-accent-warning`    | Muted amber           | Compliance warnings, toxicity alerts                 |
| `--color-accent-success`    | Low-saturation emerald| Passed validation checkpoints                        |
| `--color-accent-danger`     | Desaturated red       | Destructive actions only — never a scientific result |

Each accent has a `-muted` variant for borders and a `-surface` variant for tinted backgrounds.

Rather than reaching for these directly, render state through `<StatusPill tone="...">`, whose
tones (`running`, `warning`, `validated`, `idle`) map to the accents in one place.

### Typography

SF Pro Display for headings and brand, SF Pro Text for UI, SF Mono for structural and code
content. The scale is deliberately small and dense so multi-column tables stay readable:
`--font-size-2xs` (11px) through `--font-size-2xl` (26px), with `--font-size-sm` (13px) as the UI
default. Use `--line-height-dense` in tables, `--line-height-normal` in UI, and
`--line-height-relaxed` for prose. `--letter-spacing-wide` is for uppercase eyebrow labels and
column headers.

### Space, radius, elevation, motion

Space follows a 4px grid (`--space-1` … `--space-12`). Radii run `--radius-xs` … `--radius-full`.
Elevation uses `--shadow-panel` / `--shadow-raised` / `--shadow-overlay`; focus uses
`--shadow-focus-ring`. Transitions use `--duration-fast` or `--duration-normal` with
`--easing-standard`; all durations collapse to zero under `prefers-reduced-motion`.

---

## Layout components

### `AppShell` — `src/layouts/AppShell.tsx`

The authenticated frame: sidebar, top bar with workspace identity, and an `<Outlet />` for the
routed page. Applied once in `App.tsx`; pages never render it themselves.

### `Sidebar` — `src/layouts/Sidebar.tsx`

Left-docked collapsible navigation. Its contents come from `src/layouts/navigation.ts` —
**add new tabs there**, not in the component. Collapsing narrows the rail to icons and persists
across reloads in `localStorage`.

### `DualPaneWorkspace` — `src/layouts/DualPaneWorkspace.tsx`

The reusable split every tab is built on: agent chat on the left, data viewer / editor /
visualization on the right.

```tsx
<DualPaneWorkspace
  storageKey="literature"        // persists this tab's divider position
  defaultRatio={0.42}            // left pane share before the user drags
  leftLabel="Literature assistant"
  rightLabel="Source reader"
  left={<Panel title="Literature">{/* chat */}</Panel>}
  right={<Panel title="Source reader" flush>{/* PDF, table, graph */}</Panel>}
/>
```

The divider is draggable, keyboard-accessible (arrow keys move it, `Home` resets), exposed as an
ARIA `separator`, and clamped to 20–80% so neither pane can be collapsed away. Give each tab a
distinct `storageKey` so users keep a per-tab split.

### `Panel` — `src/components/Panel.tsx`

The standard bordered container with an optional header for a title and actions. Use
`flush` when the panel hosts a table or editor that manages its own padding.

### Building a new tab

1. Add the route to `src/layouts/navigation.ts` and `src/App.tsx`.
2. Render a `DualPaneWorkspace` with a unique `storageKey`.
3. Put content in `Panel`s; express state with `StatusPill`; use `Button` for actions.
4. Style with CSS modules that reference tokens only.

`src/pages/TabPlaceholder.tsx` is a working example of steps 2–4.

---

## Authentication

Email/password with JWT access (30 min) and refresh (14 day) tokens; bcrypt password hashing;
tokens in `localStorage`, refreshed transparently on load by `AuthProvider`.

SSO is wired but inert: `GET /api/auth/sso` reports whether an OIDC provider is configured, and
the login screen renders the provider button only when it is. Set `OIDC_ISSUER` and
`OIDC_CLIENT_ID` to enable it. **The authorization-code exchange is not implemented yet** — the
endpoint exists so the frontend contract is stable before tenant onboarding lands.

## Backend services

`backend/app/services/pubmed/` wraps the NCBI Entrez E-utilities: natural-language →
Boolean/MeSH Entrez translation, rate limiting (3/s, or 10/s with `NCBI_API_KEY`), retry with
backoff, and normalized records behind `GET /api/pubmed/search`. See
[its README](backend/app/services/pubmed/README.md) for the public interface and configuration.

## Deployment

Frontend deploys to Vercel (`frontend/vercel.json`), backend to Railway
(`backend/railway.toml`, health-checked at `/api/health`). Both jobs in
`.github/workflows/deploy.yml` skip themselves until `VERCEL_TOKEN` / `RAILWAY_TOKEN` are added
to repository secrets.

Set at minimum in production: `JWT_SECRET` (required — the default is a development placeholder),
`DATABASE_URL` (Postgres; SQLite is development only), and `CORS_ORIGINS`.
