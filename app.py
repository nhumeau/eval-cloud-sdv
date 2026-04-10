import os
import json
import datetime
from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="static", static_url_path="")


def get_collection():
    conn_str = os.environ["COSMOS_CONNECTION_STRING"]
    client = MongoClient(conn_str, serverSelectionTimeoutMS=5000)
    return client["tododb"]["tasks"]


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    col = get_collection()
    tasks = list(col.find())
    for t in tasks:
        t["_id"] = str(t["_id"])
    return jsonify(tasks)


@app.route("/api/tasks", methods=["POST"])
def create_task():
    data = request.get_json()
    if not data or not data.get("title"):
        return jsonify({"error": "title required"}), 400
    task = {
        "title": data["title"].strip(),
        "done": False,
        "created_at": datetime.datetime.now().isoformat() + "Z",
    }
    col = get_collection()
    result = col.insert_one(task)
    task["_id"] = str(result.inserted_id)
    return jsonify(task), 201


@app.route("/api/tasks/<task_id>", methods=["PUT"])
def update_task(task_id):
    data = request.get_json()
    try:
        oid = ObjectId(task_id)
    except InvalidId:
        return jsonify({"error": "invalid id"}), 400
    col = get_collection()
    done = bool(data["done"])
    update = {"done": done}
    if done:
        update["completed_at"] = datetime.datetime.now().isoformat() + "Z"
    else:
        update["completed_at"] = None
    col.update_one({"_id": oid}, {"$set": update})
    return jsonify({"ok": True})


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    try:
        oid = ObjectId(task_id)
    except InvalidId:
        return jsonify({"error": "invalid id"}), 400
    col = get_collection()
    col.delete_one({"_id": oid})
    return jsonify({"ok": True})


@app.route("/api/export", methods=["POST"])
def export_to_blob():
    from azure.storage.blob import BlobServiceClient

    col = get_collection()
    tasks = list(col.find())
    for t in tasks:
        t["_id"] = str(t["_id"])

    conn_str = os.environ["STORAGE_CONNECTION_STRING"]
    container = os.environ.get("BLOB_CONTAINER", "exports")
    timestamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    blob_name = f"export-{timestamp}.json"

    blob_client = BlobServiceClient.from_connection_string(conn_str)
    bc = blob_client.get_blob_client(container=container, blob=blob_name)
    bc.upload_blob(json.dumps(tasks, indent=2, ensure_ascii=False))

    return jsonify({"blob_name": blob_name, "url": bc.url})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
