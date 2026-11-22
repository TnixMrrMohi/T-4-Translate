import json
import os
import shutil
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.projects import ProjectManager
from app.main import app


@pytest.fixture
def temp_data_dir():
    d = tempfile.mkdtemp(prefix="t4_test_projects_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def test_project_manager_crud(temp_data_dir):
    pm = ProjectManager(data_dir=temp_data_dir)
    
    # 1. List initially empty
    assert pm.list_projects() == []
    
    # 2. Create project
    proj = pm.create_project(name="Test Manga Chapter 1")
    assert proj["name"] == "Test Manga Chapter 1"
    assert "id" in proj
    assert proj["step"] == 1
    assert proj["pages"] == []
    project_id = proj["id"]
    
    # Verify file created on disk
    proj_dir = temp_data_dir / "projects" / project_id
    assert (proj_dir / "project.json").exists()
    
    # 3. Get project
    loaded = pm.get_project(project_id)
    assert loaded["id"] == project_id
    assert loaded["name"] == "Test Manga Chapter 1"
    
    # 4. Save state
    new_pages = [
        {"page": 1, "name": "01.jpg", "jobId": "job-1", "state": "done", "text": "Hello"}
    ]
    updated = pm.save_project_state(
        project_id,
        {
            "step": 2,
            "pages": new_pages,
            "translated": "سلام",
        }
    )
    assert updated["step"] == 2
    assert updated["translated"] == "سلام"
    assert len(updated["pages"]) == 1
    
    # Verify persistence after reload
    reloaded = pm.get_project(project_id)
    assert reloaded["step"] == 2
    assert reloaded["translated"] == "سلام"
    assert reloaded["pages"][0]["name"] == "01.jpg"
    
    # 5. List projects
    projs = pm.list_projects()
    assert len(projs) == 1
    assert projs[0]["id"] == project_id
    assert projs[0]["totalPages"] == 1
    assert projs[0]["donePages"] == 1
    
    # 6. Delete project
    assert pm.delete_project(project_id) is True
    assert pm.get_project(project_id) is None
    assert not proj_dir.exists()
    assert pm.list_projects() == []


def test_scan_local_folder(temp_data_dir):
    pm = ProjectManager(data_dir=temp_data_dir)
    folder = temp_data_dir / "sample_chapter"
    folder.mkdir(parents=True)
    
    # Create sample image files and a non-image file
    (folder / "page_02.png").write_bytes(b"fake_png")
    (folder / "page_01.jpg").write_bytes(b"fake_jpg")
    (folder / "page_10.webp").write_bytes(b"fake_webp")
    (folder / "notes.txt").write_text("ignore me")
    
    files = pm.scan_local_folder(str(folder))
    names = [f["name"] for f in files]
    # Natural sort order: page_01.jpg, page_02.png, page_10.webp
    assert names == ["page_01.jpg", "page_02.png", "page_10.webp"]
    assert all(f["size"] > 0 for f in files)
    assert files[0]["extension"] == ".jpg"


def test_project_api_endpoints(temp_data_dir, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(temp_data_dir))
    client = TestClient(app)
    
    # List projects (empty)
    res = client.get("/api/projects")
    assert res.status_code == 200
    assert res.json() == []
    
    # Create project
    res = client.post("/api/projects", json={"name": "API Test Project"})
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "API Test Project"
    project_id = data["id"]
    
    # Get project
    res = client.get(f"/api/projects/{project_id}")
    assert res.status_code == 200
    assert res.json()["id"] == project_id
    
    # Save state
    res = client.post(
        f"/api/projects/{project_id}/save-state",
        json={
            "step": 3,
            "translated": "متن تستی فارسی",
            "pages": [{"page": 1, "name": "01.png", "state": "done", "jobId": "j1"}],
        }
    )
    assert res.status_code == 200
    assert res.json()["step"] == 3
    assert res.json()["translated"] == "متن تستی فارسی"
    
    # Verify in list
    res = client.get("/api/projects")
    assert res.status_code == 200
    projects = res.json()
    assert len(projects) == 1
    assert projects[0]["id"] == project_id
    assert projects[0]["step"] == 3
    
    # Scan folder endpoint
    folder = temp_data_dir / "folder_test"
    folder.mkdir(parents=True)
    (folder / "img1.png").write_bytes(b"123")
    res = client.post("/api/projects/scan-folder", json={"path": str(folder)})
    assert res.status_code == 200
    files = res.json().get("files", [])
    assert len(files) == 1
    assert files[0]["name"] == "img1.png"

    # Browse folder endpoint (mocked)
    with monkeypatch.context() as m:
        m.setattr("app.projects.pick_folder_native", lambda: str(folder))
        res = client.post("/api/projects/browse-folder")
        assert res.status_code == 200
        assert res.json()["path"] == str(folder)
        assert res.json()["canceled"] is False
    
    # Delete project
    res = client.delete(f"/api/projects/{project_id}")
    assert res.status_code == 200
    assert res.json()["ok"] is True
    
    # Verify 404 after delete
    res = client.get(f"/api/projects/{project_id}")
    assert res.status_code == 404


def test_create_job_from_path(temp_data_dir, monkeypatch):
    from PIL import Image
    monkeypatch.setenv("T4_DATA_DIR", str(temp_data_dir))
    client = TestClient(app)

    # Create real image on disk
    img_path = temp_data_dir / "real_image.png"
    img = Image.new("RGB", (100, 100), color=(200, 200, 200))
    img.save(img_path)

    res = client.post("/api/jobs/from-path", json={"path": str(img_path)})
    assert res.status_code == 201
    data = res.json()
    assert "jobId" in data
    assert data["width"] == 100
    assert data["height"] == 100
    assert data["format"] == "PNG"


def test_project_manager_chapters(temp_data_dir):
    pm = ProjectManager(data_dir=temp_data_dir)
    proj = pm.create_project(name="Solo Leveling")
    proj_id = proj["id"]

    # 1. Project automatically initializes with default chapter 1
    chapters = pm.list_chapters(proj_id)
    assert len(chapters) == 1
    assert chapters[0]["chapterNumber"] == 1
    assert chapters[0]["name"] == "چپتر ۱"
    ch1_id = chapters[0]["id"]
    assert proj["activeChapterId"] == ch1_id

    # 2. Create chapter 2
    ch2 = pm.create_chapter(proj_id, name="چپتر ۲")
    assert ch2["chapterNumber"] == 2
    assert ch2["name"] == "چپتر ۲"
    ch2_id = ch2["id"]

    # 3. List chapters shows both
    chapters = pm.list_chapters(proj_id)
    assert len(chapters) == 2
    assert [c["chapterNumber"] for c in chapters] == [1, 2]

    # 4. Save state in chapter 2 (isolation check)
    pm.save_chapter_state(
        proj_id,
        ch2_id,
        {
            "step": 3,
            "pages": [{"page": 1, "name": "c2_01.webp", "state": "done"}],
            "translated": "ترجمه چپتر ۲",
        }
    )

    # Ch2 has step 3 and 1 page
    loaded_ch2 = pm.get_chapter(proj_id, ch2_id)
    assert loaded_ch2["step"] == 3
    assert len(loaded_ch2["pages"]) == 1
    assert loaded_ch2["translated"] == "ترجمه چپتر ۲"

    # Ch1 remains at step 1 and 0 pages
    loaded_ch1 = pm.get_chapter(proj_id, ch1_id)
    assert loaded_ch1["step"] == 1
    assert len(loaded_ch1["pages"]) == 0

    # 5. Switch active chapter
    pm.set_active_chapter(proj_id, ch2_id)
    loaded_proj = pm.get_project(proj_id)
    assert loaded_proj["activeChapterId"] == ch2_id
    assert loaded_proj["step"] == 3
    assert len(loaded_proj["pages"]) == 1

    # 6. Delete chapter
    assert pm.delete_chapter(proj_id, ch2_id) is True
    assert pm.get_chapter(proj_id, ch2_id) is None
    chapters = pm.list_chapters(proj_id)
    assert len(chapters) == 1
    assert chapters[0]["id"] == ch1_id


def test_legacy_project_migration(temp_data_dir):
    pm = ProjectManager(data_dir=temp_data_dir)
    proj_dir = temp_data_dir / "projects" / "proj_legacy"
    proj_dir.mkdir(parents=True)
    legacy_manifest = {
        "id": "proj_legacy",
        "name": "Legacy Manhwa",
        "createdAt": "2026-11-20T10:00:00Z",
        "updatedAt": "2026-11-20T10:00:00Z",
        "step": 4,
        "pages": [{"page": 1, "name": "old_01.jpg", "state": "done"}],
        "translated": "متن قدیمی",
        "outFiles": [],
    }
    (proj_dir / "project.json").write_text(json.dumps(legacy_manifest), encoding="utf-8")

    # Load legacy project -> must migrate smoothly
    proj = pm.get_project("proj_legacy")
    assert proj is not None
    assert "activeChapterId" in proj
    assert "chapters" in proj
    assert len(proj["chapters"]) == 1
    assert proj["chapters"][0]["name"] == "چپتر ۱"
    assert proj["step"] == 4
    assert proj["translated"] == "متن قدیمی"

    # Chapter file on disk exists
    ch_file = proj_dir / "chapters" / f"{proj['activeChapterId']}.json"
    assert ch_file.exists()


def test_chapter_api_endpoints(temp_data_dir, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(temp_data_dir))
    client = TestClient(app)

    # 1. Create project
    res = client.post("/api/projects", json={"name": "Tower of God"})
    assert res.status_code == 200
    proj = res.json()
    proj_id = proj["id"]
    ch1_id = proj["activeChapterId"]

    # 2. List chapters
    res = client.get(f"/api/projects/{proj_id}/chapters")
    assert res.status_code == 200
    chaps = res.json()
    assert len(chaps) == 1
    assert chaps[0]["id"] == ch1_id

    # 3. Create chapter 2
    res = client.post(
        f"/api/projects/{proj_id}/chapters",
        json={"name": "چپتر ۲", "chapter_number": 2}
    )
    assert res.status_code == 200
    ch2 = res.json()
    assert ch2["name"] == "چپتر ۲"
    assert ch2["chapterNumber"] == 2
    ch2_id = ch2["id"]

    # 4. Get chapter 2
    res = client.get(f"/api/projects/{proj_id}/chapters/{ch2_id}")
    assert res.status_code == 200
    assert res.json()["name"] == "چپتر ۲"

    # 5. Save state in chapter 2
    res = client.post(
        f"/api/projects/{proj_id}/chapters/{ch2_id}/save-state",
        json={"step": 2, "translated": "ترجمه چپتر ۲ برج خدا"}
    )
    assert res.status_code == 200
    assert res.json()["step"] == 2
    assert res.json()["translated"] == "ترجمه چپتر ۲ برج خدا"

    # 6. Activate chapter 2
    res = client.post(f"/api/projects/{proj_id}/chapters/{ch2_id}/activate")
    assert res.status_code == 200
    proj_updated = res.json()
    assert proj_updated["activeChapterId"] == ch2_id
    assert proj_updated["step"] == 2

    # 7. Delete chapter 2
    res = client.delete(f"/api/projects/{proj_id}/chapters/{ch2_id}")
    assert res.status_code == 200
    assert res.json()["ok"] is True

    # 8. List chapters again
    res = client.get(f"/api/projects/{proj_id}/chapters")
    assert res.status_code == 200
    assert len(res.json()) == 1



