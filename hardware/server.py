from flask import Flask, send_file, abort

import os
import json

app = Flask(__name__)

PAGE = """<title>RPiAlarmSystem</title>
<h1>RPiAlarmSystem Video List</h1>"""

@app.route("/",methods=['GET'])
def index():
    videos = os.listdir("./videos/")
    page = PAGE
    for video in videos:
        page += f"<p><a href='/download/{video.replace('.mp4','')}'>{video}</a> <a href='/delete/{video.replace('.mp4','')}' onclick=\"return confirm('Are you sure to delete this file? This operation cannot be undone!')\">Delete</a></p>"
    return page

@app.route("/download/<string:filename>",methods=['GET']) # with mp4 extension
def download_video(filename):
    if not filename.endswith(".mp4"):
        filename+=".mp4"
    if os.path.exists(f"./videos/{filename}"):
        return send_file(f"./videos/{filename}", as_attachment = True)
    else:
        abort(404)

@app.route("/delete/<string:filename>",methods=['GET'])
def delete_video(filename):
    if not filename.endswith(".mp4"):
        filename+=".mp4"
    if os.path.exists(f"./videos/{filename}"):
        os.remove(f"./videos/{filename}")
        return "<meta http-equiv='refresh' content='3;url=/' /><title>RPiAlarmSystem</title><p>File deleted. Redirecting...</p>"
    else:
        return "<meta http-equiv='refresh' content='3;url=/' /><title>RPiAlarmSystem</title><p>File not found! Redirecting...</p>"

app.run("0.0.0.0",8080)