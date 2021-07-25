import Adafruit_DHT as DHT
import socketserver
from http import server
import json
import time

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

class DHTServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

class DHTHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/info":
            humidity, temperature = DHT.read_retry(DHT.DHT11, config.GPIO.dht)
            if humidity is None:
                humidity = "--"
            if temperature is None:
                temperature = "--"
            d = json.dumps({"humidity": str(humidity), "temperature": str(temperature)})
            self.send_response(200)
            self.send_header('Content-Type', 'text/json')
            self.send_header('Content-Length', len(d))
            self.end_headers()
            self.wfile.write(d.encode("utf-8"))

        else:
            self.send_error(404)
            self.end_headers()

address = ('127.0.0.1', 8001)
server = DHTServer(address, DHTHandler)
server.serve_forever()
