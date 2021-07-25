from flask import Flask, request, Response, abort
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash

import hashlib
import json
import time
import threading
import coloredlogs, logging

app = Flask(__name__)
auth = HTTPBasicAuth()

streaming_status = False
frame_bytes = None
frame_ts = 0

ipban_time = {} # ip : ban until
ipban_count = {} # ip : ban counter

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

if not config.streaming.password.startswith("!"):
    hashed = "!" + generate_password_hash(config.streaming.password)
    config_txt = config_txt.replace(config.streaming.password, hashed)
    open("./config.json","w").write(config_txt)
    config.streaming.password = hashed
config.streaming.password = config.streaming.password[1:]

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
logger.info("RAS Relay Server started")

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

@app.route("/verify", methods = ['POST'])
def verify():
    # Since I'm using CloudFlare, I get those info from those headers
    # You should change this based on your own situation
    ip = request.headers["Cf-Connecting-Ip"]
    country = request.headers["Cf-Ipcountry"]
    ##########

    if request.headers["User-Agent"] != "RPiAlarmSystem":
        abort(404)
    pitoken = request.form["token"]
    if check_password_hash(pitoken, config.token):
        logger.warning(f"{ip} from {country} is successfully verified!")

        gentoken = generate_password_hash(config.token)
        while gentoken == pitoken:
            gentoken = generate_password_hash(config.token)
        return json.dumps({"success" : True, "token" : gentoken})
    else:
        logger.warning(f"{ip} from {country} failed to verify!")

        return json.dumps({"success" : False})

@app.route("/relay", methods = ['GET', 'POST'])
def relay():
    if request.headers["User-Agent"] != "RPiAlarmSystem":
        abort(404)
    try:
        if not check_password_hash(request.headers["Token"], config.token):
            abort(403)

        global frame_bytes
        global frame_ts

        if request.method == 'GET':
            return json.dumps({"streaming_status":streaming_status})

        elif request.method == 'POST':
            frame_bytes = request.data
            frame_ts = time.time()
            return json.dumps({"success":True, "streaming_status":streaming_status})

    except:
        import traceback
        traceback.print_exc()
    abort(404)

def streaming(ip,country):
    global streaming_status
    cur_frame_ts = 0
    cur_sleep_cnt = 0 # send a response each 10 sec to prevent disconnection
    try:
        while True:
            if frame_ts != cur_frame_ts or cur_sleep_cnt == 100:
                cur_sleep_cnt = 0
                cur_frame_ts = frame_ts
                streaming_status = True
                yield (b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            cur_sleep_cnt += 0.1
            time.sleep(0.1)
    except:
        pass
    streaming_status = False
    logger.warning(f"{ip} from {country} stopped watching stream!")

@auth.verify_password
def verify_password(username, password):
    # Since I'm using CloudFlare, I get those info from those headers
    # You should change this based on your own situation
    ip = request.headers["Cf-Connecting-Ip"]
    country = request.headers["Cf-Ipcountry"]
    ##########
    
    global ipban_time
    global ipban_count

    if ip in ipban_time.keys():
        if ipban_time[ip] > time.time():
            abort(401)

    if username == config.streaming.user and check_password_hash(config.streaming.password, password):
        return username

    if not ip in ipban_count.keys():
        ipban_count[ip] = 0
    else:
        ipban_count[ip] += 1
        if ipban_count[ip] == 30: # to limit the max banning time to ~2 days
            ipban_count[ip] == 1
        if not ip in ipban_time.keys():
            ipban_time[ip] = 0
        ipban_time[ip] = time.time() + pow(1.5, ipban_count[ip])

    logger.warning(f"{ip} from {country} failed to login to watch stream! ")

@app.route("/stream", methods = ['GET'])
@auth.login_required
def stream():
    # Since I'm using CloudFlare, I get those info from those headers
    # You should change this based on your own situation
    ip = request.headers["Cf-Connecting-Ip"]
    country = request.headers["Cf-Ipcountry"]
    ##########

    logger.warning(f"{ip} from {country} started to watch stream!")

    if ip in ipban_time.keys():
        del ipban_time[ip]
        del ipban_count[ip]

    return Response(streaming(ip,country),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

threading.Thread(target=ConfigUpdater).start()
app.run("127.0.0.1", 7777)