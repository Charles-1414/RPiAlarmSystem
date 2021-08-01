# RPiAlarmSystem
A monitoring system with motion detector, based on RaspberryPi  
**Important Notice: I have updated the License to GNU General Public License, you must open source your project and let me know about it if your code is based on my code in any aspect. It's very simple and I hope you could obey it. Otherwise you will be held legally responsible!**  
*This project has finished core development. I will make constant update if there are issues or I got new ideas.*

## Introduction

### Features
i) Motion Detection (You can disable it and use Live Streaming only)  
ii) Video saving after motion is detected  
iii) Realtime streaming (LAN & WAN)  
iv) Video file download (LAN & WAN) delete (LAN only)

### More details
i) Automatically limiting saving video fps when little memory is free.  
ii) The pi is connected with a Adafruit DHT sensor so it can detect humidity and temperature.  
iii) Due to obvious reasons, the WAN Streaming has bad performance (0.6 frame per second) comparing to LAN Streaming (2 frame per second).  
iv) The config is compatible with RPi 3. If you have a RPi 4, it may be able to process frames of higher resolution and higher fps. :)  

### Testing results

Device: RaspberryPi 3B+  
<table>
    <tr><th>Motion Detection</th><th>Watermark</th><th>Streaming FPS</th><th>Recording FPS</th></tr>
    <tr><td>Enabled</td><td>Enabled</td><td>12</td><td>12</td></tr>
    <tr><td>Enabled</td><td>Disabled</td><td>32</td><td>12</td></tr>
    <tr><td>Disabled</td><td>Enabled</td><td>12</td><td>/</td></tr>
    <tr><td>Disabled</td><td>Disabled</td><td>32</td><td>/</td></tr>
</table>

### About the config
Motion detection and watermark can be disabled.  
If you disable motion detection, pi will not detect motion and record videos.  
If you disable watermark, the lines of text containing time and system info at the bottom of both stream and video will be removed.  
Since adding the watermark requires pi to convert raw frame to opencv readable frame and add the text, if will greatly reduce the fps of streaming. However, since outputing video records also require the convertion, the video file will never have higher fps unless you upgrade your device.  
I suggest enabling / disabling both motion detection and watermark at the same time for best performance. Because if you disable watermark and increase fps in the config, the video file will still have low fps and you may feel its sped-up as the fps the file told your player is the average fps before the record starts, close to the one in the config. If you only disable motion detection and enable watermark, the fps of streaming will still be low.  
By the way, the streaming fps refers to LAN streaming fps. WAN streaming fps is decided by the network speed between your pi and your relay server.

## Installation

*This is a very brief installation but I guess you can understand it using your powerful brain :)*  
1.Clone this repo  
2.Edit both hardware and relay_server config using the template (there's instruction in it)  
*You can run only the hardware part if you don't have a server. Just leave the relay.server in config empty.*  
3.Edit the code getting ip and country in relay_server/relay_server.py if you are not using CloudFlare
3.5.Edit the port of servers as you wish (in main.py, server.py and relay_serevr.py)
4.Upload the files in hardware and relay_server to your pi and your server  
5.Install dependencies using requirements.txt on both pi and server  
6.Run it! (You need to run all main.py, server.py, dht_server.py and relay_server.py at the same time)
*If you don't have a DHT sensor, just do not run the dht_server.py**

## And ...
The author is just a RPi hobbyist (and a student) who just make this project for fun. The author is NOT an expert of opencv / picture processing so the perfomance may be bad. If you have better solution, you are welcomed to open an issue and I'll be very grateful! :D  
