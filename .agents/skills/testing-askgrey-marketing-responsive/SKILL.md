---
name: testing-askgrey-marketing-responsive
description: How to end-to-end test the askgrey.ai public marketing site, the Host-header host split (marketing vs product), the compact/mobile layout below 820px, and conditional Google SSO on the login screen.
---

# Testing askgrey.ai marketing site, host split and compact/mobile layout

Covers the surfaces that are selected by **hostname** or by **viewport width**, which is what
makes them easy to test wrongly. See `testing-askgrey-shell` for bringing the stack up, auth and
the dual-pane resizer.

## The host split: marketing vs product

`frontend/src/lib/hosts.ts` chooses the whole React tree from the hostname:

| Hostname | Tree |
| --- | --- |
| `askgrey.app`, `www.askgrey.app` (i.e. `MARKETING_HOST` and its `www.`) | marketing site |
| anything else, **including `localhost`** | product app |

Overrides for local work: `?site=marketing` / `?site=app`.

`MARKETING_HOST` / `PRODUCT_HOST` come from `VITE_MARKETING_HOST` / `VITE_PRODUCT_HOST`, defaulting
to `askgrey.app` / `lab.askgrey.app`.

### Run TWO Vite servers — the query override cannot prove CTA behaviour

This is the key lesson. `?site=marketing` is enough for *content* and *SEO-string* assertions, but
it **cannot** prove that CTAs resolve to the absolute product host, because:

- `App.tsx` picks the root tree **only at initial mount**;
- React Router `<Link>` navigation **drops the query string**, so after an in-app nav
  `productUrl()` sees an empty `search`, `isMarketingHost()` returns false, and it correctly
  returns a **relative** path.

That relative href is an artifact of the forcing trick, **not a defect** — do not report it. Prove
CTAs on a server where the *hostname branch* fires with no query param:

```bash
# product host (localhost is the product)
(cd frontend && setsid nohup npm run dev > /tmp/fe.log 2>&1 < /dev/null &)          # :5173
# marketing host, production-shaped: hostname itself selects marketing
(cd frontend && VITE_MARKETING_HOST=localhost setsid nohup npm run dev -- --port 5174 \
   > /tmp/femk.log 2>&1 < /dev/null &)                                               # :5174
```

Then assert every CTA href is exactly `https://lab.askgrey.app/login`
(hero "Open the workspace", closing panel, nav "Sign in", footer "Sign in", Security page CTA).

**Caveat to not misreport:** on `:5174` the footer renders `© YEAR askgrey · localhost` because
`MARKETING_HOST` is literally `localhost` there. That is the local env value, not a branding bug.

### robots.txt / sitemap.xml are Host-header keyed (backend)

`backend/app/core/seo.py`. Start the backend with `MARKETING_HOST=askgrey.app`, then:

```bash
for h in askgrey.app www.askgrey.app lab.askgrey.app localhost; do
  echo "== $h"; curl -s -H "Host: $h" localhost:8000/robots.txt; done
curl -s -H 'Host: askgrey.app' localhost:8000/sitemap.xml
```

Expected: marketing hosts → `Allow: /` + `Disallow: /api/` + `Sitemap: https://askgrey.app/sitemap.xml`;
every other host → `Disallow: /`. Sitemap must contain exactly `/`, `/security`, `/terms` and **no**
authenticated route (`/login`, `/chat`, `/literature`, `/screening`, …). Confirm the body is real
text/XML rather than the SPA's `index.html` — a catch-all SPA route happily returns HTML with a
200 and reads as a pass.

## Per-route SEO: check the route you navigated FROM, not just the one you are on

`frontend/src/marketing/useSeo.ts` mutates `document.title`, the meta tags and
`link[rel=canonical]` in an effect. Because it is a per-page hook, **a marketing route whose
component does not call `useSeo` leaves the previous route's metadata in place**. A direct load
shows the baseline `index.html` values; a client-side nav shows the *previous* page's values.

So test both paths for every route:

1. direct load of `/<route>?site=marketing`, and
2. client-side nav from another marketing route (e.g. `/security` → `/terms`).

Asserting only the direct load, or only one route, hides the bug. Read all three at once:

```js
({title: document.title,
  desc: document.querySelector('meta[name=description]')?.content,
  canonical: document.querySelector('link[rel=canonical]')?.href,
  ogUrl: document.querySelector('meta[property="og:url"]')?.content})
```

Known shape of the defect class: `/terms` reuses the **product** `frontend/src/pages/TermsPage.tsx`,
which has no reason to know about marketing SEO and does not call `useSeo`. Any marketing route that
reuses a product page is a candidate. `grep -rl useSeo frontend/src` against the route list is the
fast check.

**The robust fix shape, and how to test it.** The durable fix is to lift the metadata into the route
table: `MarketingSite.tsx` holds a `ROUTES` array of `{path, element, title, description}` and wraps
each element in a `MarketingPage` component that calls `useSeo({title, description, path})`, with the
leaf pages no longer calling it themselves. That makes it structurally impossible for a marketing
route to ship without metadata. When a fix takes this shape, test **both navigation directions**
(`/security` → `/terms` *and* `/terms` → `/security`): a per-page hook can latch once and look fixed
in one direction, whereas a route wrapper must re-run both ways. Also assert the three canonicals are
**mutually distinct** and each equals `https://<MARKETING_HOST>` + its own path — two sitemap URLs
sharing a canonical is the duplicate-content bug the sitemap makes visible to crawlers.

Canonical strings depend on which server you use: `useSeo` builds them from
`MARKETING_ORIGIN = https://${MARKETING_HOST}`, so on the `:5174` server (`VITE_MARKETING_HOST=localhost`)
canonical is `https://localhost<path>`. Assert exact **production** canonical strings on
`:5173/?site=marketing`, where `MARKETING_HOST` keeps its default `askgrey.app`. Client-side nav
between marketing routes still works there despite `<Link>` dropping the query, because the root tree
is chosen once at mount — only `productUrl()` CTAs are affected by the dropped query.

Also assert the unknown-path fallback (`MarketingSite.tsx` has `<Route path="*" element={<Navigate to="/" replace/>} />`):
`/pricing?site=marketing` must render the homepage, not a 404 and not the product.

## Compact/mobile layout below 820px

`COMPACT_QUERY = '(max-width: 820px)'` in `frontend/src/lib/useMediaQuery.ts`. Note **768px tablet
is inside compact**, so it must show the drawer layout, not a half-desktop.

### Set the viewport over CDP, and verify matchMedia actually flipped

`Emulation.setDeviceMetricsOverride` drives `matchMedia` correctly, so the compact branch really
engages. Always read back the predicate rather than trusting the pixel size:

```js
window.matchMedia('(max-width: 820px)').matches
```

Verified mapping: `390×844 → true`, `768×1024 → true`, `1440×900 → false`.

### The drawer has four close paths — and the resize one is the real test

`AppShell.tsx`: menu button toggles `aria-label` between `Open navigation` / `Close navigation`;
the scrim is a `button[aria-label="Close navigation"]`.

Close paths to exercise: **scrim click, Escape, navigating to a tab, and resizing back above 820px**.
The resize path is the discriminating one — an implementation that merely hides the sidebar with CSS
leaves drawer state set, so after resizing to 1440 you get a drawer overlaying the desktop layout.
Likewise a CSS-only implementation fails "open the drawer" at 390px because there is nothing to open.

### Dual-pane → two tabs: assert the input survives, not just that tabs switch

`DualPaneWorkspace.tsx` renders a `role="tablist"` with two tabpanels and keeps **both children
mounted**, hiding the inactive one with the `hidden` attribute. The wrong implementation
(`{shown === 'left' && left}`) also "switches tabs" fine, so the only test that separates them is
state persistence:

1. type a **half-finished** value into the left pane (Screening's SMILES input is ideal — deterministic, no API key): `CC(C)(C)c1ccc(cc1)C(O`
2. switch to the right tab, switch back,
3. assert the input contains **exactly** that string.

Back it with a DOM check that both panels exist and the inactive one is `hidden` rather than absent:

```js
[...document.querySelectorAll('[role=tabpanel]')].map(p => ({id:p.id, hidden:p.hasAttribute('hidden')}))
```

### Measuring horizontal overflow without false positives

Page-level overflow is `documentElement.scrollWidth > innerWidth + 1`. Two traps:

- **The closed drawer is intentionally off-canvas**, so a naive "any element extending past the
  viewport" sweep reports it. Exclude descendants of `nav[aria-label="Primary"]`.
- Deliberate horizontal scroll **inside a table element** is by design; judge the page, then
  check each table separately.

The sharpest per-element clipping check is a strip whose children exceed it while it *cannot*
scroll — i.e. `overflow-x: auto` but `scrollWidth === clientWidth`, with a child rect extending
past the parent's right edge. That combination means the content is genuinely unreachable, not
just scrollable. Found exactly this on Regulatory's sub-tab strip at 390px.

**Root cause is usually the shared `Panel`, not the tab strip.** `Panel.module.css` has
`overflow: hidden` on the panel and lays out `.title` + `.actions` in the header. Without
`min-width: 0` on both, the title refuses to shrink, the actions box is sized larger than the space
left, and its `overflow-x: auto` therefore never has anything to scroll — hence
`scrollWidth === clientWidth`. The fix is a `@media (max-width: 820px)` block giving `.title`
ellipsis truncation + `min-width: 0` and `.actions` `min-width: 0`, plus `min-width: 0` on the strip.
Because `Panel` is global, **a fix here must be regression-checked on every panel whose header
carries actions** (Literature, Screening, Protocol, Grants, Assistant, Regulatory). Titles truncating
with an ellipsis is the intended trade; what must never happen is an action clipped with nothing to
scroll.

Verifying such a fix takes three steps, and only the third is conclusive:

1. the inequality flipped — `scrollWidth (362) > clientWidth (263)`;
2. a **real scroll gesture** over the strip moves `scrollLeft` > 0 and brings the far control's rect
   fully inside the strip's client rect;
3. the previously-unreachable control is then **clicked** and the UI responds (`aria-selected`
   flips, the panel title changes, the matching form becomes the unhidden one).

A reusable per-header oracle: for each header, compare every `button/a/input/select` rect against the
header's client rect and flag only controls that are *both* outside it *and* have no scrollable
ancestor. Expect zero. Note two benign results so you do not misreport them: a zero-size
`input[type=file]` behind an "Attach PDF" button is the standard hidden-input pattern, and a control
outside the header but inside a scrollable ancestor is reachable by design.

Guard the obvious regression of any sub-tab fix: Regulatory's `Slot` keeps inactive forms mounted and
toggles `hidden`, so type a partial value (Preclinical **Study id**, placeholder `TOX-2026-014`),
round-trip through another sub-tab, and assert the value is **exactly** intact. A fix that remounted
the panels would silently wipe half-entered data.

Also check the topbar identity controls (email + Sign out) fit, since they are the most commonly
clipped element at 390px.

### Marketing scroll-reveal animations

Sections carry `data-reveal`; the risk is content stuck invisible. After scrolling the whole page,
count elements still pending *and* check nothing is transparent:

```js
[...document.querySelectorAll('[data-reveal]')].map(e => ({
  revealed: e.getAttribute('data-revealed'),
  opacity: getComputedStyle(e).opacity}))
```

Expect 0 stuck-pending and 0 with opacity near 0. Screenshot each section too — the DOM numbers are
the tie-breaker, never the substitute, since a painted-but-wrong layout passes the DOM check.

**Scroll *gradually*, or you will report a false "stuck reveal".** The observer only fires for
sections that actually intersect the viewport. Pressing `End`, dragging the scrollbar, or landing
via an `#anchor` *skips over* intermediate sections, which then legitimately sit at
`opacity: 0 / translateY(12px)` with no `data-revealed`. That is **not** a defect: the observer is
not once-only and not direction-bound, so those sections reveal normally when the user scrolls
back through them (verified by scrolling up from the footer — every skipped section recovered).
Before filing a stuck reveal, re-test with many small `scroll` steps (e.g. 16 × 5 clicks with ~1s
between) and only call it a defect if a section stays transparent *after being brought into view*.
Note also that `data-reveal` keeps the literal value `pending` even once revealed — the authoritative
signal is `data-revealed === 'true'` plus computed opacity, so a probe keyed on `data-reveal` alone
reports 100% stuck and reads as a catastrophic failure.
A hero/section with `padding: 0` at phone width is invisible to overflow checks (nothing overflows,
it is just flush against both edges) — compare each block's `getBoundingClientRect().x` against the
page gutter the other sections use, e.g. 16px.

### An undefined CSS custom property voids the WHOLE shorthand — the usual root cause

The `padding: 0` class of defect above was caused by `marketing.module.css` naming
`var(--space-7)`, which `frontend/src/styles/tokens.css` does not define (the scale is
`0,1,2,3,4,5,6,8,10,12` — it jumps 6→8). One undefined `var()` makes the entire `padding`
shorthand invalid, so the element gets `0px` on all four sides rather than just losing one value.
The same typo silently zeroes `margin` shorthands, which is why a bad token can collapse grid/section
spacing at **desktop** while the visible symptom is a phone gutter.

So when you see a zeroed shorthand, grep the stylesheet for every `var(--…)` it uses and check each
name exists in `tokens.css`. And when verifying such a fix, do not stop at the one element that was
reported: check every other rule that referenced the dead token (here five `margin`s at desktop as
well as the hero `padding` at phone). Useful expected values: `--space-4 = 16px`, `--space-6 = 24px`,
`--space-8 = 32px`.

Assert the **computed shorthand string**, not just "nonzero":

```js
getComputedStyle(document.querySelector('header')).padding   // want e.g. "32px 16px 24px"
```

`src/styles/tokens.test.ts` now fails on any `var()` naming an undefined token, so this class of bug
should be caught by `npm test` going forward — but it only covers tokens, not arbitrary typos.

## Conditional Google SSO on the login screen

`/api/auth/sso` reports `google_enabled`; `LoginPage.tsx` renders the divider and the
`a[href="/api/auth/google/start"]` anchor only when true.

The trap worth testing: `backend/app/core/config.py` treats the literal string **`unset`** as a
placeholder, so `GOOGLE_CLIENT_ID=unset GOOGLE_CLIENT_SECRET=unset` must still report
`google_enabled: false`. Three states to cover:

```bash
# 1. default           -> google_enabled false, no button, no "or" divider
# 2. literal placeholder
GOOGLE_CLIENT_ID=unset GOOGLE_CLIENT_SECRET=unset ...   # -> still false, still no button
# 3. configured with fake-but-non-empty values
GOOGLE_CLIENT_ID=test-client.apps.googleusercontent.com GOOGLE_CLIENT_SECRET=test-secret ...
curl -s localhost:8000/api/auth/sso
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' localhost:8000/api/auth/google/start
```

State 3 is testable **without** any real Google credentials: the button appears, its href is exactly
`/api/auth/google/start`, and that endpoint 302s to an `accounts.google.com` URL. Check the redirect
**without following it** — the real OAuth exchange cannot and should not be completed.

Surface the error path too: `/login?sso_error=Google+sign-in+failed` must render the message in the
login form's `role="alert"` paragraph. No Google call is involved, so this is always testable.

### Two gotchas when restarting the backend for these states

- **Kill *all* uvicorn processes.** `pgrep -af "[u]vicorn app.main:app"` must return nothing before
  restarting, or an old process keeps serving the previous env and you test the wrong config.
- **Do not combine `pkill` and the relaunch in one shell command.** The `pkill` pattern can match
  the just-launched process (and the call may background/time out), leaving nothing running. Kill in
  one call, relaunch in the next, then confirm with `/api/health` and `/api/auth/sso`.

If you are already signed in, `/login` redirects to a product tab — **sign out through the UI**
before testing the login screen, or you will screenshot `/literature` and think navigation broke.

## Reveal-on-scroll vs hover: the specificity trap that silently kills hover affordances

The marketing site animates sections in with `useReveal` (`frontend/src/marketing/useReveal.ts`),
which stamps `data-reveal="pending"` then `data-revealed="true"` on a reveal root. The settled state
is written by a **descendant** selector in `marketing.module.css`:

```css
.highlight[data-revealed='true'] .highlightShot { transform: none; }  /* 0-3-0 */
.highlightShot:hover                            { transform: translateY(-4px); }  /* 0-2-0 */
```

The revealed rule outranks the hover rule, so **once a section has revealed, its hover lift can
never apply** — and the element is only hoverable *after* it has revealed. Any hover transform on a
descendant of a reveal root is suspect. A `border-color` change in the same hover rule still works,
which is what makes this easy to pass by eye: the border visibly reacts, so the hover "looks alive"
while the specified movement never happens.

**Oracle — read the computed transform, never the screenshot.** A 4px lift is near-invisible in a
screenshot, and a reduced-motion emulation left on makes it legitimately `none`:

```js
const el = document.querySelector('#literature [class*=highlightShot]');
// real mouse over it first (Input.dispatchMouseEvent / computer-use mouse_move), then:
getComputedStyle(el).transform   // 'none' => defect; 'matrix(1,0,0,1,0,-4)' => ok
```

**Confirm it is specificity and not a missing rule** before reporting, with a DOM experiment that
neutralises only the reveal attributes and re-hovers; if the lift appears, the hover rule is fine and
the revealed-state selector is the cause. Compare against a control that is *not* under a reveal root
(the hero preview shot lifts correctly) — that contrast is what makes the report actionable, and it
points at the fix: raise the hover selector's specificity or scope it under `[data-revealed]`.

## Reduced motion over CDP: the override dies with the websocket

`Emulation.setEmulatedMedia` is **per-connection**. A helper that sets the override, disconnects, and
lets a later script measure will find normal motion — pending reveals, smooth scrolling — and you will
wrongly report that reduced motion is ignored. Set the media, **reload** (the hook only takes the
reduced branch at mount), measure, and screenshot **all on one held connection**, then restore the
default and assert the normal branch returns so the rest of the run is not silently reduced-motion.

What to assert, *without scrolling*, so you prove the JS branch and not the observer: every reveal
root is `data-revealed="true"` with **no** `data-reveal="pending"`, computed `opacity` 1 and
`transform: none`, **including sections far below the fold**. Note the CSS
`@media (prefers-reduced-motion: reduce)` block only zeroes hover transforms and sets
`scroll-behavior: auto`; it does **not** force reveal opacity, so visibility depends entirely on the
`useReveal` early-return. If that branch regresses, the whole page below the fold stays at opacity 0
for reduced-motion users while the DOM still contains every word — a DOM-only check passes.

## Dark theme: measure contrast, and expect muted text to be the finding

Since the site moved to the dark `obsidian` tokens, the recurring defect class is not
white-on-white but **muted text that is merely dim**. Compute WCAG ratios rather than eyeballing:
the muted grey (`rgb(107,118,132)`) lands around **4.3:1** on the page background and ~**4.0:1** on a
card surface — above the 3:1 "is it visible" bar but below the **4.5:1** AA floor for normal-sized
text. Report those as real accessibility findings with the ratio and the class names, and check the
muted role everywhere it is reused (eyebrows, captions, notes, step indices, footer headings/legal,
and the Terms version line) — they share one token, so one fix moves all of them. Also assert each
band's background luminance is low (catches a light-theme leftover band) and that borders differ from
their surface (catches invisible borders).

## Picking the CDP target: filter by URL, and beware non-`page` targets

Helper scripts that grab `pages[0]` from `/json/list` will intermittently attach to the wrong
context — a browser extension's background page can appear in the list and shuffle the order. The
symptom is a result that parses fine but describes a different document (e.g. `location.pathname`
`"/"` and `innerWidth` 320 when the app is at `/literature` and 390 wide), which is easy to
misread as a real layout defect. Always filter the target list by the URL you expect, and if a
measurement looks impossible, re-read `location.href` and `innerWidth` in the same call before
believing it. Also note the CDP endpoint is **not** reliably IPv6-only: this box answered on
`http://127.0.0.1:29229/json/list` while `http://[::1]:29229` refused, so helpers hardcoding `[::1]`
need fixing.

## Reporting

Defects on these surfaces must name the **exact viewport and the exact element** — the same page is
fine at 1440 and broken at 390, so a defect without a viewport is not actionable.

## Per-tab product pages (`/product/<id>`) and the grouped nav

Added with the nine `/product/<id>` marketing pages (`ProductTabPage.tsx`, `tabs.ts`,
grouped `ProductMenu` in `MarketingSite.tsx`).

### Oracles that actually discriminate

- **Title vs h1 are deliberately different strings.** The route title is `` `${tab.name} — AskGrey` ``
  (short name) while the **h1 is `tab.title`** (the long claim). Asserting only one of them cannot
  catch a page that merely inherited the route's metadata — assert both.
- **Walk the pages via the next-tab card, not by typing URLs.** Clicking through
  literature → … → settings → literature proves `tabPath`, each `group`, and the modulo wrap in one
  pass; a wrong `next` index shows up as landing on the wrong page instead of hiding behind a
  URL you typed yourself.
- Expect **exactly one** pill with `aria-current="page"`; 0 or >1 is the defect signature.
- Canonicals must be asserted on a server **without** `VITE_MARKETING_HOST` (see the two-server
  section) or every one reads `https://localhost/product/<id>`.

### `.tabRail` scrolls horizontally — measure the active pill per tab AND per entry path

`.tabRail` is `overflow-x: auto` with `flex: none` pills. That internal
`scrollWidth > clientWidth` is **intended** and must not be counted as document overflow — always
measure page overflow as `documentElement.scrollWidth - clientWidth`, and separately report the
rail. At phone width the rail is ~380px visible (310px at 320) against ~888px of content, so for
later tabs (audit, settings) the active pill is only visible if something scrolls it into view.
`TabRail` now does this via `activeRef.current?.scrollIntoView({block:'nearest', inline:'center'})`
keyed on `[current.id]`.

```js
const rail = document.querySelector('nav[aria-label="Product"]');
const a = rail.querySelector('[aria-current="page"]');
const rr = rail.getBoundingClientRect(), ar = a.getBoundingClientRect();
const railRight = rr.left + rail.clientWidth;   // NOT rr.right — see below
({scrollLeft: rail.scrollLeft, maxScroll: rail.scrollWidth - rail.clientWidth,
  clippedRightPx: ar.right - railRight,
  visible: ar.left >= rr.left - 1 && ar.right <= railRight + 1,
  pageScrollY: window.scrollY})
```

Three traps that each produce a wrong verdict:

- **Use `rr.left + rail.clientWidth`, not `rr.right`, as the rail's visible right edge.** On a
  scrolled overflow container the bounding rect and the client box can disagree, which turns a
  clipped pill into a false pass.
- **Cold load, refresh, deep link and resize are separate code paths from client-side nav — test
  them explicitly (type the URL / F5 / drive the viewport), never just in-app navigation.** The
  deps are still `[current.id]`, so a cold load mounts with that id *already current* and only the
  mount-time work runs; a resize changes no id at all. Both paths once failed here while
  client-side nav passed, which is exactly what masked the bug. `TabRail` now covers them by
  calling `scrollIntoView` immediately, again on `requestAnimationFrame`, again on
  `document.fonts.ready`, and on every `window` resize (cleanup cancels the frame, removes the
  listener, guards with a `cancelled` flag). Verified green at `0eb0dd0`: cold load / typed URL /
  F5 of `/product/settings` reaches `scrollLeft` 509 of a 508 max at 390 (579/578 at 320) with
  `clippedRightPx -16`. Do **not** re-report the old 13px clip.
- **Because the fix deliberately re-fires on `rAF` and `fonts.ready`, let the page settle and
  sample twice until the value is stable.** A single early read catches a legitimate intermediate
  state and mis-reports it as a clip. Conversely, if you ever do see a shortfall, check whether it
  is stable across repeated reads before calling it a transient — `document.fonts.status` can
  already read `loaded` while layout is still settling.
- **Also assert `pageScrollY === 0` on arrival.** `block:'nearest'` can drag the page vertically as
  a side effect, which would silently undo the scroll-to-top fix below. `ScrollToDestination`'s
  effect runs *before* `TabRail`'s, so the rail call lands last and could in principle win.

Pick the tab deliberately: check **Settings (last)** and **Audit (8th)** plus **Literature (1st)**.
Early tabs fit trivially and hide any clipping; Audit clamps to the rail end so it stays visible
even when broken; only the final pill is truly exposed. Literature is the **over-correction**
control — it must stay at `scrollLeft === 0`, since a non-zero value means the rail is being
dragged when pill 1 already fits. At 1440 all nine pills fit, so assert `maxScroll === 0` **and**
`scrollLeft === 0` to catch a resize handler that scrolls the rail oddly on desktop.

### Marketing SPA route changes and the scroll-to-top / hash tension

`ScrollToDestination` in `MarketingSite.tsx` (rendered inside `MarketingChrome` above `<Routes>`)
runs on `[pathname, hash]`: if the hash names a live element it calls `target.scrollIntoView()`,
otherwise `window.scrollTo({top: 0, behavior: 'instant'})`. Before this existed, navigating from
the **bottom** of a product page kept the old `scrollY` and the destination opened at its footer.

Testing this needs both halves, because a blanket scroll-to-top passes the first and fails the
second:

1. Scroll to the **bottom** first (mandatory — from the top the defect is invisible), then navigate
   by next-tab card, footer product link **and** the desktop Product dropdown. Expect settled
   `scrollY === 0` exactly (the top branch is `instant`) and a positive on-screen `h1` rect top.
2. From a tab page click `/#product`: expect `scrollY` emphatically **> 1000**, not 0, and the
   `#product` rect top ≈ **80** — `.section/.film/.highlight/.figures` carry
   `scroll-margin-top: 80px`, so a rect top near 0 means it landed hidden under the sticky nav.

`.site` sets `scroll-behavior: smooth`, so the hash branch animates while the top branch is forced
instant. **Sample `scrollY` twice ~1s apart and only accept a stable value**, or you measure
mid-animation and mis-report.

### Phone screenshot legibility is a judgement call, so quantify it

The ≤820px rule is `width/max-width: 100%` (it replaced `width: 720px; max-width: none`, which was
the sideways-scroll bug). The images are 1280px natural, so state the **downscale factor**:
~346px rendered at 390px wide (3.7×) and ~276px at 320px (4.6×), putting embedded UI text near
3px. Report them as usable visual previews but not readable UI documentation, rather than
pass/fail.

## Chrome's address bar silently rewrites bare-host URLs

Typing `localhost:5180/` and pressing Enter can commit `localhost:5180/?site=marketing` from
history autocomplete — which inverts a host-split test into a false pass (marketing renders at the
"bare" host). Type the URL, press **Delete** to drop the inline completion, confirm the omnibox
text, *then* Enter — and verify `location.search === ''` in the assertion itself. Screenshots taken
mid-autocomplete are not valid host-split evidence.
