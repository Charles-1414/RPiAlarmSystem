import picamera
import cv2
from PIL import Image, ImageDraw, ImageFont
import numpy as np

import os,sys
import threading
import json
import time,datetime
import coloredlogs,logging

# Starting
script_start_time = time.time()
# No actual running within first 15 seconds

# Import config

class Dict2Obj(object):
    def __init__(self, d):
        for key in d:
            if type(d[key]) is dict:
                data = Dict2Obj(d[key])
                setattr(self, key, data)
            else:
                setattr(self, key, d[key])

config_txt = open("./config.json","r").read()
config = Dict2Obj(json.loads(config_txt))
motion_output = None

# Set logger

coloredlogs.install()
loglvl = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR, "critical": logging.CRITICAL}
logger = logging.getLogger("RASlogger")
logger.setLevel(loglvl[config.logging.level.lower()])
handler = logging.FileHandler(config.logging.file)
# handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("[%(levelname)s] (%(asctime)s) %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.info("RAS started")

# Config Updater 

def ConfigUpdater():
    global config
    global config_txt
    while 1:
        try:
            new_config_txt = open("./config.json","r").read()
            new_config = Dict2Obj(json.loads(new_config_txt))
            if config_txt != new_config_txt:
                logger.info("Successfully imported config")
                config = new_config
                config_txt = new_config_txt
        except Exception as e:
            logger.error(f"Failed to import config: {str(e)}")
        time.sleep(1)

# Camera output and motion detection
import io
from threading import Condition

occupied = False

class StreamingOutput(object):
    def __init__(self):
        self.frame_org = None
        self.frame_cv2 = None
        self.frame_timestamp = 0
        self.buffer = io.BytesIO()
        self.condition = Condition()
        self.fps_ts = 0
        self.fps_cnt = 0

    def write(self, buf):
        if buf.startswith(b'\xff\xd8'):
            # New frame, copy the existing buffer's content and notify all clients it's available
            self.buffer.truncate()
            with self.condition:
                self.frame_org = self.buffer.getvalue()
                self.frame_timestamp = datetime.datetime.now()
                
                if len(self.frame_org) > 1000:
                    # add watermark
                    frame_np = np.asarray(bytearray(self.frame_org), dtype=np.uint8)
                    self.frame_cv2 = cv2.imdecode(frame_np, cv2.IMREAD_COLOR)

                    frame_resolution = config.resolution.split("x")
                    frame_resolution = (int(frame_resolution[0]), int(frame_resolution[1]))
                    ratio = frame_resolution[1] / 1952
                    self.frame_cv2  = cv2.copyMakeBorder(self.frame_cv2,0,int(8 * ratio),0,0,cv2.BORDER_CONSTANT,value=[255,0,0])
                    self.frame_cv2  = cv2.copyMakeBorder(self.frame_cv2,0,int(60 * ratio),0,0,cv2.BORDER_CONSTANT,value=[0,0,0])
                    shp = self.frame_cv2.shape
                    ts = self.frame_timestamp.strftime("%A %d %B %Y %H:%M:%S")
                    cv2.putText(self.frame_cv2, f"[{config.resolution}] {ts}", (10,int(shp[0]-12*ratio)), cv2.FONT_HERSHEY_SIMPLEX, 1.4 * ratio, (255,255,255), thickness=2)
                    cv2.putText(self.frame_cv2, "Captured by RPiAlarmSystem (C) 2021 Charles", 
                        (int(shp[1]/2),int(shp[0]-12*ratio)), cv2.FONT_HERSHEY_SIMPLEX, 1.4 * ratio, (255,255,255), thickness=2)

                if self.fps_ts == 0:
                    self.fps_ts = int(time.time())
                else:
                    if self.fps_ts == int(time.time()):
                        self.fps_cnt += 1
                    else:
                        logger.info(f"Current FPS: {self.fps_cnt} frames")
                        self.fps_cnt = 0
                        self.fps_ts = int(time.time())
                
                self.condition.notify_all()

            self.buffer.seek(0)

        return self.buffer.write(buf)

output = StreamingOutput()

# Streaming server
import socketserver
from http import server

## Limit the width and height to decrease delay
resolution = config.resolution.split("x")
width , height = int(resolution[0]), int(resolution[1])
t=1
for i in range(0,10):
    if width <= 1000 and height <= 1000:
        break
    t *= 2
    width /= 2
    height /= 2
STREAMING_PAGE=f"""<title>RPiAlarmSystem Streaming</title>
<img src="/stream.mjpg" width="{width}" height="{height}" />"""

class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/stream':
            content = STREAMING_PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)

        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            logger.info(f'Added streaming browser client {self.client_address}')
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = cv2.imencode('.jpg', output.frame_cv2)[1]
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
                    time.sleep(0.3)

            except Exception as e:
                import traceback
                traceback.print_exc()
                logger.warning(f'Removed streaming browser client {self.client_address} : {str(e)}')

        elif self.path == '/stream.dat':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            logger.info(f'Added streaming software client {self.client_address}')
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame_cv2
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
                    time.sleep(0.1)

            except Exception as e:
                import traceback
                traceback.print_exc()
                logger.warning(f'Removed streaming software client {self.client_address} : {str(e)}')
        
        elif self.path == '/status':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            logger.info(f'Added status streaming client {self.client_address}')
            try:
                while True:
                    data = ""
                    if occupied:
                        data = "Occupied"
                    else:
                        data = "Not occupied"
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Content-Length', len(data))
                    self.end_headers()
                    self.wfile.write(data.encode("utf-8"))
                    self.wfile.write(b'\r\n')
                    time.sleep(0.5)

            except Exception as e:
                import traceback
                traceback.print_exc()
                logger.warning(f'Removed status streaming client {self.client_address} : {str(e)}')

        else:
            self.send_error(404)
            self.end_headers()

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

# Motion Detection
finish_save_time = 0

def MotionDetection():
    time.sleep(5)
    logger.info("Motion Detection started!")
    first_frame = None
    while 1:
        frame = None
        with output.condition:
            output.condition.wait()
            frame = output.frame_cv2

        st_time=time.time()
        global occupied
        global finish_save_time
        
        # Compress image (must do!)
        resize_resolution = config.motion_detection.resolution.split("x")
        frame = cv2.resize(frame, (int(resize_resolution[0]), int(resize_resolution[1])), interpolation = cv2.INTER_AREA)

        # Convert frame to GrayScale
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        gray = cv2.GaussianBlur(gray,(21,21),0)

        # Saving the first frame if it doesn't exist
        if first_frame is None:
            first_frame = gray
            continue

        # Real Motion Detection starts from here!
        
        # Calculates difference to detect motion
        delta_frame = cv2.absdiff(first_frame, gray)

        # Applies threshold and converts it to black & white image
        threshold = cv2.threshold(delta_frame, 100, 255, cv2.THRESH_BINARY)[1]
        threshold = cv2.dilate(threshold, None, iterations=0)

        # Finding contours on the white portion(made by the threshold)
        _,cnts,_ = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        movement_cnt = 0
        for c in cnts:
            if cv2.contourArea(c) < config.motion_detection.min_size:
                continue

            (x, y, w, h) = cv2.boundingRect(c)
            cv2.rectangle(threshold, (x, y), (x + w, y + h), (0, 255, 0), 2)
            movement_cnt += 1

        # Alert
        if movement_cnt != 0:
            logger.warning(f"Detected {movement_cnt} movement(s)!")
            occupied = True
            finish_save_time = time.time() + 3
            first_frame = gray
        else:
            if finish_save_time <= time.time():
                occupied = False

        ed_time=time.time()
        logger.debug(f"The last round of motion detection took {round(ed_time-st_time,2)} seconds")

        time.sleep(0.05)

if __name__ == "__main__":
    threading.Thread(target=MotionDetection).start()
    threading.Thread(target=ConfigUpdater).start()
    with picamera.PiCamera(resolution=config.resolution, framerate=config.fps) as camera:
        time.sleep(3)
        camera.start_recording(output, format='mjpeg')
        address = ('0.0.0.0', 8000)
        server = StreamingServer(address, StreamingHandler)
        server.serve_forever()

# In case user shut RPiAlarmSystem down 
# camera.stop_recording()