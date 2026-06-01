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


def normalize_url(url: str) -> str:
    """Convert B站 /lists?sid= to /channel/collectiondetail?sid= supported by yt-dlp."""
    m = re.match(r'https?://space\.bilibili\.com/(\d+)/lists\?sid=(\d+)', url)
    if m:
        return f"https://space.bilibili.com/{m.group(1)}/channel/collectiondetail?sid={m.group(2)}"
    return url


def run_yt_dlp(task_id: str, url: str, media_type: str, quality: str, out_dir: str):
    out_template = str(Path(out_dir) / "%(title)s.%(ext)s")

    base_cmd = ["yt-dlp"]
    # Add cookies from file if it exists (for B站 etc.)
    for cookie_path in [os.path.join(out_dir, "cookies.txt"), "cookies.txt"]:
        if os.path.isfile(cookie_path):
            base_cmd += ["--cookies", cookie_path]
            break

    if media_type == "audio":
        cmd = base_cmd + [
            "--no-overwrites",
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
        cmd = base_cmd + [
            "--no-overwrites",
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


def _create_task(url: str, media_type: str, quality: str, out_dir: str, batch_id: str = "") -> str:
    url = normalize_url(url)
    task_id = datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]
    with tasks_lock:
        tasks[task_id] = {
            "id": task_id,
            "url": url,
            "type": media_type,
            "quality": quality,
            "directory": out_dir,
            "batch_id": batch_id,
            "status": "queued",
            "progress": 0,
            "filename": "",
            "error": "",
            "log": [],
            "created": datetime.now().isoformat(),
        }
    t = threading.Thread(target=run_yt_dlp, args=(task_id, url, media_type, quality, out_dir), daemon=True)
    t.start()
    return task_id


@app.route("/api/parse", methods=["POST"])
def parse_url():
    data = request.get_json()
    url = normalize_url(data.get("url", "").strip())
    if not url:
        return jsonify({"error": "请输入链接"}), 400

    base_cmd = ["yt-dlp"]
    for cp in [os.path.join(str(downloads_dir), "cookies.txt"), "cookies.txt"]:
        if os.path.isfile(cp):
            base_cmd += ["--cookies", cp]
            break

    try:
        proc = subprocess.run(
            base_cmd + ["--flat-playlist", "-J", "--no-download", url],
            capture_output=True,
            text=True,
            encoding=locale.getpreferredencoding(),
            errors="replace",
            timeout=30,
        )

        if proc.returncode != 0:
            stderr = (proc.stderr or "")[:200]
            hint = ""
            if "412" in stderr and "bilibili" in url.lower():
                hint = " | 建议: 将 B站 cookies.txt 放到下载目录中"
            return jsonify({"error": f"解析失败{hint}", "type": "single", "title": "", "entries": [], "count": 0})

        info = json.loads(proc.stdout)
        entries = info.get("entries", [])
        if entries:
            items = [
                {
                    "title": e.get("title", "未知"),
                    "url": e.get("url", "") or e.get("webpage_url", ""),
                    "duration": e.get("duration") or 0,
                    "index": e.get("playlist_index", i + 1),
                }
                for i, e in enumerate(entries)
            ]
            return jsonify({
                "type": "playlist",
                "title": info.get("title", "合集"),
                "count": len(items),
                "entries": items,
            })
        else:
            return jsonify({
                "type": "single",
                "title": info.get("title", ""),
                "entries": [{"title": info.get("title", "未知"), "url": url, "duration": info.get("duration") or 0, "index": 1}],
                "count": 1,
            })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "解析超时，请检查链接"}), 408
    except Exception as e:
        return jsonify({"error": f"解析失败: {str(e)}"}), 500


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json()
    urls = data.get("urls", [])
    single_url = data.get("url", "").strip()
    media_type = data.get("type", "video")
    quality = data.get("quality", "best")
    out_dir = data.get("directory", str(downloads_dir))

    if not os.path.isdir(out_dir):
        return jsonify({"error": "目录不存在"}), 400

    if urls:
        batch_id = datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]
        task_ids = []
        for item in urls:
            if isinstance(item, dict):
                u = item.get("url", "").strip()
            else:
                u = str(item).strip()
            if u:
                tid = _create_task(u, media_type, quality, out_dir, batch_id)
                task_ids.append(tid)
        if not task_ids:
            return jsonify({"error": "请输入链接"}), 400
        return jsonify({"task_ids": task_ids, "batch_id": batch_id})
    else:
        if not single_url:
            return jsonify({"error": "请输入链接"}), 400
        task_id = _create_task(single_url, media_type, quality, out_dir)
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
