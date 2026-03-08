# Research: TanStack Start for Local EEG Dashboard

**Date:** 2026-03-08
**Sources:** 15+ sources (key ones listed below)

---

## Executive Summary

TanStack Start is a full-stack React framework at **Release Candidate v1.154.0**, built on Vite and TanStack Router [1]. It has **first-class Convex integration** via `@convex-dev/react-query` with official quickstart guides and examples [2]. For this project, it's a reasonable but not optimal choice. The key value-add over plain Vite+React is type-safe file-based routing, server functions, and the Convex integration pattern — but for a single-page dashboard with no SSR needs, most of Start's features go unused. The SPA mode exists as a first-class feature, which means you can disable SSR entirely [3]. The honest recommendation: **TanStack Start is fine if you want to learn it, but plain Vite+React+TanStack Router would give you the same DX with less framework overhead.**

---

## Key Findings

### 1. Current State & Maturity

TanStack Start reached RC status in late 2025 and is currently at v1.154.0 [1]. The API is considered stable and feature-complete, with 1.0 expected imminently. The framework migrated from Vinxi to Vite in v1.121.0 (June 2025), which was a significant architectural change that improved stability [4]. A memory leak issue (#5734) was resolved in January 2026 [4].

Production deployments exist (Cloudflare Workers validated), but the RC status means you should pin dependencies. Code-based routing has had critical build issues — file-based routing is more reliable [5]. The community is growing but smaller than Next.js; documentation is decent but has gaps for advanced patterns [6].

### 2. Architecture

TanStack Start is built on three layers:

- **Vite** — Build tool, dev server, HMR, plugin ecosystem
- **TanStack Router** — Type-safe file-based routing, nested layouts, search param validation, code splitting
- **Server layer** — Server functions (RPC with SHA256-hashed IDs), server routes (API endpoints), SSR/streaming

For a local dashboard, you'd primarily use the Router layer. Server functions could be useful if you want to call your Python backend from server-side code, but for WebSocket streaming that's irrelevant — the browser connects directly [7].

**SPA mode** is a documented first-class feature that disables SSR entirely, making Start behave like a Vite SPA with better routing. This is the mode you'd use [3].

### 3. Convex Integration — First Class

This is where TanStack Start genuinely shines for your use case. Convex has official TanStack Start support with:

- Dedicated quickstart: `npm create convex@latest -- -t tanstack-start` [2]
- `@convex-dev/react-query` package providing live-updating queries via TanStack Query hooks
- `useSuspenseQuery(convexQuery(api.sessions.list, {}))` — reactive, type-safe, auto-invalidating
- Server-side rendering of Convex queries with consistent timestamps [2]
- Example apps: Trellaux (Trello clone), Better Auth integration [8]

The integration pattern is clean: create a `ConvexClient` and `ConvexQueryClient` in your router config, wrap with `ConvexProvider`, and use standard TanStack Query hooks everywhere. Mutations work via `useMutation(convexQuery(...))` [2].

### 4. What Start Gives You Over Plain Vite+React

| Feature | Vite+React | Vite+React+TanStack Router | TanStack Start |
|---------|------------|---------------------------|----------------|
| HMR/dev server | Yes | Yes | Yes |
| Type-safe routing | No | Yes | Yes |
| File-based routes | No | Yes | Yes |
| Search param validation | No | Yes | Yes |
| Code splitting (auto) | Manual | Yes | Yes |
| Server functions (RPC) | No | No | Yes |
| SSR/streaming | No | No | Yes |
| SPA mode | Default | Default | Opt-in |
| Convex integration | Manual | Manual | Official template |

For your dashboard, the relevant features are type-safe routing and the Convex integration pattern. You could get these with just `Vite + TanStack Router + @convex-dev/react-query` without the full Start framework.

### 5. For the EEG Dashboard Specifically

**What Start helps with:**
- File-based routing if the dashboard grows beyond one page (settings, session history, experiment configs)
- Convex integration is plug-and-play
- Type-safe route params (e.g., `/session/:id` for viewing recorded sessions)
- The project template gives you a clean starting structure

**What Start doesn't help with:**
- WebSocket streaming — this is browser-direct, framework-agnostic
- Real-time charting — this is a React component concern, not a framework concern
- High-frequency data handling — no framework feature addresses 256Hz data pipelines
- Signal processing — all in Python/BrainFlow

**Risk factors:**
- Still RC, not 1.0 — API could have minor changes
- Code-based routing has had build issues [5]
- Smaller community means fewer StackOverflow answers when stuck
- The Vinxi→Vite migration was recent; edge cases may remain

### 6. The Honest Take

TanStack Start is a good framework that happens to be slightly overqualified for a local single-page dashboard. The main value propositions — SSR, streaming hydration, server functions, deployment flexibility — are irrelevant when you're running `localhost` and streaming EEG over a raw WebSocket.

**However**, if you plan to:
- Add multiple pages (session history, experiment library, settings)
- Use Convex as your data layer
- Potentially make this a shareable tool later

Then Start gives you a clean foundation that won't need replacing. The SPA mode means you're not paying for SSR overhead, and the Convex template gets you running in minutes.

**If you just want the fastest path to a working dashboard**, `Vite + React + TanStack Router` (without Start) gives you 90% of the benefit with less framework surface area.

---

## Recommendation for This Project

**Use TanStack Start in SPA mode.** The reasoning:

1. You're already planning to use Convex — the official integration template saves setup time
2. The dashboard will likely grow beyond one page (session history, experiment configs, ZUNA results)
3. TanStack Router's type-safe routing is genuinely useful and comes free with Start
4. SPA mode means no SSR overhead
5. The framework is Vite under the hood, so you're not sacrificing dev speed
6. If Start turns out to be friction, dropping down to Vite+Router is a minor refactor

The alternative (plain Vite+React) is also fine. This is a low-stakes framework choice since the hard work is in the WebSocket pipeline and charting components, not the app shell.

---

## Sources

[1] TanStack. "TanStack Start v1 Release Candidate." https://tanstack.com/blog/announcing-tanstack-start-v1
[2] Convex. "TanStack Start Quickstart." https://docs.convex.dev/quickstart/tanstack-start
[3] TanStack. "SPA Mode Guide." https://tanstack.com/start/latest/docs/framework/react/guide/spa-mode
[4] DEV Community. "ReactJS Day 2025: TanStack Start Real World Experiences." https://dev.to/this-is-learning/reactjs-day-2025-tanstack-start-real-world-experiences-16b9
[5] GitHub. "Start: TanStack Start + Code Based Routing not working #5808." https://github.com/TanStack/router/issues/5808
[6] CodeWithSeb. "TanStack in 2026: From Query to Full-Stack." https://www.codewithseb.com/blog/tanstack-ecosystem-complete-guide-2026
[7] TanStack. "Server Functions Guide." https://tanstack.com/start/latest/docs/framework/react/guide/server-functions
[8] TanStack. "Start Convex Trellaux Example." https://tanstack.com/start/latest/docs/framework/react/examples/start-convex-trellaux
[9] Convex. "TanStack Start Integration." https://docs.convex.dev/client/tanstack/tanstack-start/
[10] BeyondIT. "Next.js 16 vs TanStack Start Data Comparison." https://beyondit.blog/blogs/nextjs-16-vs-tanstack-start-data-comparison
[11] TanStack. "TanStack Start Overview." https://tanstack.com/start/latest/docs/framework/react/overview
[12] GitHub. "When is TanStack Start stable release planned? #5999." https://github.com/TanStack/router/discussions/5999
[13] InfoQ. "TanStack Start: A New Meta Framework Powered by React or SolidJS." https://www.infoq.com/news/2025/11/tanstack-start-v1/
