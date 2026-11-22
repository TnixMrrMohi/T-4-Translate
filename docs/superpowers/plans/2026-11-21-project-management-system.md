# Project Management & Local Disk Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a robust, disk-persisted Project Management System for T-4 Translate supporting project creation, local folder ingestion and drag-and-drop, crash-resilient auto-saving, resume-from-any-step, and high-scale batch processing (supporting hundreds to thousands of images across chapters).

**Architecture:** 
1. **Backend Project Engine (`backend/app/projects.py` & `backend/app/main.py`)**:
   - Manage projects under `~/.t4-translate/projects/{project_id}/`.
   - Each project has an atomic `project.json` metadata and state manifest.
   - Support both `folder` mode (direct ingestion from local directory on host without copying) and `internal` mode (drag-and-drop uploaded files saved to `projects/{project_id}/sources/`).
   - Project CRUD API: list, create, get, auto-save state, scan local folder, and delete (with full disk resource cleanup).
2. **Frontend Project Dashboard & Integration (`frontend/src/ProjectManager.tsx`, `frontend/src/BatchPanel.tsx`, `frontend/src/App.tsx`)**:
   - Sleek Project Manager Modal / View: New Project, Recent Projects list with progress indicators, disk usage, resume button, and deletion confirmation.
   - In `BatchPanel`, sync state bidirectionally with active project: auto-save on OCR progress, translation typing, and step transitions.
   - Resume capability: load existing project manifest and populate steps 1-4 immediately without re-uploading or re-running completed OCR.

**Tech Stack:** 
- Backend: Python 3.12, FastAPI, Pydantic, pathlib, aiofiles
- Frontend: React 18, TypeScript, Vite, CSS3 (RTL-first design)
- Tests: pytest (backend), vitest & React Testing Library (frontend)

---

## Global Constraints

- Storage root respects `T4_DATA_DIR` environment variable, defaulting to `~/.t4-translate`.
- All disk file operations must be atomic (e.g. writing `project.json.tmp` then renaming) to prevent corruption during sudden power loss.
- Batch processing must support interrupted workflows: completed pages (`state: 'done'`) must never re-run OCR when resumed.
- Persian UI / UX with standard RTL typography and accessible keyboard controls.

## Review Focus

1. Sudden crash / restart while halfway through Step 2 (OCR or translation text input) restores exact translated text and page states.
2. Ingesting a local directory with subfolders or mixed image extensions (`.png`, `.jpg`, `.jpeg`, `.webp`) sorts natural alphanumeric order and ignores non-images.
3. Deleting a project cleanly removes all related jobs, slices, and files from disk without leaving orphaned directories.
4. Auto-save in frontend uses debouncing (500ms-1s) to avoid spamming the backend while user types translation.
5. Large batch handling: UI smoothly lists pages without freezing even when 500+ pages are present.

---

### Task 1: Backend Project Storage & Manifest Schema

**Files:**
- Create: `backend/app/projects.py`
- Test: `backend/tests/test_projects.py`

**Interfaces:**
- Consumes: `T4_DATA_DIR`, `Path.home()`
- Produces: `ProjectManager` class with:
  - `list_projects() -> List[dict]`
  - `create_project(name: str, source_path: Optional[str] = None) -> dict`
  - `get_project(project_id: str) -> dict`
  - `save_project_state(project_id: str, state: dict) -> dict`
  - `delete_project(project_id: str) -> bool`
  - `scan_local_folder(path: str) -> List[dict]`

- [ ] **Step 1: Write failing backend test for ProjectManager**
  Write unit tests verifying project creation, state saving with atomic file replacement, local folder scanning, and deletion.

- [ ] **Step 2: Run pytest to verify test failure**
  Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_projects.py`

- [ ] **Step 3: Implement `backend/app/projects.py`**
  Implement `ProjectManager` with Pydantic models for project metadata, atomic JSON writes (`json.dump` to `.tmp` then `replace`), directory scanning for images, and project deletion.

- [ ] **Step 4: Run pytest to verify test pass**
  Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_projects.py`

---

### Task 2: Backend API Endpoints for Projects

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_projects.py`

**Interfaces:**
- Endpoints:
  - `GET /api/projects`
  - `POST /api/projects` (body: `{name, source_path}`)
  - `GET /api/projects/{project_id}`
  - `POST /api/projects/{project_id}/save-state`
  - `DELETE /api/projects/{project_id}`
  - `POST /api/projects/scan-folder` (body: `{path}`)

- [ ] **Step 1: Write integration tests in `test_projects.py` for FastAPI endpoints**
  Test creating a project via `TestClient`, getting it, saving state, listing projects, and deleting it.

- [ ] **Step 2: Run pytest to verify test failure**
  Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_projects.py`

- [ ] **Step 3: Register project routes in `backend/app/main.py`**
  Integrate `ProjectManager` into `main.py` and mount the endpoints.

- [ ] **Step 4: Run pytest to verify test pass**
  Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_projects.py`

---

### Task 3: Frontend Project Manager Component & Dialog

**Files:**
- Create: `frontend/src/ProjectManagerModal.tsx`
- Create: `frontend/src/ProjectManagerModal.test.tsx`
- Modify: `frontend/src/style.css`

**Interfaces:**
- Props:
  - `open: boolean`
  - `activeProjectId?: string`
  - `onSelectProject: (projectId: string) => void`
  - `onClose: () => void`

- [ ] **Step 1: Write unit tests for `ProjectManagerModal`**
  Verify listing recent projects, creating a new project (by name and path/mode), selecting an existing project, and deleting a project.

- [ ] **Step 2: Run vitest to verify test failure**
  Run: `npm.cmd --prefix frontend test -- src/ProjectManagerModal.test.tsx`

- [ ] **Step 3: Implement `ProjectManagerModal.tsx` and CSS styles**
  Build the project dashboard modal with tabs/sections for "پروژه‌های اخیر" (Recent Projects) and "پروژه جدید" (New Project: choice between local folder path or upload).

- [ ] **Step 4: Run vitest to verify test pass**
  Run: `npm.cmd --prefix frontend test -- src/ProjectManagerModal.test.tsx`

---

### Task 4: Integrate Project State & Auto-Save in BatchPanel

**Files:**
- Modify: `frontend/src/BatchPanel.tsx`
- Modify: `frontend/src/BatchPanel.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Sync `BatchPanel` state (`batchStep`, `pages`, `translated`, `outFiles`) with active project.
- Debounced auto-save hook to `/api/projects/{project_id}/save-state`.
- On loading a project, initialize `pages`, `translated`, `batchStep` from project manifest so user resumes seamlessly.
- Header button to switch / open projects and show auto-save status pill (`ذخیره‌شده در پروژه X`).

- [ ] **Step 1: Write test for BatchPanel project resumption and auto-save**
  Verify that when an `initialProject` or `projectId` is passed, `BatchPanel` restores the saved pages and translated text.

- [ ] **Step 2: Run vitest to verify test failure**
  Run: `npm.cmd --prefix frontend test -- src/BatchPanel.test.tsx`

- [ ] **Step 3: Implement project persistence & resume logic in `BatchPanel.tsx` and header in `App.tsx`**
  Connect `ProjectManagerModal`, auto-save on state updates, and load existing projects.

- [ ] **Step 4: Run all frontend tests and build**
  Run: `npm.cmd --prefix frontend test && npm.cmd --prefix frontend run build`

---

### Task 5: End-to-End Verification & Server Restart

**Files:**
- Verification across backend and frontend servers

- [ ] **Step 1: Run full test suites**
  - Backend: `pytest`
  - Frontend: `vitest run`
- [ ] **Step 2: Restart backend and frontend background daemons**
- [ ] **Step 3: Test live endpoints with curl**
