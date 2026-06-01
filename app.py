import os
import re
import json
import locale
import threading
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

downloads_dir = Path.home() / "Downloads"
downloads_dir.mkdir(exist_ok=True)

# In-memory store for download tasks
tasks: dict[str, dict] = {}
tasks_lock = threading.Lock()


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def run_yt_dlp(task_id: str, url: str, media_type: str, quality: str, out_dir: str):
    out_template = str(Path(out_dir) / "%(title)s.%(ext)s")

    if media_type == "audio":
        cmd = [
            "yt-dlp",
            "-x", "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", out_template,
            "--newline",
            url,
        ]
    else:
        fmt_map = {
            "best": "bestvideo+bestaudio/best",
            "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
        }
        fmt = fmt_map.get(quality, fmt_map["best"])
        cmd = [
            "yt-dlp",
            "-f", fmt,
            "--merge-output-format", "mp4",
            "-o", out_template,
            "--newline",
            url,
        ]

    with tasks_lock:
        tasks[task_id]["status"] = "downloading"

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=locale.getpreferredencoding(),
            errors="replace",
            bufsize=1,
        )

        last_title = ""
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue

            # Extract title
            if "[download] Destination:" in line:
                last_title = line.split("Destination:", 1)[-1].strip()
                last_title = os.path.basename(last_title)
                with tasks_lock:
                    tasks[task_id]["filename"] = last_title

            # Extract progress percentage
            pct_match = re.search(r'\[download\]\s+([\d.]+)%', line)
            if pct_match:
                pct = float(pct_match.group(1))
                with tasks_lock:
                    tasks[task_id]["progress"] = pct
                    tasks[task_id]["status"] = "downloading"

            # Log line to history
            if any(kw in line for kw in ["[download]", "[ExtractAudio]", "[Merger]", "[ffmpeg]"]):
                with tasks_lock:
                    tasks[task_id]["log"].append(line)

        proc.wait()

        if proc.returncode == 0:
            with tasks_lock:
                tasks[task_id]["status"] = "completed"
                tasks[task_id]["progress"] = 100
                tasks[task_id]["filename"] = tasks[task_id].get("filename") or last_title
        else:
            with tasks_lock:
                tasks[task_id]["status"] = "failed"
                tasks[task_id]["error"] = f"Exit code: {proc.returncode}"

    except Exception as e:
        with tasks_lock:
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = str(e)


@app.route("/")
def index():
    home = Path.home()
    return render_template("index.html",
        downloads=str(downloads_dir),
        desktop=str(home / "Desktop"),
        music=str(home / "Music"),
        videos=str(home / "Videos"),
    )


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json()
    url = data.get("url", "").strip()
    media_type = data.get("type", "video")
    quality = data.get("quality", "best")
    out_dir = data.get("directory", str(downloads_dir))

    if not url:
        return jsonify({"error": "请输入链接"}), 400

    if not os.path.isdir(out_dir):
        return jsonify({"error": "目录不存在"}), 400

    task_id = datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]
    with tasks_lock:
        tasks[task_id] = {
            "id": task_id,
            "url": url,
            "type": media_type,
            "quality": quality,
            "directory": out_dir,
            "status": "queued",
            "progress": 0,
            "filename": "",
            "error": "",
            "log": [],
            "created": datetime.now().isoformat(),
        }

    t = threading.Thread(target=run_yt_dlp, args=(task_id, url, media_type, quality, out_dir), daemon=True)
    t.start()

    return jsonify({"task_id": task_id})


@app.route("/api/tasks")
def list_tasks():
    with tasks_lock:
        task_list = [
            {
                "id": t["id"],
                "url": t["url"],
                "type": t["type"],
                "quality": t["quality"],
                "status": t["status"],
                "progress": t["progress"],
                "filename": t.get("filename", ""),
                "error": t.get("error", ""),
                "created": t.get("created", ""),
            }
            for t in tasks.values()
        ]
    task_list.sort(key=lambda x: x["created"], reverse=True)
    return jsonify(task_list)


@app.route("/api/tasks/<task_id>")
def get_task(task_id):
    with tasks_lock:
        t = tasks.get(task_id)
        if not t:
            return jsonify({"error": "Task not found"}), 404
        return jsonify({
            "id": t["id"],
            "url": t["url"],
            "type": t["type"],
            "quality": t["quality"],
            "status": t["status"],
            "progress": t["progress"],
            "filename": t.get("filename", ""),
            "error": t.get("error", ""),
            "log": t.get("log", []),
            "created": t.get("created", ""),
        })


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    with tasks_lock:
        if task_id in tasks:
            del tasks[task_id]
    return jsonify({"ok": True})


if __name__ == "__main__":
    webbrowser.open("http://127.0.0.1:5128/")
    app.run(host="127.0.0.1", port=5128, debug=False)
