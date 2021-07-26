from flask import Flask, request, Response, abort, send_file
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.wsgi import FileWrapper

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

file_list = []
download_request = ''
download_file = ''
download_ready = False

pi_ipban_time = {} # ip : ban until
pi_ipban_count = {} # ip : ban counter
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



# IPBan functions
def update_ban(ip, client_type, clear = False):
    # client_type = 1: pi | 2: user
    global ipban_count
    global ipban_time

    if clear is True:
        if client_type == 1:
            if ip in ipban_count.keys():
                del pi_ipban_count[ip]
            if ip in ipban_time.keys():
                del pi_ipban_time[ip]
        
        elif client_type == 2:
            if ip in ipban_count.keys():
                del ipban_count[ip]
            if ip in ipban_time.keys():
                del ipban_time[ip]
    
    else:
        if client_type == 1:
            if not ip in pi_ipban_count.keys():
                pi_ipban_count[ip] = 0
            else:
                pi_ipban_count[ip] += 1
                if pi_ipban_count[ip] == 30: # to limit the max banning time to ~2 days
                    pi_ipban_count[ip] == 1
                if not ip in pi_ipban_time.keys():
                    pi_ipban_time[ip] = 0
                pi_ipban_time[ip] = time.time() + pow(1.5, pi_ipban_count[ip])

        elif client_type == 2:
            if not ip in ipban_count.keys():
                ipban_count[ip] = 0
            else:
                ipban_count[ip] += 1
                if ipban_count[ip] == 30: # to limit the max banning time to ~2 days
                    ipban_count[ip] == 1
                if not ip in ipban_time.keys():
                    ipban_time[ip] = 0
                ipban_time[ip] = time.time() + pow(1.5, ipban_count[ip])


# Relay Part

@app.route("/verify", methods = ['POST'])
def verify():
    if request.headers["User-Agent"] != "RPiAlarmSystem":
        abort(404)


    # Since I'm using CloudFlare, I get those info from those headers
    # You should change this based on your own situation
    # There are more code to fetch ip and country and you need to change them all
    ip = request.headers["Cf-Connecting-Ip"]
    country = request.headers["Cf-Ipcountry"]
    #####
    
    # Check IPBan
    global pi_ipban_time
    global pi_ipban_count

    if ip in pi_ipban_time.keys():
        if pi_ipban_time[ip] > time.time():
            abort(401)


    pitoken = request.form["token"]
    if check_password_hash(pitoken, config.token):
        logger.warning(f"Pi {ip} from {country} is successfully verified!")

        gentoken = generate_password_hash(config.token)
        while gentoken == pitoken:
            gentoken = generate_password_hash(config.token)

        update_ban(ip, 1, clear = True)
        return json.dumps({"success" : True, "token" : gentoken})

    else:
        logger.warning(f"Pi {ip} from {country} failed to verify!")
        update_ban(ip, 1)
        return json.dumps({"success" : False})


@app.route("/stream_relay", methods = ['GET', 'POST'])
def stream_relay():
    ip = request.headers["Cf-Connecting-Ip"]

    # Check IPBan
    global pi_ipban_time
    global pi_ipban_count

    if ip in pi_ipban_time.keys():
        if pi_ipban_time[ip] > time.time():
            abort(401)


    if request.headers["User-Agent"] != "RPiAlarmSystem":
        abort(404)
    try:
        if not check_password_hash(request.headers["Token"], config.token):
            abort(401)

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


@app.route("/file_relay/<string:op>", methods = ["GET", "POST"])
def file_relay(op):
    ip = request.headers["Cf-Connecting-Ip"]

    # Check IPBan
    global pi_ipban_time
    global pi_ipban_count

    if ip in pi_ipban_time.keys():
        if pi_ipban_time[ip] > time.time():
            abort(401)

    if request.headers["User-Agent"] != "RPiAlarmSystem":
        abort(404)
    try:
        if not check_password_hash(request.headers["Token"], config.token):
            abort(401)

        global download_request
        global download_file
        global download_ready
        global file_list

        if request.method == 'POST':
            if op == 'file_list':
                file_list = request.form['list'].split(" ")
                return json.dumps({"success":True})

            elif op.startswith("upload"):
                filename = op.replace("upload", "")

                if filename != download_request:
                    return json.dumps({"success":False, "msg":"File not requested"})

                try:
                    os.remove(download_file)
                except:
                    pass
                download_file=f"/tmp/{download_request}"
                open(download_file,"wb").write(request.data)
                download_ready = True
            
            elif op.startswith("cancel_upload"):
                download_request = ''
                return json.dumps({"success":True})

        
        elif request.method == 'GET':
            if op == 'download_request':
                if download_ready is True:
                    return json.dumps({"success":True, "file": ''})
                else:
                    return json.dumps({"success":True, "file": download_request})

    except:
        import traceback
        traceback.print_exc()
    abort(404)


# Streaming Part

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
    logger.warning(f"User {ip} from {country} stopped watching stream!")


@auth.verify_password
def verify_password(username, password):
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

    update_ban(ip, 2)

    logger.warning(f"User {ip} from {country} failed to login to watch stream! ")


@app.route("/stream", methods = ['GET'])
@auth.login_required
def client_stream():
    ip = request.headers["Cf-Connecting-Ip"]
    country = request.headers["Cf-Ipcountry"]

    logger.warning(f"User {ip} from {country} started to watch stream!")

    update_ban(ip, 2, clear=True)

    return Response(streaming(ip,country),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/file", methods = ['GET'])
@auth.login_required
def client_file():
    ip = request.headers["Cf-Connecting-Ip"]
    country = request.headers["Cf-Ipcountry"]

    logger.warning(f"User {ip} from {country} is getting file list!")

    update_ban(ip, 2, clear=True)

    page = """<title>RPiAlarmSystem</title>
    <h1>RPiAlarmSystem Video List</h1>"""

    global file_list
    for f in file_list:
        page += f"<p><a href='/download/{f.replace('.mp4','')}'>{f}</a></p>"

    return page

@app.route("/download/<string:filename>", methods = ['GET'])
@auth.login_required
def client_download(filename):
    global download_request
    global download_file
    global download_ready
    global file_list

    if download_request != '' and download_ready is False and filename != download_request.replace('.mp4',''):
        return f"<title>RPiAlarmSystem</title><p>Another download request is in progress!</p><p><a href='/download/{download_request.replace('.mp4','')}'>Go to that download</a></p>"

    filename += ".mp4"
    if filename in file_list:
        if download_request != filename:
            download_request = filename
            return "<title>RPiAlarmSystem</title><p>Download request received! Relay will now request file from pi. Please wait a few moments and refresh this page!</p>"
        else:
            if not download_ready:
                return "<title>RPiAlarmSystem</title><p>Download is still in progress. Please wait a few moments and refresh this page!</p>"
            else:
                return send_file(download_file, as_attachment = True, attachment_filename = download_request)
    else:
        return "<title>RPiAlarmSystem</title><p>File not found!</p><p><a href='/file'>Back</a></p>"


if __name__ == "__main__":
    threading.Thread(target=ConfigUpdater).start()
    app.run("127.0.0.1", 7777)