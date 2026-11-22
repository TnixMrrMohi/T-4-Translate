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

