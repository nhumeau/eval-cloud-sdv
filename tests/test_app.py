# tests/test_app.py
import json
import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId

import os
os.environ.setdefault("COSMOS_CONNECTION_STRING", "mongodb://localhost:27017/")
os.environ.setdefault("STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=https;AccountName=x;AccountKey=ey==;EndpointSuffix=core.windows.net")

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def mock_collection():
    """Mock pymongo collection for all tests."""
    with patch("app.get_collection") as mock_get:
        col = MagicMock()
        mock_get.return_value = col
        yield col


def test_list_tasks_empty(client, mock_collection):
    mock_collection.find.return_value = []
    res = client.get("/api/tasks")
    assert res.status_code == 200
    assert res.get_json() == []


def test_create_task(client, mock_collection):
    fake_id = ObjectId()
    mock_collection.insert_one.return_value = MagicMock(inserted_id=fake_id)
    res = client.post(
        "/api/tasks",
        data=json.dumps({"title": "Apprendre Azure"}),
        content_type="application/json",
    )
    assert res.status_code == 201
    data = res.get_json()
    assert data["title"] == "Apprendre Azure"
    assert data["done"] is False
    assert data["_id"] == str(fake_id)


def test_create_task_missing_title(client, mock_collection):
    res = client.post(
        "/api/tasks",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert res.status_code == 400


def test_update_task(client, mock_collection):
    task_id = str(ObjectId())
    res = client.put(
        f"/api/tasks/{task_id}",
        data=json.dumps({"done": True}),
        content_type="application/json",
    )
    assert res.status_code == 200
    assert res.get_json() == {"ok": True}
    mock_collection.update_one.assert_called_once()


def test_delete_task(client, mock_collection):
    task_id = str(ObjectId())
    res = client.delete(f"/api/tasks/{task_id}")
    assert res.status_code == 200
    assert res.get_json() == {"ok": True}
    mock_collection.delete_one.assert_called_once()


def test_update_task_invalid_id(client, mock_collection):
    res = client.put(
        "/api/tasks/not-a-valid-id",
        data=json.dumps({"done": True}),
        content_type="application/json",
    )
    assert res.status_code == 400


def test_delete_task_invalid_id(client, mock_collection):
    res = client.delete("/api/tasks/not-a-valid-id")
    assert res.status_code == 400
