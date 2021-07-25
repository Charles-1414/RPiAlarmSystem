import picamera
import RPi.GPIO as GPIO

import cv2
from PIL import Image, ImageDraw, ImageFont
import numpy as np

import os,sys
import threading
import base64,hashlib
import json,requests
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
if not config.relay.server.endswith("/"):
    config.relay.server += "/"


# GPIO Setup
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BOARD)
GPIO.setup(config.GPIO.blue,GPIO.OUT)
GPIO.setup(config.GPIO.yellow,GPIO.OUT)
GPIO.setup(config.GPIO.buzzer,GPIO.OUT)

def gpioon(port):
    GPIO.output(port,GPIO.HIGH)

def gpiooff(port):
    GPIO.output(port,GPIO.LOW)

gpiooff(config.GPIO.blue)
gpiooff(config.GPIO.yellow)
gpiooff(config.GPIO.buzzer)

# Set logger
coloredlogs.install()
coloredlogs.set_level(config.logging.display_level.upper())
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
                if not config.relay.server.endswith("/"):
                    config.relay.server += "/"
        except Exception as e:
            logger.error(f"Failed to import config: {str(e)}")
        time.sleep(1)

# Get DHT Info
humidity = "--"
temperature = "--"

def GetDHTInfo():
    global humidity
    global temperature
    while 1:
        try:
            r = requests.get("http://127.0.0.1:8001/info")
            d = json.loads(r.text)
            humidity = d["humidity"]
            temperature = d["temperature"]
        except:
            pass
        time.sleep(3)

# Video Writer
fourcc = cv2.VideoWriter_fourcc('m', 'p', '4', 'v')
class VideoWriter(object):
    def __init__(self):
        self.video_writer = None
        self.frames = {}
        self.frame_cnt = 0
        self.frame_written = 0
        self.do_write = True

        self.mem_warn = False
        self.mem_warn_starting_frame = 0

    def write(self,writer_id):
        logger.info(f"Video Writer {writer_id} started")
        while self.do_write or self.frame_written < self.frame_cnt:
            if self.frame_written < self.frame_cnt:
                if not self.frame_written+1 in self.frames.keys():
                    self.frame_written+=1
                    continue
                if self.mem_warn is True and self.mem_warn_starting_frame <= self.frame_written:
                    for _ in range(0,int(avgfps/2)): # limit to 2 fps
                        self.video_writer.write(self.frames[self.frame_written+1])
                    self.frame_written+=1
                else:
                    self.video_writer.write(self.frames[self.frame_written+1])
                    self.frame_written+=1
                del self.frames[self.frame_written]
            time.sleep(0.1)
        self.video_writer.release()
        logger.info(f"Video Writer {writer_id} stopped")

video_writer_in_use = 0
total_video_writers = 0
video_writers = {}

# Camera output
import io
from threading import Condition

occupied = False
avgfps = config.fps

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
        global video_writers
        global avgfps
        if buf.startswith(b'\xff\xd8'):
            # New frame, copy the existing buffer's content and notify all clients it's available
            self.buffer.truncate()
            with self.condition:
                self.frame_org = self.buffer.getvalue()
                self.frame_timestamp = datetime.datetime.now()
                
                memfree = 0
                if len(self.frame_org) > 1000:
                    # add watermark
                    frame_np = np.asarray(bytearray(self.frame_org), dtype=np.uint8)
                    self.frame_cv2 = cv2.imdecode(frame_np, cv2.IMREAD_COLOR)

                    frame_resolution = config.resolution.split("x")
                    frame_resolution = (int(frame_resolution[0]), int(frame_resolution[1]))
                    ratio = frame_resolution[1] / 1952
                    self.frame_cv2  = cv2.copyMakeBorder(self.frame_cv2,0,int(8 * ratio),0,0,cv2.BORDER_CONSTANT,value=[255,0,0])
                    self.frame_cv2  = cv2.copyMakeBorder(self.frame_cv2,0,int(140 * ratio),0,0,cv2.BORDER_CONSTANT,value=[0,0,0])

                    text_color = (255,255,255)

                    shp = self.frame_cv2.shape
                    ts = self.frame_timestamp.strftime("%A %d %B %Y %H:%M:%S")
                    memfree = 0
                    memtotal = 1
                    with open('/proc/meminfo',"r") as f:
                        for l in f.readlines():
                            if l.startswith('MemFree'):
                                memfree = int(l.split()[1])
                            elif l.startswith("MemTotal"):
                                memtotal = int(l.split()[1])
                    cputemp = float(open("/sys/class/thermal/thermal_zone0/temp","r").read())/1000
                    memwarn = ""
                    if memfree/1024 < 100:
                        memwarn = "[Low MEM]"
                        text_color = (0,255,255)
                    txt = f"{config.resolution}  |  Humidity: {humidity}%  | Temperature: {temperature}C  |  CPU Temperature: {round(cputemp,1)}C  |  MEM Used: {int((memtotal - memfree) / memtotal * 100)}% {memwarn}"

                    if occupied:
                        text_color = (0,0,255)

                    cv2.putText(self.frame_cv2, txt, (10,int(shp[0]-86*ratio)), cv2.FONT_HERSHEY_SIMPLEX, 1.4 * ratio, text_color, thickness=2)
                    cv2.putText(self.frame_cv2, ts, (10,int(shp[0]-26*ratio)), cv2.FONT_HERSHEY_SIMPLEX, 1.4 * ratio, text_color, thickness=2)
                    cv2.putText(self.frame_cv2, "Captured by RPiAlarmSystem (C) 2021 Charles", 
                        (int(shp[1]/2),int(shp[0]-26*ratio)), cv2.FONT_HERSHEY_SIMPLEX, 1.4 * ratio, text_color, thickness=2)


                if occupied and video_writer_in_use != 0:
                    memfree /= 1024
                    if memfree < 50:
                        if video_writers[video_writer_in_use].mem_warn is False:
                            video_writers[video_writer_in_use].mem_warn = True
                            video_writers[video_writer_in_use].mem_warn_starting_frame = video_writers[video_writer_in_use].frame_cnt + 1
                        if self.fps_cnt in [int(avgfps / 2) - 1, int(avgfps) - 1]: # limit to 2 fps
                            video_writers[video_writer_in_use].frames[video_writers[video_writer_in_use].frame_cnt + 1] = self.frame_cv2
                            video_writers[video_writer_in_use].frame_cnt += 1
                    else:
                        video_writers[video_writer_in_use].frames[video_writers[video_writer_in_use].frame_cnt + 1] = self.frame_cv2
                        video_writers[video_writer_in_use].frame_cnt += 1

                if self.fps_ts == 0:
                    self.fps_ts = int(time.time())
                else:
                    if self.fps_ts == int(time.time()):
                        self.fps_cnt += 1
                    else:
                        if self.fps_cnt >= 6:
                            avgfps = round((avgfps + self.fps_cnt) / 2, 2)
                        logger.debug(f"Current FPS: {self.fps_cnt} frames | Average FPS: {avgfps} frames")
                        self.fps_cnt = 0
                        self.fps_ts = int(time.time())
                
                self.condition.notify_all()

            self.buffer.seek(0)

        return self.buffer.write(buf)

output = StreamingOutput()

# Motion Detection
finish_save_time = 100000000000

def MotionDetection():
    def AlarmReaction():
        t = threading.currentThread()
        while getattr(t, "alarm", True):
            for _ in range(3):
                gpioon(config.GPIO.yellow)
                if config.settings.alarm_buzz:
                    gpioon(config.GPIO.buzzer)
                time.sleep(0.1)
                gpiooff(config.GPIO.yellow)
                gpiooff(config.GPIO.buzzer)
                time.sleep(0.1)
            time.sleep(0.2)
        gpiooff(config.GPIO.yellow)
        gpiooff(config.GPIO.buzzer)
    alarm_reaction = threading.Thread(target=AlarmReaction)
    alarm_reaction.alarm = True

    time.sleep(5)
    logger.info("Motion Detection started!")
    first_frame = None
    while 1:
        frame = None
        backup_frame = None
        with output.condition:
            output.condition.wait()
            frame = output.frame_cv2
            backup_frame = frame

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
        global video_writers
        global video_writer_in_use
        global total_video_writers
        if movement_cnt != 0:
            logger.warning(f"Detected {movement_cnt} movement(s)!")
            occupied = True
            finish_save_time = time.time() + 3
            first_frame = gray
            f = config.settings.saving_dir
            if not f.endswith("/"):
                f += "/"
            f += f"{int(time.time())}.mp4"
            ratio = int(resolution[1]) / 1952
            
            if video_writer_in_use == 0:
                video_writer_in_use = total_video_writers + 1
                total_video_writers += 1
                vw = VideoWriter()
                vw.video_writer = cv2.VideoWriter(f, fourcc, \
                    round(avgfps), (int(resolution[0]), int(resolution[1]) + int(148 * ratio)))
                vw.frame_cnt += 1
                vw.frames[vw.frame_cnt] = backup_frame
                video_writers[video_writer_in_use] = vw
                threading.Thread(target=video_writers[video_writer_in_use].write,args=(video_writer_in_use,)).start()

            if not alarm_reaction.is_alive():
                alarm_reaction = threading.Thread(target=AlarmReaction)
                alarm_reaction.alarm = True
                alarm_reaction.start()
        else:
            if finish_save_time <= time.time():
                logger.info(f"Video Writer {video_writer_in_use} to finish writing and save")
                finish_save_time = 100000000000
                occupied = False
                alarm_reaction.alarm = False
                video_writers[video_writer_in_use].do_write = False
                video_writer_in_use = 0

        ed_time=time.time()
        logger.debug(f"The last round of motion detection took {round(ed_time-st_time,2)} seconds")

        time.sleep(0.05)

# Streaming server
import socketserver
from http import server

streaming_status = 0

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
        global streaming_status
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
            streaming_status += 1
            try:
                while True:
                    gpioon(config.GPIO.blue)
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
                streaming_status -= 1
                if streaming_status == 0:
                    gpiooff(config.GPIO.blue)
                logger.warning(f'Removed streaming browser client {self.client_address} : {str(e)}')

        elif self.path == '/stream.dat':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            logger.info(f'Added streaming software client {self.client_address}')
            streaming_status += 2
            try:
                while True:
                    gpioon(config.GPIO.blue)
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
                streaming_status -= 2
                if streaming_status == 0:
                    gpiooff(config.GPIO.blue)
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
                logger.warning(f'Removed status streaming client {self.client_address} : {str(e)}')

        else:
            self.send_error(404)
            self.end_headers()

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

# WAN Streaming (Sending data to relay server)

# Obviously socket streaming will be best
# But CloudFlare supports limited websocket connection
# So we have to fallback to HTTP streaming
# However we still can use the keep-alive method

def WANStreaming():
    frame = None
    while frame is None:
        with output.condition:
            output.condition.wait()
            frame = output.frame_cv2
        time.sleep(1)
    
    # Set Request Session
    session = requests.Session()
    session.verify = True

    # Verify Relay Server
    hashed_token = hashlib.sha256(config.relay.token.encode()).hexdigest()
    r = session.post(config.relay.server + "verify", data = {"token" : hashed_token, "shape" : str(frame.shape)[1:-1]}, \
        headers = {'User-Agent': 'RPiAlarmSystem'})
    ok = False
    if r.status_code == 200:
        d = json.loads(r.text)
        if d["success"] is True:
            if d["token"] == config.relay.token:
                ok = True
            else:
                ok = False
        else:
            ok = False
    else:
        ok = False
    
    if not ok:
        logger.warning("Failed to verify relay server. WAN Streaming disabled.")
        return
    logger.info("Successfully verified relay server. Starting WAN Streaming.")

    # Prepare to stream
    time.sleep(30)
    headers = {"Token" : config.relay.token, 'User-Agent': 'RPiAlarmSystem'}
    global streaming_status
    stream_was_on = False

    while 1:
        # first comfirm someone is watching the stream to reduce the use of
        # system resource and server bandwidth
        if not stream_was_on:
            r = session.get(config.relay.server + "relay", headers = headers)
            d = json.loads(r.text)
            if d["streaming_status"] is False:
                if stream_was_on:
                    streaming_status -= 1
                    if streaming_status == 0:
                        gpiooff(config.GPIO.blue)
                time.sleep(5) # to reduce CPU use and also not to be recognized as an attack
                continue
            
            streaming_status += 1
            stream_was_on = True

        gpioon(config.GPIO.blue)
        frame = None
        with output.condition:
            output.condition.wait()
            frame = output.frame_cv2

        # as pi has really slow computing power, we'll upload the bytes array
        # to the server and let the server encode it to jpeg image
        frame_np = base64.b64encode(frame.tostring()).decode()
    
        shape = str(frame.shape)[1:-1]
        
        r = session.post(config.relay.server + "relay", data = {"frame_np" : frame_np, "shape": shape}, headers = headers)
        if r.status_code == 200:
            d = json.loads(r.text)
            if d["streaming_status"] is False:
                streaming_status -= 1
                stream_was_on = False
                if streaming_status == 0:
                    gpiooff(config.GPIO.blue)

        else:
            logger.error("Unknown error occured at relay server")
            time.sleep(5)

        
        time.sleep(0.1)

# Starting show
# for _ in range(3):
#     gpioon(config.GPIO.blue)
#     gpioon(config.GPIO.yellow)
#     gpioon(config.GPIO.buzzer)
#     time.sleep(0.5)
#     gpiooff(config.GPIO.blue)
#     gpiooff(config.GPIO.yellow)
#     gpiooff(config.GPIO.buzzer)
#     time.sleep(0.5)

for _ in range(25):
    gpioon(config.GPIO.blue)
    gpiooff(config.GPIO.yellow)
    time.sleep(0.1)
    gpiooff(config.GPIO.blue)
    gpioon(config.GPIO.yellow)
    time.sleep(0.1)
gpiooff(config.GPIO.yellow)


if __name__ == "__main__":
    threading.Thread(target=MotionDetection).start()
    threading.Thread(target=ConfigUpdater).start()
    threading.Thread(target=GetDHTInfo).start()
    threading.Thread(target=WANStreaming).start()
    with picamera.PiCamera(resolution=config.resolution, framerate=config.fps) as camera:
        time.sleep(3)
        camera.start_recording(output, format='mjpeg')
        address = ('0.0.0.0', 8000)
        server = StreamingServer(address, StreamingHandler)
        server.serve_forever()

# In case user shut RPiAlarmSystem down 
# camera.stop_recording()