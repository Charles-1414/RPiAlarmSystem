import time, json
import RPi.GPIO as GPIO
import coloredlogs, logging
import threading

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

gpiooff(config.GPIO.buzzer)





print("Loading")
def loading():
    t = threading.currentThread()
    while getattr(t, "load", True):
        gpioon(config.GPIO.blue)
        gpioon(config.GPIO.yellow)
        time.sleep(0.1)
        gpiooff(config.GPIO.blue)
        gpiooff(config.GPIO.yellow)
        time.sleep(0.1)
t = threading.Thread(target = loading)
t.load = True
t.start()





import cv2 # install it with `apt-get install python3-opencv`
import numpy as np
import picamera

import os, sys
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import datetime





# Logger Setup
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





t.load = False
gpiooff(config.GPIO.blue)
gpiooff(config.GPIO.yellow)
logger.info("RAS started")

script_start_time = time.time()
# No motion detection within first 15 seconds

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
                logger.warning("You may need to restart the script to make some changes take effect!")
                config = new_config
                config_txt = new_config_txt
                if not config.relay.server.endswith("/"):
                    config.relay.server += "/"
        except Exception as e:
            logger.error(f"Failed to import config: {str(e)}")
        time.sleep(1)



# DHT Info Fetcher
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
video_writer_in_use = 0
total_video_writers = 0
video_writers = {}

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
                memtotal = 1
                with open('/proc/meminfo',"r") as f:
                    for l in f.readlines():
                        if l.startswith('MemFree'):
                            memfree = int(l.split()[1])
                        elif l.startswith("MemTotal"):
                            memtotal = int(l.split()[1])
                cputemp = float(open("/sys/class/thermal/thermal_zone0/temp","r").read())/1000

                if config.motion_detection.watermark:
                    if len(self.frame_org) > 976: # make sure it's a valid frame (it's often invalid in the first seconds)
                        # Add watermark
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

                if config.motion_detection.enable:
                    # Write video if occupied
                    if occupied and video_writer_in_use != 0:
                        memfree /= 1024
                        if not config.motion_detection.watermark:
                            frame_np = np.asarray(bytearray(self.frame_org), dtype=np.uint8)
                            self.frame_cv2 = cv2.imdecode(frame_np, cv2.IMREAD_COLOR)
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


                # Calculate fps (only for debug use)
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

### CORE CODE
# Motion Detection
finish_save_time = 100000000000

def MotionDetection():
    if config.motion_detection.enable is False:
        return
    
    # Alarm Reaction for GPIO LEDs
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

    # Wait for the camera to be ready
    time.sleep(5)

    logger.info("Motion Detection started!")
    first_frame = None
    global occupied
    global finish_save_time

    global video_writers
    global video_writer_in_use
    global total_video_writers

    while 1:
        # Get frame from output
        frame = None
        backup_frame = None
        with output.condition:
            output.condition.wait()
            if config.motion_detection.watermark:
                frame = output.frame_cv2
            else:
                frame_np = np.asarray(bytearray(output.frame_org), dtype=np.uint8)
                frame = cv2.imdecode(frame_np, cv2.IMREAD_COLOR)
            backup_frame = frame

        # Set start time for timing calculation (debug only)
        st_time=time.time()
        
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

        ### Real Motion Detection starts from here!
        
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
        
        # Alert if occupied
        if movement_cnt != 0:
            logger.warning(f"Detected {movement_cnt} movement(s)!")
            occupied = True

            finish_save_time = time.time() + 3
            first_frame = gray
            f = config.settings.saving_dir
            if not f.endswith("/"):
                f += "/"
            f += f"{int(time.time())}.mp4"

            ratio = int(resolution[1]) / 1952 # stretch ratio
            
            if video_writer_in_use == 0:
                # No active video writer so create one
                video_writer_in_use = total_video_writers + 1
                total_video_writers += 1

                vw = VideoWriter()
                if config.motion_detection.watermark:
                    vw.video_writer = cv2.VideoWriter(f, fourcc, \
                        round(avgfps), (int(resolution[0]), int(resolution[1]) + int(148 * ratio)))
                else:
                    vw.video_writer = cv2.VideoWriter(f, fourcc, \
                        round(avgfps), (int(resolution[0]), int(resolution[1])))
                vw.frame_cnt += 1
                vw.frames[vw.frame_cnt] = backup_frame
                video_writers[video_writer_in_use] = vw

                threading.Thread(target=video_writers[video_writer_in_use].write,args=(video_writer_in_use,)).start()

            if not alarm_reaction.is_alive():
                # No active alarm reaction so start it
                alarm_reaction = threading.Thread(target=AlarmReaction)
                alarm_reaction.alarm = True
                alarm_reaction.start()

        else:
            if finish_save_time <= time.time():
                # To finish writing video and save
                logger.info(f"Video Writer {video_writer_in_use} to finish writing and save")

                finish_save_time = 100000000000
                occupied = False
                alarm_reaction.alarm = False

                video_writers[video_writer_in_use].do_write = False
                video_writer_in_use = 0

        # Calculate timing
        ed_time=time.time()
        logger.debug(f"The last round of motion detection took {round(ed_time-st_time,2)} seconds")

        time.sleep(0.05)



# LAN Streaming
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
status = ["disable","enable"]
STREAMING_PAGE=f"""<title>RPiAlarmSystem Streaming</title>
<p>Motion detection is {status[config.motion_detection.enable]}d (You can {status[1-config.motion_detection.enable]} it by changing the config file of your pi)</p>
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
                        if config.motion_detection.watermark:
                            frame = cv2.imencode('.jpg', output.frame_cv2)[1]
                        else:
                            frame = output.frame_org
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')

                    if config.motion_detection.enable:
                        time.sleep(0.3)

            except Exception as e:
                streaming_status -= 1
                if streaming_status == 0:
                    gpiooff(config.GPIO.blue)
                logger.warning(f'Removed streaming browser client {self.client_address} : {str(e)}')

        else:
            self.send_error(404)
            self.end_headers()

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True



# Relay Server (WAN Streaming + File Relay)

# Obviously socket streaming will be best
# But CloudFlare supports limited websocket connection
# So we have to fallback to HTTP streaming
# It's still acceptable

relay_status = 0
def VerifyRelayServer():
    global relay_status
    session = requests.Session()
    session.verify = True

    while 1:
        logger.info("Verifying relay server...")

        ok = 0
        hashed_token = generate_password_hash(config.relay.token)
        r = session.post(config.relay.server + "verify", data = {"token" : hashed_token}, headers = {'User-Agent': 'RPiAlarmSystem'})
        try:
            if r.status_code == 200:
                d = json.loads(r.text)
                if d["success"] is True:
                    if d["token"] != hashed_token and check_password_hash(d["token"], config.relay.token):
                        ok = 1
                    else:
                        ok = -1
                else:
                    ok = -1
            else:
                ok = 0
        except:
            ok = 0 # connection timed out

        relay_status = ok

        if ok == 0:
            logger.warning("Failed to connect to relay server. Retrying after 30 seconds...")
        
        elif ok == -1:
            logger.warning("Failed to verify relay server.")
            time.sleep(570)

        else:
            logger.info("Successfully verified relay server.")
            time.sleep(270)

        time.sleep(30)


def StreamRelay():
    global relay_status

    frame = None
    while frame is None:
        with output.condition:
            output.condition.wait()
            if config.motion_detection.watermark:
                frame = output.frame_cv2
            else:
                frame = output.frame_org
        time.sleep(1)
    
    # Set Request Session
    session = requests.Session()
    session.verify = True
    
    while relay_status != 1:
        time.sleep(5)

    logger.info("Relay server verified! WAN Streaming enabled!")

    # Prepare to stream
    time.sleep(30)
    global streaming_status
    stream_was_on = True

    while 1:
        while relay_status != 1:
            time.sleep(5)

        # Update hashed token each loop
        headers = {"Token" : generate_password_hash(config.relay.token), 'User-Agent': 'RPiAlarmSystem'}

        # first comfirm someone is watching the stream to reduce the use of
        # system resource and server bandwidth
        if not stream_was_on:
            r = session.get(config.relay.server + "stream_relay", headers = headers)
            if r.status_code != 200:
                continue
            
            d = json.loads(r.text)
            if d["streaming_status"] is False:
                time.sleep(5) # to reduce CPU use and also not to be recognized as an attack
                continue
            
            streaming_status += 1
            stream_was_on = True
            logger.warning("Someone started to watch stream through relay server! Check more info on relay server's log.")

        if streaming_status > 0:
            gpioon(config.GPIO.blue)
        frame = None
        with output.condition:
            output.condition.wait()
            if config.motion_detection.watermark:
                frame = cv2.imencode('.jpg', output.frame_cv2)[1].tobytes()
            else:
                frame = output.frame_org

        # (abandoned) as pi has really slow computing power, we'll upload the bytes array
        # to the server and let the server encode it to jpeg image
        # (current) due to the really slow network speed, I decided to encode img on pi
        # the numpy size is more than 20x bigger than jpg size

        r = session.post(config.relay.server + "stream_relay", data = frame , headers = headers)
        if r.status_code == 200:
            d = json.loads(r.text)
            if d["streaming_status"] is False:
                stream_was_on = False
                if streaming_status > 0:
                    streaming_status -= 1
                    if streaming_status == 0:
                        logger.warning("Someone stopped to watch stream from WAN! Check more info on relay server's log.")
                        gpiooff(config.GPIO.blue)

        else:
            logger.error("Unknown error occured at relay server")
            time.sleep(5)

        if config.motion_detection.enable:
            time.sleep(0.1)
        else:
            time.sleep(0.01)

def FileRelay():
    global relay_status

    session = requests.Session()

    while relay_status != 1:
        time.sleep(5)
    logger.info("Relay server verified! WAN File Download enabled!")

    while 1:
        while relay_status != 1:
            time.sleep(5)
        
        headers = {"Token" : generate_password_hash(config.relay.token), 'User-Agent': 'RPiAlarmSystem'}

        # Upload file list
        l = os.listdir("./videos")
        r = session.post(config.relay.server + "file_relay/file_list", data = {'list': ' '.join(l)}, headers = headers)
        if r.status_code != 200:
            continue
        
        # Check download request
        r = session.get(config.relay.server + "file_relay/download_request", headers = headers)
        if r.status_code != 200:
            continue
        d = json.loads(r.text)
        f = d["file"]
        if f != '':
            if os.path.exists(f"./videos/{f}"):
                logger.warning(f"Relay server requested video file {f}. Uploading...")
                r = session.post(config.relay.server + f"file_relay/upload{f}", data = open(f"./videos/{f}", "rb"), headers = headers)
                logger.warning(f"Relay server requested video file {f}. Uploaded!")
                if r.status_code != 200:
                    continue
            else:
                r = session.post(config.relay.server + "cancel_upload", headers = headers)
                if r.status_code != 200:
                    continue
        
        time.sleep(5)





if __name__ == "__main__":
    # Start functions
    threading.Thread(target=ConfigUpdater).start()
    threading.Thread(target=GetDHTInfo).start()

    threading.Thread(target=MotionDetection).start()

    threading.Thread(target=VerifyRelayServer).start()
    threading.Thread(target=StreamRelay).start()
    threading.Thread(target=FileRelay).start()


    # Start camera
    with picamera.PiCamera(resolution=config.resolution, framerate=config.fps) as camera:
        time.sleep(3)
        camera.start_recording(output, format='mjpeg')
        address = ('0.0.0.0', 8000)
        server = StreamingServer(address, StreamingHandler)
        server.serve_forever()

# In case user shut RPiAlarmSystem down 
# camera.stop_recording()