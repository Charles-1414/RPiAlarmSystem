# RPiAlarmSystem
A monitoring system with motion detector, based on RaspberryPi  
*This project is still under development*  

## Current features
i) Motion Detection  
ii) Video saving after motion is detected  
iii) Realtime streaming (LAN only)  

## More details
i) Automatically limiting saving video fps when little memory is free.  
ii) The pi is connected with a Adafruit DHT sensor so it can detect humidity and temperature.  
iii) The config is compatible with RPi 3. If you have a RPi 4, it may be able to process frames of higher resolution and higher fps. :)  

## Planning features
i) Relay server to expose the video stream to WAN (and of course with authentication)  
ii) Online control panel to edit settings  
iii) Email notification when motion is detected  

## And ...
The author is just a RPi hobbyist (and a student) who just make this project for fun. The author is NOT an expert of opencv / picture processing so the perfomance may be bad. If you have better solution, you are welcomed to open an issue and I'll be very grateful! :D  
