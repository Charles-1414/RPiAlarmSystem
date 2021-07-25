from flask import Flask, send_file, abort

import os

app = Flask(__name__)

PAGE = """<title>RPiAlarmSystem</title>
<h1>RPiAlarmSystem Video List</h1>"""

@app.route("/")
def index():
    videos = os.listdir("./videos/")
    page = PAGE
    for video in videos:
        page += f"<p><a href='/download/{video.replace('.mp4','')}'>{video}</a></p>"
    return page

@app.route("/download/<string:filename>") # with mp4 extension
def download_video(filename):
    if not filename.endswith(".mp4"):
        filename+=".mp4"
    if os.path.exists(f"./videos/{filename}"):
        return send_file(f"./videos/{filename}", as_attachment = True)
    else:
        abort(404)

app.run("0.0.0.0",8080)