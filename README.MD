# RPiAlarmSystem
A monitoring system with motion detector, based on RaspberryPi  
*This project has finished core development. I will make constant update if there are issues or I got new ideas.*

## Introduction

### Features
i) Motion Detection  
ii) Video saving after motion is detected  
iii) Realtime streaming (LAN & WAN)  
iv) Video file download (LAN & WAN)  

### More details
i) Automatically limiting saving video fps when little memory is free.  
ii) The pi is connected with a Adafruit DHT sensor so it can detect humidity and temperature.  
iii) Due to obvious reasons, the WAN Streaming has bad performance (0.6 frame per second) comparing to LAN Streaming (2 frame per second).  
iv) The config is compatible with RPi 3. If you have a RPi 4, it may be able to process frames of higher resolution and higher fps. :)  

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
