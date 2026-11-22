# Project Chapters Architecture & Multi-Chapter Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a hierarchical Manga/Manhwa Series Project structure with multi-chapter management, allowing users to manage long-running series with dozens or hundreds of chapters under a single project, seamlessly switch between chapters, and create new chapters without creating separate top-level projects.

**Architecture:**
1. **Backend Project & Chapter Engine (`backend/app/projects.py` & `backend/app/main.py`)**:
   - Projects represent a Series / Manga (e.g. `Shadow Slayer`).
   - Under each project directory `~/.t4-translate/projects/{project_id}/`:
     - `project.json`: Series metadata, active chapter pointer (`activeChapterId`), and chapter catalog summary.
     - `chapters/{chapter_id}.json`: Dedicated isolated persistence file for each chapter's pages, step, translations, and outFiles.
   - Backward Compatibility: Existing single-chapter projects automatically migrate into Chapter 1 (`chap_01`) seamlessly on first access without data loss.
   - RESTful API for chapter operations: list chapters, create chapter, get chapter, save chapter state, delete chapter, and set active chapter.
2. **Frontend Multi-Chapter UI Integration (`frontend/src/BatchPanel.tsx`, `frontend/src/ProjectManagerModal.tsx`, `frontend/src/ChapterCreateModal.tsx`, `frontend/src/style.css`)**:
   - In `BatchPanel`'s project bar: display project name with an active chapter selector dropdown and a quick `+ افزودن چپتر جدید` button.
   - Fast in-memory & disk switching between chapters with auto-save barrier protection.
   - Quick "New Chapter Modal" with auto-incremented chapter number suggestion and native folder picker integration.
   - In `ProjectManagerModal`: show series with chapter counts, expandable chapter breakdown, and direct jump to any chapter.

**Tech Stack:**
- Backend: Python 3.12, FastAPI, Pydantic, pathlib
- Frontend: React 18, TypeScript, Vite, CSS3 (RTL-first)
- Tests: pytest (backend), vitest & React Testing Library (frontend)

---

## Global Constraints

- Storage root respects `T4_DATA_DIR` environment variable, defaulting to `~/.t4-translate`.
- All disk file operations are atomic (`.tmp` write followed by `replace`) to prevent corruption.
- Backward compatibility: existing manifests with root `pages` and `translated` must never lose data.
- UI must follow standard Persian RTL typography and styling.

---

### Task 1: Backend Chapter Persistence & Migration Logic

**Files:**
- Modify: `backend/app/projects.py`
- Test: `backend/tests/test_projects.py`

**Interfaces:**
- `ProjectManager`:
  - `list_chapters(project_id: str) -> List[dict]`
  - `create_chapter(project_id: str, name: Optional[str] = None, chapter_number: Optional[int] = None, source_path: Optional[str] = None, source_mode: str = "internal") -> dict`
  - `get_chapter(project_id: str, chapter_id: str) -> Optional[dict]`
  - `save_chapter_state(project_id: str, chapter_id: str, state: dict) -> Optional[dict]`
  - `delete_chapter(project_id: str, chapter_id: str) -> bool`
  - `set_active_chapter(project_id: str, chapter_id: str) -> Optional[dict]`
  - Auto-migration of legacy project format into `chapters/chap_01.json`.

- [ ] **Step 1: Write unit tests in `test_projects.py` for chapter CRUD and legacy migration**
- [ ] **Step 2: Run pytest to verify test failure**
- [ ] **Step 3: Implement chapter methods in `backend/app/projects.py`**
- [ ] **Step 4: Run pytest to verify test pass**

---

### Task 2: Backend API Endpoints for Chapters

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_projects.py`

**Interfaces:**
- Endpoints:
  - `GET /api/projects/{project_id}/chapters`
  - `POST /api/projects/{project_id}/chapters`
  - `GET /api/projects/{project_id}/chapters/{chapter_id}`
  - `POST /api/projects/{project_id}/chapters/{chapter_id}/save-state`
  - `POST /api/projects/{project_id}/chapters/{chapter_id}/activate`
  - `DELETE /api/projects/{project_id}/chapters/{chapter_id}`

- [ ] **Step 1: Write API tests in `test_projects.py` for FastAPI chapter endpoints**
- [ ] **Step 2: Run pytest to verify test failure**
- [ ] **Step 3: Register chapter endpoints in `backend/app/main.py`**
- [ ] **Step 4: Run pytest to verify test pass**

---

### Task 3: Frontend Chapter Switcher & Creation Modal in BatchPanel

**Files:**
- Create: `frontend/src/ChapterCreateModal.tsx`
- Modify: `frontend/src/BatchPanel.tsx`
- Modify: `frontend/src/style.css`
- Test: `frontend/src/BatchPanel.test.tsx`

**Deliverables:**
- Chapter dropdown in `batch-project-bar` showing current chapter, status badge, and total pages.
- Fast switching between chapters with clean state reset and auto-save protection.
- Quick `+ چپتر جدید` button opening `ChapterCreateModal`.

- [ ] **Step 1: Create `ChapterCreateModal.tsx` for adding new chapters**
- [ ] **Step 2: Integrate chapter selector and switcher in `BatchPanel.tsx`**
- [ ] **Step 3: Add CSS styles in `style.css` for chapter dropdown and buttons**
- [ ] **Step 4: Run frontend tests to verify stability**

---

### Task 4: Series & Chapter Hierarchy in ProjectManagerModal

**Files:**
- Modify: `frontend/src/ProjectManagerModal.tsx`
- Test: `frontend/src/ProjectManagerModal.test.tsx`

**Deliverables:**
- Display series project cards with chapter count, active chapter indicator, and expandable chapter list.
- Allow opening any chapter directly or creating a chapter from the modal.

- [ ] **Step 1: Update `ProjectManagerModal.tsx` to display chapters list under each project**
- [ ] **Step 2: Update tests in `ProjectManagerModal.test.tsx`**
- [ ] **Step 3: Run vitest to ensure all tests pass**

---

### Task 5: End-to-End Verification & Real Project Migration

- [ ] **Step 1: Verify existing project `proj_099ee23077` (Shadow Slayer) migrates cleanly to Chapter 1**
- [ ] **Step 2: Verify adding Chapter 2, switching between Chapter 1 and 2, and disk persistence**
- [ ] **Step 3: Run full backend and frontend test suites**
