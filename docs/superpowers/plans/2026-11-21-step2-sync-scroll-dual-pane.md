# Step 2 Synchronized Scroll & Dual-Pane Full-Width View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a dual-pane, side-by-side synchronized scroll view in Step 2 (translation) with a collapsible right sidebar to maximize screen real estate, bidirectional scroll synchronization between images and text, and manual sync toggles.

**Architecture:**
1. **Collapsible Sidebar & Full-Width Layout (`frontend/src/BatchPanel.tsx`, `frontend/src/style.css`)**:
   - Add `sidebarCollapsed` state in `BatchPanel.tsx` (auto-collapsed or toggleable in Step 2 with button `📐 تمام‌صفحه / ستون مراحل`).
   - Add `.layout.sidebar-collapsed` CSS (`grid-template-columns: 1fr; max-width: 100%;`).
   - Add compact breadcrumb/step navigator when sidebar is collapsed so user can switch steps without expanding sidebar.
2. **Side-by-Side Dual-Pane Container in Step 2 (`frontend/src/BatchPanel.tsx`)**:
   - Right/First Pane: Continuous Image Stream with page headers (`batch-stream-item`), lazy loading, and `ref` per page.
   - Left/Second Pane: Persian translation textarea + English extracted text textarea with calculated scroll mapping.
3. **Two-Way Scroll Synchronization Engine (`frontend/src/BatchPanel.tsx`)**:
   - Parse page markers `=== 00X | filename ===` in English and Persian text to find character and line positions.
   - Scrolling image pane -> finds active page index -> scrolls textareas smoothly to `=== 00X ===`.
   - Scrolling textarea -> finds current page header in view -> scrolls image pane smoothly to corresponding image.
   - Guard against circular scroll loops (`isSyncingRef` lock).
   - Toggle button: `🔗 اسکرول همگام (فعال / غیرفعال)`.

**Tech Stack:** React 18, TypeScript, CSS Grid/Flexbox, Vitest, React Testing Library.

---

### Task 1: CSS Styles for Collapsed Sidebar & Step 2 Dual-Pane

**Files:**
- Modify: `frontend/src/style.css`

- [ ] **Step 1: Add `.layout.sidebar-collapsed`, `.step2-split-container`, `.step2-pane`, `.sync-scroll-toggle` in `frontend/src/style.css`**
  - Support side-by-side 50/50 split on desktop (`min-height: calc(100vh - 220px)`).
  - Responsive fallback for smaller screens.

---

### Task 2: Page Header Indexing & Scroll Position Helpers

**Files:**
- Create/Modify: `frontend/src/scrollSync.ts`
- Create/Modify: `frontend/src/scrollSync.test.ts`

- [ ] **Step 1: Write unit tests for page header position calculation and active page detection**
- [ ] **Step 2: Run vitest to verify test failure**
- [ ] **Step 3: Implement `findPageOffsets(text: string): Map<number, number>` and `getActivePageFromScroll` in `scrollSync.ts`**
- [ ] **Step 4: Run vitest to verify test pass**

---

### Task 3: Integrate Dual-Pane & Synchronized Scrolling in BatchPanel

**Files:**
- Modify: `frontend/src/BatchPanel.tsx`
- Modify: `frontend/src/BatchPanel.test.tsx`

- [ ] **Step 1: Write test for sidebar collapse toggle and synchronized scrolling toggle in `BatchPanel.test.tsx`**
- [ ] **Step 2: Run vitest to verify test failure**
- [ ] **Step 3: Implement collapsible sidebar, dual-pane layout, and two-way scroll synchronization in `BatchPanel.tsx`**
- [ ] **Step 4: Run vitest to verify test pass**

---

### Task 4: Full Verification & Build

- [ ] **Step 1: Run full test suite: `npm.cmd --prefix frontend test`**
- [ ] **Step 2: Run TypeScript build: `npm.cmd --prefix frontend run build`**
- [ ] **Step 3: Ensure backend and frontend servers are healthy**
