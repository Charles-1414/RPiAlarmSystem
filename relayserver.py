from flask import Flask, request, Response, abort
import numpy as np
import cv2
import io
import base64
import json
import time

app = Flask(__name__)

streaming_status = True
frame_np = None
frame_bytes = None
frame_ts = 0

@app.route("/relay", methods = ['GET', 'POST'])
def relay():
    try:
        global frame_np
        global frame_bytes
        global frame_ts
        if request.method == 'GET':
            return json.dumps({"streaming_status":streaming_status})
        elif request.method == 'POST':
            frame_np_buffer = base64.b64decode(request.form["frame_np"])
            frame_np = np.frombuffer(frame_np_buffer, dtype = np.uint8)
            frame_np = frame_np.reshape(list(map(int, request.form["shape"].split(", "))))
            frame_bytes = cv2.imencode('.jpg', frame_np)[1]
            frame_ts = time.time()
            return json.dumps({"success":True,"streaming_status":streaming_status})
    except:
        import traceback
        traceback.print_exc()
    abort(404)

def streaming():
    global streaming_status
    cur_frame_ts = 0
    cur_sleep_cnt = 0 # send a response each 10 sec to prevent disconnection
    while True:
        if frame_ts != cur_frame_ts or cur_sleep_cnt == 10:
            cur_sleep_cnt = 0
            cur_frame_ts = frame_ts
            streaming_status = True
            yield (b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes.tobytes() + b'\r\n')
        cur_sleep_cnt += 0.1
        time.sleep(0.1)
    streaming_status = False


@app.route("/stream", methods = ['GET'])
def stream():
    return Response(streaming(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

app.run("127.0.0.1", 7777)