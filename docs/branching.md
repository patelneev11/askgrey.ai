# Branching

`main` is the only long-lived branch. Everything else is a short-lived branch that is opened,
reviewed, merged and deleted; nothing is meant to sit unmerged for days.

## Names carry the structure

A branch is named `<area>/<change>`, where the area is the part of the product it belongs to —
one per tab, plus two for work that isn't a tab:

| Area | Covers |
| --- | --- |
| `literature/` | Literature tab, PubMed/PDF ingestion, citations, review table |
| `screening/` | Screening tab, compound descriptors, SAR, ADMET, patents |
| `protocol/` | Protocol tab, drafting, calculators, ELN history |
| `regulatory/` | Regulatory tab, guidance sources, preclinical checklist, IND assembly |
| `grants/` | Grants tab, opportunity matching, eligibility, budgets |
| `review/` | Cross-cutting review board and audit trail |
| `platform/` | Auth, deployment, monitoring, design system, shared services |
| `chore/` | Dependency bumps, tooling, agent skills |

So the grouping the repository listing shows is the grouping of the product:

```
main
├── grants/api
├── grants/frontend
├── literature/persistence-api
├── screening/sar-service
└── platform/deploy-readiness
```

Git has no real subdirectories for branches — the `/` is only a name — so this is a convention,
not something the tool enforces. That is the point: it costs nothing and it can't drift.

## Why there is no long-lived branch per tab

A permanent `literature` branch that features merge into, and which merges to `main`
periodically, looks tidier in a diagram and behaves worse:

- Its diff against `main` grows without bound, so the eventual merge is the largest and least
  reviewable change in the history, made at the moment everyone has forgotten the code.
- CI on a feature branch proves it works against the tab branch, not against what is deployed.
  Integration failures surface at the tab merge instead of at the feature merge.
- Two tabs that touch the same shared file (the export service, the design tokens, the nav
  shell — all of which are shared here) conflict twice: once in the feature branch and again in
  the tab merge.
- `main` stops describing the product, because finished work is parked one level away from it.

The problem those branches are meant to solve — knowing what belongs together — is a *naming*
problem, and the table above solves it without deferring any merge.

## Rules

1. Branch from `main`, and rebase on `main` rather than merging `main` into the branch.
2. One reviewable change per PR. If the backend service and the tab that consumes it are both
   large, ship the service first with its own tests, then the UI.
3. Stack only within an area, and only when the second PR genuinely cannot compile without the
   first. A stacked PR's base is the branch below it; merge bottom-up. Never stack across areas —
   `review/board-ui` waiting on `grants/frontend` means neither can land alone.
4. Delete the branch when the PR merges (the repository setting does this automatically).
5. Don't reuse a merged branch for follow-up work; open a new one.

## Renaming an existing branch

Rename through GitHub (**Settings → Branches**, or
`gh api -X POST repos/<owner>/<repo>/branches/<old>/rename -f new_name=<new>`) rather than
pushing a new name and deleting the old one. GitHub moves any open pull request and retargets
PRs stacked on top of it; a push-and-delete closes the pull request and loses its review history.
