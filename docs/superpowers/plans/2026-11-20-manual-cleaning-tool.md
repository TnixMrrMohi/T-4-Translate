# Manual Inpainting & Healing Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide an interactive hybrid manual cleaning and healing tool (circle spot-healing brush + rectangular box selection + undo) to remove missed text, watermarks, and logos directly from the image preview in Step 3.

**Architecture:** A lightweight React `<ManualCleanOverlay>` component sits directly over the preview image / zoom modal canvas, allowing the user to paint with an adjustable circle brush or draw a bounding box. On submission, it sends the drawn binary mask / box coordinates to the FastAPI backend (`/api/jobs/{job_id}/manual-clean`), which creates a backup for undo, crops the local edit region for sub-second execution, runs inpainting with LaMa (falling back to cv2.inpaint), saves the updated `clean.png`, and invalidates render caches so the frontend immediately reflects the repaired background.

**Tech Stack:** FastAPI, Python Pillow, OpenCV (cv2), LaMa Inpainting (ONNX), React 18, TypeScript, HTML5 Canvas API, Vitest, Pytest.

**Spec:** [Design doc agreed in conversation on 2026-11-20: Spot-healing circle brush + rectangular selection box + undo + localized inpainting in Step 3 and Zoom Modal].

## Global Constraints

- Never break existing automated batch or single-page OCR and cleaning pipelines.
- Sub-second localized inpainting: always crop the bounding box of the edit with a margin before inpainting rather than processing the entire full-resolution page.
- Preserve image dimensions and color fidelity without introducing compression artifacts or blur outside the edited mask.
- Provide full undo support (`clean.png.bak`) so any accidental manual edit can be reverted instantly.
- Accessible RTL UI with Persian labels and clear visual feedback for brush cursor and painted mask overlays.

## Review Focus

1. **Large/Out-of-bounds selection:** User draws a box or brush stroke that exceeds image boundaries -> Clamped safely to `(0, 0, width, height)` without IndexError.
2. **Empty / Accidental submit:** User clicks "پاک‌سازی" with an empty mask (no pixels painted) -> Returns cleanly without modifying the image or throwing 500 error.
3. **High-DPI / Zoom scaling:** Displayed preview width/height differs from natural image resolution -> Canvas coordinates map 1:1 to natural pixel coordinates using `naturalWidth / clientWidth` ratio.
4. **Missing or initial clean.png:** Manual cleaning invoked before automated cleaning has run -> Uses `source.img` as base and generates `clean.png`.
5. **Undo without prior edit:** Calling undo when no backup exists -> Returns graceful 400 error message without crashing.

---

### Task 1: Backend Manual Cleaning & Undo Endpoints

**Files:**
- Create: `backend/tests/test_manual_clean.py`
- Modify: `backend/app/main.py:1030-1160` (or after line 1180)

**Interfaces:**
- Produces:
  - `POST /api/jobs/{job_id}/manual-clean`: Accepts `{mask_base64?: str, boxes?: list[list[int]]}`, applies inpainting to `clean.png`, backups previous image, and returns `{"ok": True, "jobId": str}`.
  - `POST /api/jobs/{job_id}/manual-clean/undo`: Restores `clean.png.bak` and returns `{"ok": True, "restored": True}`.

- [ ] **Step 1: Write failing backend tests in `backend/tests/test_manual_clean.py`**
  Cover box selection inpainting, base64 mask inpainting, undo behavior, and boundary clamping.

- [ ] **Step 2: Run backend tests to verify failure**
  Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_manual_clean.py -v`
  Expected: FAIL (404 Not Found for `/manual-clean`).

- [ ] **Step 3: Implement `manual_clean` and `manual_clean_undo` in `backend/app/main.py`**
  - Define `ManualCleanInput(BaseModel)` with optional `mask_base64` and `boxes`.
  - In `manual_clean`:
    - Resolve base image (`clean.png` if exists, else `source.img`).
    - Save backup to `clean.png.bak`.
    - Build numpy mask: if `mask_base64`, decode PNG bytes to uint8 array; if `boxes`, fill rectangles `[x0, y0, x1, y1]` with 255.
    - If mask is empty, return early with `{"ok": True, "modified": False}`.
    - Find non-zero bounding box `[min_x, min_y, max_x, max_y]`.
    - Expand bounding box by 32px padding (clamped to image dimensions).
    - Crop RGB image and mask; inpaint crop with `inpaint._tiled_fill` or fallback to `cv2.inpaint`.
    - Paste repaired crop back, save to `clean.png.tmp`, atomic replace `clean.png`.
    - Call `_drop_render(workspace)` and delete `clean-preview.png`.
  - In `manual_clean_undo`:
    - Check if `clean.png.bak` exists; if so, replace `clean.png` with backup, drop renders, return `{"ok": True}`. If not, raise HTTPException(400, "تغییری برای بازگردانی وجود ندارد.").

- [ ] **Step 4: Run backend tests to verify pass**
  Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_manual_clean.py -v`
  Expected: PASS.

- [ ] **Step 5: Commit backend changes**
  Run: `git add backend/app/main.py backend/tests/test_manual_clean.py && git commit -m "feat(backend): add manual inpainting and undo endpoints"`

---

### Task 2: Frontend Manual Clean Canvas Overlay Component

**Files:**
- Create: `frontend/src/ManualCleanOverlay.tsx`
- Create: `frontend/src/ManualCleanOverlay.test.tsx`

**Interfaces:**
- Produces:
  - `<ManualCleanOverlay />`: Interactive overlay rendering on top of image preview.
  - Props:
    ```typescript
    export interface ManualCleanOverlayProps {
      jobId: string;
      naturalWidth: number;
      naturalHeight: number;
      tool: 'brush' | 'box' | 'none';
      brushSize: number;
      disabled?: boolean;
      onCleanDone: () => void;
      onBusyChange?: (busy: boolean) => void;
    }
    ```

- [ ] **Step 1: Write failing frontend tests in `frontend/src/ManualCleanOverlay.test.tsx`**
  Test toolbar actions, drawing canvas interactions, API call to `/manual-clean` with mask or box, and clearing canvas.

- [ ] **Step 2: Run frontend test to verify failure**
  Run: `cd frontend; npm.cmd test -- src/ManualCleanOverlay.test.tsx`
  Expected: FAIL (Cannot find module).

- [ ] **Step 3: Implement `ManualCleanOverlay.tsx`**
  - Transparent HTML5 `<canvas>` positioned absolutely over image.
  - Coordinate translation from mouse client coordinates to natural image resolution.
  - Brush mode: draws smooth stroke with `rgba(239, 68, 68, 0.5)` overlay and maintains binary offscreen canvas.
  - Box mode: draws rubber-band box on drag.
  - Floating action buttons: "پاک‌سازی این بخش (ترمیم)", "پاک کردن رسم", "بازگشت (Undo)".
  - Calls `POST /api/jobs/${jobId}/manual-clean` with generated mask data URL.

- [ ] **Step 4: Run frontend test to verify pass**
  Run: `cd frontend; npm.cmd test -- src/ManualCleanOverlay.test.tsx`
  Expected: PASS.

- [ ] **Step 5: Commit component**
  Run: `git add frontend/src/ManualCleanOverlay.tsx frontend/src/ManualCleanOverlay.test.tsx && git commit -m "feat(frontend): add ManualCleanOverlay component"`

---

### Task 3: Integration into BatchPanel Step 3 & Zoom Modal

**Files:**
- Modify: `frontend/src/BatchPanel.tsx`
- Modify: `frontend/src/BatchPanel.test.tsx`
- Modify: `frontend/src/style.css`

**Interfaces:**
- Consumes: `<ManualCleanOverlay />`
- Produces: Integrated manual cleaning toolbar in Step 3 preview card and zoom modal, styling for brush cursor, toolbar pills, and responsive layout.

- [ ] **Step 1: Write integration tests in `frontend/src/BatchPanel.test.tsx`**
  Test opening the manual cleaning tools (brush, box selection, undo) in Step 3 and triggering manual repair.

- [ ] **Step 2: Run tests to verify failure**
  Run: `cd frontend; npm.cmd test -- src/BatchPanel.test.tsx`
  Expected: FAIL for new toolbar controls.

- [ ] **Step 3: Update `BatchPanel.tsx` and `style.css`**
  - Add manual tool state (`manualTool: 'brush' | 'box' | 'none'`, `brushSize: number`).
  - Render toolbar controls above image preview:
    - Button `🖌️ قلم‌موی ترمیم`
    - Button `🔲 کادر انتخابی`
    - Brush size slider (10 to 100px) when brush is active
    - Button `↩️ بازگشت (Undo)`
  - Render `<ManualCleanOverlay>` inside the preview frame when a tool is active.
  - Also provide access inside the Zoom modal.
  - Add styles in `style.css` for custom cursor and toolbar pills.

- [ ] **Step 4: Run all frontend tests to verify pass**
  Run: `cd frontend; npm.cmd test`
  Expected: PASS (all tests passing).

- [ ] **Step 5: Commit integration**
  Run: `git add frontend/src/BatchPanel.tsx frontend/src/BatchPanel.test.tsx frontend/src/style.css && git commit -m "feat(batch): integrate manual healing brush and box tool into Step 3"`

---

### Task 4: End-to-End Verification & Sanity Check

- [ ] **Step 1: Run full backend and frontend test suites**
  Verify zero regressions across backend and frontend.
- [ ] **Step 2: Test live server functionality**
  Verify the tool is active in browser on http://127.0.0.1:5173.
