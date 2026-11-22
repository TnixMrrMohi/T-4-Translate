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

    def list_projects(self) -> List[Dict[str, Any]]:
        results = []
        if not self.projects_dir.exists():
            return results

        for child in self.projects_dir.iterdir():
            if child.is_dir():
                manifest_file = child / "project.json"
                if manifest_file.exists():
                    try:
                        with open(manifest_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        pages = data.get("pages", [])
                        done_count = sum(1 for p in pages if p.get("state") == "done")
                        results.append({
                            "id": data.get("id", child.name),
                            "name": data.get("name", child.name),
                            "createdAt": data.get("createdAt", ""),
                            "updatedAt": data.get("updatedAt", ""),
                            "step": data.get("step", 1),
                            "totalPages": len(pages),
                            "donePages": done_count,
                            "sourceMode": data.get("sourceMode", "internal"),
                            "sourcePath": data.get("sourcePath"),
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

        now_iso = datetime.now(timezone.utc).isoformat()
        resolved_source_path = None
        if source_path:
            p = Path(source_path).resolve()
            if p.exists() and p.is_dir():
                resolved_source_path = str(p)
                source_mode = "folder"

        manifest = {
            "id": project_id,
            "name": name.strip() if name and name.strip() else f"پروژه {project_id[5:]}",
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

        self._atomic_write_json(self._get_manifest_path(project_id), manifest)
        return manifest

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        manifest_path = self._get_manifest_path(project_id)
        if not manifest_path.exists():
            return None
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def save_project_state(self, project_id: str, state_update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current = self.get_project(project_id)
        if current is None:
            return None

        # Keys allowed to update
        allowed_keys = {"name", "step", "pages", "outFiles", "translated", "settings", "sourcePath", "sourceMode"}
        for k, v in state_update.items():
            if k in allowed_keys and v is not None:
                current[k] = v

        current["updatedAt"] = datetime.now(timezone.utc).isoformat()
        self._atomic_write_json(self._get_manifest_path(project_id), current)
        return current

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

