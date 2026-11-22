import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def natural_sort_key(s: str) -> List[Any]:
    """Clustering digits and letters for human natural sorting (e.g. 1, 2, 10)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]


IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff'}


class ProjectManager:
    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            raw_dir = os.environ.get("T4_DATA_DIR")
            self.data_dir = Path(raw_dir) if raw_dir else Path.home() / ".t4-translate"
        else:
            self.data_dir = Path(data_dir)
        self.projects_dir = self.data_dir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def _get_project_dir(self, project_id: str) -> Path:
        return self.projects_dir / project_id

    def _get_manifest_path(self, project_id: str) -> Path:
        return self._get_project_dir(project_id) / "project.json"

    def _get_chapters_dir(self, project_id: str) -> Path:
        return self._get_project_dir(project_id) / "chapters"

    def _get_chapter_path(self, project_id: str, chapter_id: str) -> Path:
        return self._get_chapters_dir(project_id) / f"{chapter_id}.json"

    def _atomic_write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)

    def _compute_dir_size_mb(self, path: Path) -> float:
        if not path.exists():
            return 0.0
        total_bytes = 0
        try:
            for entry in path.rglob("*"):
                if entry.is_file():
                    total_bytes += entry.stat().st_size
        except Exception:
            pass
        return round(total_bytes / (1024 * 1024), 2)

    def _migrate_legacy_project_if_needed(self, manifest: dict) -> dict:
        """ارتقای خودکار پروژه‌های قدیمی تک‌فصل به ساختار چندچپتری بدون از دست رفتن هیچ داده‌ای."""
        project_id = manifest.get("id", "")
        chapters = manifest.get("chapters")
        if isinstance(chapters, list) and len(chapters) > 0 and manifest.get("activeChapterId"):
            return manifest

        chapters_dir = self._get_chapters_dir(project_id)
        chapters_dir.mkdir(parents=True, exist_ok=True)

        now_iso = datetime.now(timezone.utc).isoformat()
        ch_id = manifest.get("activeChapterId") or "chap_01"
        ch_path = self._get_chapter_path(project_id, ch_id)

        pages = manifest.get("pages", [])
        done_count = sum(1 for p in pages if p.get("state") == "done")

        if not ch_path.exists():
            ch_data = {
                "id": ch_id,
                "projectId": project_id,
                "chapterNumber": 1,
                "name": "چپتر ۱",
                "createdAt": manifest.get("createdAt", now_iso),
                "updatedAt": manifest.get("updatedAt", now_iso),
                "step": manifest.get("step", 1),
                "sourceMode": manifest.get("sourceMode", "internal"),
                "sourcePath": manifest.get("sourcePath"),
                "pages": pages,
                "outFiles": manifest.get("outFiles", []),
                "translated": manifest.get("translated", ""),
                "settings": manifest.get("settings", {
                    "promoAction": "replace",
                    "filterSlanted": True,
                    "quality": 90,
                }),
            }
            self._atomic_write_json(ch_path, ch_data)

        ch_summary = {
            "id": ch_id,
            "chapterNumber": 1,
            "name": "چپتر ۱",
            "createdAt": manifest.get("createdAt", now_iso),
            "updatedAt": manifest.get("updatedAt", now_iso),
            "step": manifest.get("step", 1),
            "totalPages": len(pages),
            "donePages": done_count,
            "sourceMode": manifest.get("sourceMode", "internal"),
            "sourcePath": manifest.get("sourcePath"),
        }

        manifest["chapters"] = [ch_summary]
        manifest["activeChapterId"] = ch_id
        self._atomic_write_json(self._get_manifest_path(project_id), manifest)
        return manifest

    def list_projects(self) -> List[Dict[str, Any]]:
        results = []
        if not self.projects_dir.exists():
            return results

        for child in self.projects_dir.iterdir():
            if child.is_dir():
                manifest_file = child / "project.json"
                if manifest_file.exists():
                    try:
                        proj = self.get_project(child.name)
                        if not proj:
                            continue
                        chapters = proj.get("chapters", [])
                        total_pages = proj.get("totalPages", len(proj.get("pages", [])))
                        done_pages = proj.get("donePages", sum(1 for p in proj.get("pages", []) if p.get("state") == "done"))
                        results.append({
                            "id": proj.get("id", child.name),
                            "name": proj.get("name", child.name),
                            "createdAt": proj.get("createdAt", ""),
                            "updatedAt": proj.get("updatedAt", ""),
                            "step": proj.get("step", 1),
                            "activeChapterId": proj.get("activeChapterId"),
                            "chapterName": proj.get("chapterName", "چپتر ۱"),
                            "chapterNumber": proj.get("chapterNumber", 1),
                            "totalChapters": len(chapters),
                            "totalPages": total_pages,
                            "donePages": done_pages,
                            "sourceMode": proj.get("sourceMode", "internal"),
                            "sourcePath": proj.get("sourcePath"),
                            "diskSizeMb": self._compute_dir_size_mb(child),
                        })
                    except Exception:
                        continue

        # Sort newest first
        results.sort(key=lambda x: x.get("updatedAt", ""), reverse=True)
        return results

    def create_project(
        self,
        name: str,
        source_path: Optional[str] = None,
        source_mode: str = "internal",
        settings: Optional[dict] = None,
    ) -> Dict[str, Any]:
        project_id = f"proj_{uuid.uuid4().hex[:10]}"
        proj_dir = self._get_project_dir(project_id)
        proj_dir.mkdir(parents=True, exist_ok=True)
        chapters_dir = self._get_chapters_dir(project_id)
        chapters_dir.mkdir(parents=True, exist_ok=True)

        now_iso = datetime.now(timezone.utc).isoformat()
        resolved_source_path = None
        if source_path:
            p = Path(source_path).resolve()
            if p.exists() and p.is_dir():
                resolved_source_path = str(p)
                source_mode = "folder"

        ch_id = "chap_01"
        ch_data = {
            "id": ch_id,
            "projectId": project_id,
            "chapterNumber": 1,
            "name": "چپتر ۱",
            "createdAt": now_iso,
            "updatedAt": now_iso,
            "step": 1,
            "sourceMode": source_mode,
            "sourcePath": resolved_source_path,
            "pages": [],
            "outFiles": [],
            "translated": "",
            "settings": settings or {
                "promoAction": "replace",
                "filterSlanted": True,
                "quality": 90,
            },
        }
        self._atomic_write_json(self._get_chapter_path(project_id, ch_id), ch_data)

        ch_summary = {
            "id": ch_id,
            "chapterNumber": 1,
            "name": "چپتر ۱",
            "createdAt": now_iso,
            "updatedAt": now_iso,
            "step": 1,
            "totalPages": 0,
            "donePages": 0,
            "sourceMode": source_mode,
            "sourcePath": resolved_source_path,
        }

        manifest = {
            "id": project_id,
            "name": name.strip() if name and name.strip() else f"پروژه {project_id[5:]}",
            "createdAt": now_iso,
            "updatedAt": now_iso,
            "activeChapterId": ch_id,
            "chapters": [ch_summary],
            "step": 1,
            "sourceMode": source_mode,
            "sourcePath": resolved_source_path,
            "pages": [],
            "outFiles": [],
            "translated": "",
            "chapterName": "چپتر ۱",
            "chapterNumber": 1,
            "settings": ch_data["settings"],
        }

        self._atomic_write_json(self._get_manifest_path(project_id), manifest)
        return manifest

    def get_project(self, project_id: str, chapter_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        manifest_path = self._get_manifest_path(project_id)
        if not manifest_path.exists():
            return None
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            return None

        manifest = self._migrate_legacy_project_if_needed(manifest)

        target_ch_id = chapter_id or manifest.get("activeChapterId")
        if target_ch_id:
            ch_data = self.get_chapter(project_id, target_ch_id)
            if ch_data:
                manifest["step"] = ch_data.get("step", 1)
                manifest["pages"] = ch_data.get("pages", [])
                manifest["translated"] = ch_data.get("translated", "")
                manifest["outFiles"] = ch_data.get("outFiles", [])
                manifest["sourceMode"] = ch_data.get("sourceMode", manifest.get("sourceMode", "internal"))
                manifest["sourcePath"] = ch_data.get("sourcePath", manifest.get("sourcePath"))
                manifest["chapterName"] = ch_data.get("name", "چپتر ۱")
                manifest["chapterNumber"] = ch_data.get("chapterNumber", 1)
                manifest["activeChapterId"] = target_ch_id

        return manifest

    def save_project_state(self, project_id: str, state_update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current = self.get_project(project_id)
        if current is None:
            return None

        # به‌روزرسانی فیلدهای سطح بالای پروژه در صورت وجود
        if "name" in state_update and state_update["name"]:
            manifest_path = self._get_manifest_path(project_id)
            if manifest_path.exists():
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        raw_m = json.load(f)
                    raw_m["name"] = state_update["name"]
                    self._atomic_write_json(manifest_path, raw_m)
                except Exception:
                    pass

        active_ch_id = current.get("activeChapterId")
        if active_ch_id:
            self.save_chapter_state(project_id, active_ch_id, state_update)

        return self.get_project(project_id)

    def list_chapters(self, project_id: str) -> List[Dict[str, Any]]:
        manifest_path = self._get_manifest_path(project_id)
        if not manifest_path.exists():
            return []
        manifest = self.get_project(project_id)
        if not manifest:
            return []
        chapters = manifest.get("chapters", [])
        return sorted(chapters, key=lambda c: c.get("chapterNumber", 0))

    def create_chapter(
        self,
        project_id: str,
        name: Optional[str] = None,
        chapter_number: Optional[int] = None,
        source_path: Optional[str] = None,
        source_mode: str = "internal",
        settings: Optional[dict] = None,
    ) -> Dict[str, Any]:
        manifest_path = self._get_manifest_path(project_id)
        if not manifest_path.exists():
            raise ValueError(f"پروژه {project_id} یافت نشد.")

        manifest = self.get_project(project_id)
        chapters = manifest.get("chapters", [])

        if chapter_number is None:
            existing_numbers = [c.get("chapterNumber", 0) for c in chapters if isinstance(c.get("chapterNumber"), int)]
            chapter_number = (max(existing_numbers) + 1) if existing_numbers else (len(chapters) + 1)

        if not name or not name.strip():
            name = f"چپتر {chapter_number}"
        else:
            name = name.strip()

        ch_id = f"chap_{uuid.uuid4().hex[:8]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        resolved_source_path = None
        if source_path:
            p = Path(source_path).resolve()
            if p.exists() and p.is_dir():
                resolved_source_path = str(p)
                source_mode = "folder"

        ch_data = {
            "id": ch_id,
            "projectId": project_id,
            "chapterNumber": chapter_number,
            "name": name,
            "createdAt": now_iso,
            "updatedAt": now_iso,
            "step": 1,
            "sourceMode": source_mode,
            "sourcePath": resolved_source_path,
            "pages": [],
            "outFiles": [],
            "translated": "",
            "settings": settings or manifest.get("settings", {
                "promoAction": "replace",
                "filterSlanted": True,
                "quality": 90,
            }),
        }

        self._atomic_write_json(self._get_chapter_path(project_id, ch_id), ch_data)

        ch_summary = {
            "id": ch_id,
            "chapterNumber": chapter_number,
            "name": name,
            "createdAt": now_iso,
            "updatedAt": now_iso,
            "step": 1,
            "totalPages": 0,
            "donePages": 0,
            "sourceMode": source_mode,
            "sourcePath": resolved_source_path,
        }

        chapters.append(ch_summary)
        # Update manifest on disk
        with open(manifest_path, "r", encoding="utf-8") as f:
            raw_manifest = json.load(f)
        raw_manifest["chapters"] = chapters
        raw_manifest["updatedAt"] = now_iso
        self._atomic_write_json(manifest_path, raw_manifest)

        return ch_data

    def get_chapter(self, project_id: str, chapter_id: str) -> Optional[Dict[str, Any]]:
        ch_path = self._get_chapter_path(project_id, chapter_id)
        if not ch_path.exists():
            return None
        try:
            with open(ch_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def save_chapter_state(self, project_id: str, chapter_id: str, state_update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ch_data = self.get_chapter(project_id, chapter_id)
        if ch_data is None:
            return None

        allowed_keys = {"name", "step", "pages", "outFiles", "translated", "settings", "sourcePath", "sourceMode", "chapterNumber"}
        for k, v in state_update.items():
            if k in allowed_keys and v is not None:
                ch_data[k] = v

        now_iso = datetime.now(timezone.utc).isoformat()
        ch_data["updatedAt"] = now_iso
        self._atomic_write_json(self._get_chapter_path(project_id, chapter_id), ch_data)

        # Update summary in project.json
        manifest_path = self._get_manifest_path(project_id)
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                chapters = manifest.get("chapters", [])
                pages = ch_data.get("pages", [])
                done_count = sum(1 for p in pages if p.get("state") == "done")
                for ch in chapters:
                    if ch.get("id") == chapter_id:
                        ch["name"] = ch_data.get("name", ch.get("name"))
                        ch["chapterNumber"] = ch_data.get("chapterNumber", ch.get("chapterNumber"))
                        ch["step"] = ch_data.get("step", ch.get("step", 1))
                        ch["totalPages"] = len(pages)
                        ch["donePages"] = done_count
                        ch["updatedAt"] = now_iso
                        if ch_data.get("sourcePath"):
                            ch["sourcePath"] = ch_data["sourcePath"]
                        if ch_data.get("sourceMode"):
                            ch["sourceMode"] = ch_data["sourceMode"]
                        break
                manifest["chapters"] = chapters
                manifest["updatedAt"] = now_iso
                self._atomic_write_json(manifest_path, manifest)
            except Exception:
                pass

        return ch_data

    def delete_chapter(self, project_id: str, chapter_id: str) -> bool:
        ch_path = self._get_chapter_path(project_id, chapter_id)
        if ch_path.exists():
            try:
                ch_path.unlink()
            except Exception:
                pass

        manifest_path = self._get_manifest_path(project_id)
        if not manifest_path.exists():
            return False

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            chapters = [c for c in manifest.get("chapters", []) if c.get("id") != chapter_id]
            manifest["chapters"] = chapters
            if manifest.get("activeChapterId") == chapter_id:
                manifest["activeChapterId"] = chapters[0]["id"] if chapters else None
            manifest["updatedAt"] = datetime.now(timezone.utc).isoformat()
            self._atomic_write_json(manifest_path, manifest)
            return True
        except Exception:
            return False

    def set_active_chapter(self, project_id: str, chapter_id: str) -> Optional[Dict[str, Any]]:
        ch = self.get_chapter(project_id, chapter_id)
        if not ch:
            return None
        manifest_path = self._get_manifest_path(project_id)
        if not manifest_path.exists():
            return None
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            manifest["activeChapterId"] = chapter_id
            manifest["updatedAt"] = datetime.now(timezone.utc).isoformat()
            self._atomic_write_json(manifest_path, manifest)
            return self.get_project(project_id, chapter_id)
        except Exception:
            return None

    def delete_project(self, project_id: str) -> bool:
        proj_dir = self._get_project_dir(project_id)
        if not proj_dir.exists():
            return False
        try:
            shutil.rmtree(proj_dir, ignore_errors=True)
            return True
        except Exception:
            return False

    def scan_local_folder(self, folder_path: str) -> List[Dict[str, Any]]:
        p = Path(folder_path).resolve()
        if not p.exists() or not p.is_dir():
            return []

        entries = []
        for file_path in p.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in IMAGE_EXTENSIONS:
                try:
                    size = file_path.stat().st_size
                    entries.append({
                        "name": file_path.name,
                        "path": str(file_path),
                        "size": size,
                        "extension": file_path.suffix.lower(),
                    })
                except Exception:
                    continue

        entries.sort(key=lambda x: natural_sort_key(x["name"]))
        return entries


def pick_folder_native(title: str = "انتخاب پوشه تصاویر مانگا / وبتون", initial_dir: str = "") -> str:
    """Opens native Windows folder picker dialog in an isolated process to ensure it appears in the foreground."""
    import subprocess
    import sys

    # 1. First attempt: Tkinter askdirectory in a dedicated Python subprocess (clean Win32 STA thread)
    picker_script = (
        "import sys, os, tkinter as tk\n"
        "from tkinter import filedialog\n"
        "from pathlib import Path\n"
        "try:\n"
        "    root = tk.Tk()\n"
        "    root.overrideredirect(True)\n"
        "    root.geometry('0x0+0+0')\n"
        "    root.attributes('-topmost', True)\n"
        "    root.lift()\n"
        "    root.focus_force()\n"
        "    title = sys.argv[1] if len(sys.argv) > 1 else 'انتخاب پوشه'\n"
        "    init_dir = sys.argv[2] if len(sys.argv) > 2 and os.path.isdir(sys.argv[2]) else os.path.expanduser('~')\n"
        "    selected = filedialog.askdirectory(parent=root, title=title, initialdir=init_dir, mustexist=True)\n"
        "    root.destroy()\n"
        "    if selected:\n"
        "        print(str(Path(selected).resolve()))\n"
        "except Exception:\n"
        "    pass\n"
    )

    try:
        proc = subprocess.run(
            [sys.executable, "-c", picker_script, title, initial_dir],
            capture_output=True,
            text=True,
            timeout=300,
        )
        chosen = proc.stdout.strip()
        if chosen and os.path.isdir(chosen):
            return str(Path(chosen).resolve())
    except Exception:
        pass

    # 2. Second attempt: PowerShell FolderBrowserDialog with topmost owner form
    try:
        ps_code = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$form = New-Object System.Windows.Forms.Form; "
            "$form.TopMost = $true; "
            "$form.Width = 0; $form.Height = 0; "
            "$form.StartPosition = 'CenterScreen'; "
            "$form.Show(); "
            "$form.BringToFront(); "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$dialog.Description = '{title}'; "
            "$dialog.ShowNewFolderButton = $false; "
            "$res = $dialog.ShowDialog($form); "
            "$form.Dispose(); "
            "if ($res -eq [System.Windows.Forms.DialogResult]::OK) { "
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "Write-Output $dialog.SelectedPath "
            "}"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_code],
            capture_output=True,
            text=True,
            timeout=300,
        )
        chosen = proc.stdout.strip()
        if chosen and os.path.isdir(chosen):
            return str(Path(chosen).resolve())
    except Exception:
        pass

    return ""

