#!/usr/bin/python3

# Program to implement an eFinder (electronic finder) on motorised Alt Az telescopes
# Copyright (C) 2024 Keith Venables.
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# This variant is customised for RPi HQ camera.
# It requires astrometry.net installed
import os
import sys
import socket
if len(sys.argv) > 1:
    print ('Killing any eFinder Lite & Live running')
    os.system('pkill -9 -f eFinder_Live.py') # stops the autostart eFinder program running
    os.system('pkill -9 -f eFinder_Lite.py') # stops the autostart eFinder program running

from pathlib import Path
home_path = str(Path.home())
param = dict()
if os.path.exists(home_path + "/Solver/eFinder.config") == True:
    with open(home_path + "/Solver/eFinder.config") as h:
        for line in h:
            line = line.strip("\n").split(":")
            param[line[0]] = str(line[1])
import Display_Lite
version = "Live_1_9"
handpad = Display_Lite.Handpad(version,param["Flip"])
handpad.display('ScopeDog eFinder','Lite','Version '+ version)
import time
import math
from threading import Thread
from PIL import Image, ImageDraw,ImageFont, ImageEnhance
from skyfield.api import load, Star
import numpy as np
np.math = math
import Location_live
import Coordinates_Lite
from gpiozero import Button
from tetra3 import Tetra3, cedar_detect_client
cedar_detect = cedar_detect_client.CedarDetectClient()
import tetra3
import csv
from shutil import copyfile
import datetime
from datetime import timezone

handpad.display('ScopeDog eFinder','Lite','Loading program')
x = y = 0  # x, y  define what page the display is showing
deltaAz = deltaAlt = 0
expInc = 0.1 # sets how much exposure changes when using handpad adjust (seconds)
gainInc = 5 # ditto for gain
offset_flag = False
align_count = 0
stop = False
solve = False
sync_count = 0
sDog = True
gotoFlag = False
dispBright = 241
home_path = str(Path.home())
c= 0
fnt = ImageFont.truetype(home_path+"/Solver/text.ttf",8)
prev = 0,0,0
solved_radec = (0.0,89.9)
go_to = False
threshold = 0.4
ts = load.timescale()
addr = ""
hotspot = False

try:
    os.mkdir("/var/tmp/solve")
except:
    pass

def serveWifi(): # serve WiFi port
    global gotoRa,gotoDec, go_to,doMove, dirMove, solved_radec, speed, goto_altaz, addr
    print ('starting wifi server')
    host = ''
    port = 4060
    backlog = 50
    size = 1024
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host,port))
    s.listen(backlog)
    hostname = socket.gethostname()
    addr = socket.gethostbyname(hostname + '.local') 

    try:
        while True:
            client, address = s.accept()
            while True:
                data = client.recv(size)
                if not data:
                    break
                if data:
                    pkt = data.decode("utf-8","ignore")
                    time.sleep(0.02)
                    a = pkt.split('#')
                    #print(a)
                    raPacket = coordinates.hh2dms(solved_radec[0])+'#'
                    decPacket = coordinates.dd2aligndms(solved_radec[1])+'#'
                    for x in a:
                        if x != '':
                            #print (x)
                            if x == ':GR':
                                client.send(bytes(raPacket.encode('ascii')))
                            elif x == ':GD':
                                client.send(bytes(decPacket.encode('ascii')))
                            elif x[1:3] == 'Sr': # goto instructions incoming
                                raStr = x[3:]
                                client.send(b'1')
                            elif x[1:3] == 'Sd': # goto instructions incoming
                                decStr = x[3:]
                                client.send(b'1')  
                            elif x[1:3] == 'MS':
                                client.send(b'0')
                                ra = raStr.split(':')
                                gotoRa = int(ra[0])+int(ra[1])/60+int(ra[2])/3600
                                dec = decStr.split('*')
                                decdec = dec[1].split(':')
                                gotoDec = int(dec[0]) + math.copysign((int(decdec[0])/60+int(decdec[1])/3600),float(dec[0]))
                                print('GoTo target received:',gotoRa, gotoDec)
                                goto_radec = gotoRa, gotoDec
                                goto_altaz = conv_altaz(*(goto_radec))
                                print('goto AltAz',goto_altaz)
                                go_to = True
                            elif x[1] == 'Q':
                                print('STOP!')
                                go_to = False
                                doMove = False
    except:
        pass

def conv_altaz(ra: float, dec: float):

    Rad = math.pi / 180
    t = ts.now()
    LST = t.gmst + geoloc.get_long() / 15  # as decimal hours
    ra = ra * 15  # need to work in degrees now
    LSTd = LST * 15
    LHA = (LSTd - ra + 360) - ((int)((LSTd - ra + 360) / 360)) * 360
    x = math.cos(LHA * Rad) * math.cos(dec * Rad)
    y = math.sin(LHA * Rad) * math.cos(dec * Rad)
    z = math.sin(dec * Rad)
    xhor = x * math.cos((90 - geoloc.get_lat()) * Rad) - z * math.sin(
        (90 - geoloc.get_lat()) * Rad)
    yhor = y
    zhor = x * math.sin((90 - geoloc.get_lat()) * Rad) + z * math.cos(
        (90 - geoloc.get_lat()) * Rad)
    az = math.atan2(yhor, xhor) * (180 / math.pi) + 180
    alt = math.asin(zhor) * (180 / math.pi)
    return (alt, az)   

def pixel2dxdy(pix_x, pix_y):  # converts a pixel position, into a delta angular offset from the image centre
    global cam
    deg_x = (float(pix_x) - cam[0]/2) * cam[2]/3600  # in degrees
    deg_y = (cam[1]/2 - float(pix_y)) * cam[2] / 3600
    dxstr = "{: .1f}".format(float(60 * deg_x))  # +ve if finder is left of main scope
    dystr = "{: .1f}".format(float(60 * deg_y))  # +ve if finder is looking below main scope
    return (deg_x, deg_y, dxstr, dystr)

def dxdy2pixel(dx, dy): # converts offsets in arcseconds to pixel position
    global cam
    pix_x = dx * 3600 / cam[2] + cam[0]/2
    pix_y = cam[1]/2 - dy * 3600 / cam[2]
    dxstr = "{: .1f}".format(float(60 * dx))  # +ve if finder is left of main scope
    dystr = "{: .1f}".format(float(60 * dy))  # +ve if finder is looking below main scope
    return (pix_x, pix_y, dxstr, dystr)


def capture():
    global param
    if param["Test_mode"] == "1" or param["Test_mode"] == "True":
        if offset_flag == False:
            m13 = True
            polaris_cap = False
        else:
            m13 = False
            polaris_cap = True
    else:
        m13 = False
        polaris_cap = False
    camera.capture(
        int(float(param["Exposure"]) * 1000000),
        int(float(param["Gain"])),
        m13,
        polaris_cap,
        destPath,
    )


def solveImage(looping = False):
    global offset_flag, solve, solvedPos, elapsed_time, solved_radec, solved_altaz, firstStar, solution, cam, stars, go_to

    start_time = time.time()
    #handpad.display("Started solving", "", "")
    captureFile = destPath + "capture.png"
    with Image.open(captureFile).convert('L') as img:
        centroids = cedar_detect.extract_centroids(
            img,
            max_size=10,
            sigma=8,
            use_binned=False,
            )
        stars = str(len(centroids))
        if len(centroids) < 20:
            handpad.display("Bad image","only"+ stars," centroids")
            solve = False
            time.sleep(1)
            return
        solution = t3.solve_from_centroids(
                        centroids,
                        (img.size[1],img.size[0]),
                        fov_estimate=cam[3],
                        fov_max_error=1,
                        match_max_error=0.002,
                        target_pixel=offset,
                        return_matches=True,
                    )
        elapsed_time = str(time.time() - start_time)[0:3]

    if solution['RA'] == None:
        handpad.display("Not Solved",stars + " centroids", "")
        solve = False
        return
    firstStar = centroids[0]
    ra = solution['RA_target']
    dec = solution['Dec_target']
    solved = Star(
        ra_hours=ra / 15, dec_degrees=dec
    )  # will set as J2000 as no epoch input
    solvedPos = (
        geoloc.get_location().at(coordinates.get_ts().now()).observe(solved)
    )  # now at Jnow and current location

    ra, dec, d = solvedPos.apparent().radec(coordinates.get_ts().now())
    solved_radec = ra.hours, dec.degrees
    solved_altaz = conv_altaz(*(solved_radec))
    if looping:
        arr[0, 1][0] = "Sol: Az " + coordinates.ddd2dms(solved_altaz[1])
        arr[0, 1][1] = "   Alt " + coordinates.dd2dms(solved_altaz[0])
        if go_to == True:
            ddAz = goto_altaz[1] - solved_altaz[1]
            if ddAz > 180:
                ddAz = (ddAz - 180) * -1
            elif ddAz < -180:
                ddAz = (ddAz +180) * -1
            ddAlt = goto_altaz[0] - solved_altaz[0]
            if ddAz < 0:
                sAz = 'L'
            else:
                sAz = 'R'
            if ddAlt < 0:
                sAlt = 'Dn'
            else:
                sAlt = 'Up'
            dAz = ('%s %3.2f' % (sAz,abs(ddAz)))
            dAlt = ('%s %2.2f' % (sAlt, abs(ddAlt)))
            arr[0, 1][2] = dAz + '   ' + dAlt
        else:
            arr[0, 1][2] = stars + " stars in " + elapsed_time + " s"
    else:
        arr[0, 1][0] = "Sol: RA " + coordinates.hh2dms(solved_radec[0])
        arr[0, 1][1] = "   Dec " + coordinates.dd2dms(solved_radec[1])
        arr[0, 1][2] = stars + " stars in " + elapsed_time + " s"
    solve = True

def measure_offset():
    global offset_str, offset_flag, offset, param, scope_x, scope_y, firstStar
    offset_flag = True
    handpad.display("started capture", "", "")
    capture()
    solveImage()
    if solve == False:
        handpad.display("solve failed", "", "")
        return
    scope_x = firstStar[1]
    scope_y = firstStar[0]
    offset = firstStar
    d_x, d_y, dxstr, dystr = pixel2dxdy(scope_x, scope_y)
    param["d_x"] = "{: .2f}".format(float(60 * d_x))
    param["d_y"] = "{: .2f}".format(float(60 * d_y))
    save_param()
    offset_str = dxstr + "," + dystr
    arr[0,2][1] = "new " + offset_str
    hipId = str(solution['matched_catID'][0])
    name = ""
    with open(home_path+'/Solver/data/starnames.csv') as csvfile:
            reader = csv.reader(csvfile, delimiter=',')
            for row in reader:
                nam = row[0].strip()
                hip = row[1]
                if str(row[1]) == str(solution['matched_catID'][0]):
                    hipId = hip
                    name = nam
                    break       
    handpad.display(arr[0,2][0], arr[0,2][1], name + ', HIP ' + hipId)
    offset_flag = False
    solveImage()

def up_down(v):
    global x
    x = x + v
    time.sleep(0.2)
    handpad.display(arr[x, y][0], arr[x, y][1], arr[x, y][2])

def left_right(v):
    global y
    y = y + v
    time.sleep(0.2)
    handpad.display(arr[x, y][0], arr[x, y][1], arr[x, y][2])

def up_down_inc(inc, sign):
    global param, arr
    arr[x, y][1] = int(10 * (float(arr[x, y][1]) + inc * sign))/10
    param[arr[x, y][0]] = float(arr[x, y][1])
    handpad.display(arr[x, y][0], arr[x, y][1], arr[x, y][2])
    update_summary()
    time.sleep(0.1)


def flip():
    global param, arr
    arr[x, y][1] = 1 - int(float(arr[x, y][1]))
    param[arr[x, y][0]] = str((arr[x, y][1]))
    handpad.display(arr[x, y][0], arr[x, y][1], arr[x, y][2])
    update_summary()
    time.sleep(0.1)

def update_summary():
    global param, arr
    arr[1, 0][0] = ("Ex:" + str(param["Exposure"]) + "  Gn:" + str(param["Gain"]))
    arr[1, 0][1] = "Test:" + str(param["Test_mode"])
    save_param()

def go_solve():
    global x, y, solve, arr
    #new_arr = nexus.read_altAz(arr)
    #arr = new_arr
    handpad.display("Image capture", "", "")
    capture()

    handpad.display("Plate solving", "", "")
    solveImage()
    if solve == True:
        handpad.display("Solved", "", "")
    else:
        handpad.display("Not Solved", "", "")
        return
    x = 0
    y = 1
    handpad.display(arr[x, y][0], arr[x, y][1], arr[x, y][2])

def solveLoop():
    global x, y, prev
    while True:
        capture()
        solveImage(True)
        handpad.display(arr[x, y][0], arr[x, y][1], arr[x, y][2])
        if up.is_pressed:
            x = y = 0
            break
        while abs(tilt.acceleration[0] - prev[0]) > threshold or abs(tilt.acceleration[1] - prev[1]) > threshold or abs(tilt.acceleration[2] - prev[2]) > threshold:
            handpad.display(arr[x, y][0], arr[x, y][1], "Scope moving")
            time.sleep(0.2)
            prev = tilt.acceleration


def reset_offset():
    global param, arr, offset
    param["d_x"] = 0
    param["d_y"] = 0
    offset_str = "0,0"
    offset = (cam[0]/2, cam[1]/2) # default centre of the image
    arr[0,2][1] = "new " + offset_str
    handpad.display(arr[x, y][0], arr[x, y][1], arr[x, y][2])
    save_param()

def get_param():
    global param, offset_str, pix_scale
    if os.path.exists(home_path + "/Solver/eFinder.config") == True:
        with open(home_path + "/Solver/eFinder.config") as h:
            for line in h:
                line = line.strip("\n").split(":")
                param[line[0]] = str(line[1])


def save_param():
    global param, cam, Testcam, camCam, dataBase, t3
    with open(home_path + "/Solver/eFinder.config", "w") as h:
        for key, value in param.items():
            h.write("%s:%s\n" % (key, value))


def home_refresh():
    global x,y
    while True:
        if x == 0 and y == 0:
            time.sleep(1)
            handpad.display(arr[x, y][0], arr[x, y][1], arr[x, y][2])
            time.sleep (0.5)

def setTilt():
    global tilt, side, param
    if param["Flip"].lower() == 'auto':
        try:
            import board
            import adafruit_adxl34x
            i2c = board.I2C()
            tilt = adafruit_adxl34x.ADXL345(i2c)
            side = 'auto'
        except:
            handpad.display("Flip set to auto","but no sensor","setting to 'right'")
            sys.exit()
    else:
        side = param["Flip"].lower()       

def findTilt():
    if side == 'auto':
        return tilt.acceleration[1]
    elif side == 'left':
        return -1
    else:
        return 1

def doButton(button):
    global gotoFlag, stop
    gotoFlag = True
    stop = False
    pin = str(button.pin)[4:]
    if pin == '26':
        time.sleep(0.4)
        if ok.is_pressed:
            exec(arr[x, y][8])
        else:
            exec(arr[x, y][7])
            stop = True
        #time.sleep(0.1)
    
    if findTilt() > 0:
        if pin == '5':
            time.sleep(0.05)
            exec(arr[x, y][3])
        elif pin == '6':
            time.sleep(0.05)
            exec(arr[x, y][4])
        elif pin == '13':
            time.sleep(0.05)
            exec(arr[x, y][5])
        elif pin == '19':
            time.sleep(0.05)
            exec(arr[x, y][6])
    else:
        if pin == '6':
            time.sleep(0.05)
            exec(arr[x, y][3])
        elif pin == '5':
            time.sleep(0.05)
            exec(arr[x, y][4])
        elif pin == '19':
            time.sleep(0.05)
            exec(arr[x, y][5])
        elif pin == '13':
            time.sleep(0.05)
            exec(arr[x, y][6])
    gotoFlag = False

def AdjBright(c):
    global param, arr
    param["Brightness"] = int(param["Brightness"]) + (c * 20)
    if param["Brightness"] > 255:
        param["Brightness"]= 255
    elif param["Brightness"] < 1:
        param["Brightness"] = 1
    handpad.bright(param["Brightness"])
    arr[2,1][2] = "Brightness " + str(param["Brightness"])
    handpad.display(arr[x, y][0], arr[x, y][1], arr[x, y][2])
    save_param()

def newBase():
    global cam, Testcam, camCam, t3
    handpad.display('Please wait','loading new','database')
    if param["Test_mode"] == '1' or param["Test_mode"] == "True":
        cam = Testcam
        t3 = Tetra3('t3_fov14_mag8')
    else:
        cam = camCam
        t3 = Tetra3(dataBase)
    left_right(-1)

def adjExposure(pk): # auto
    global param, arr
    if pk > 250:
        param['Exposure'] = (int(10 * (float(param['Exposure'])/2)))/10
    elif pk < 200:
        param['Exposure'] = (int(10*(float(param['Exposure']) * 225/pk)))/10
    update_summary()
    arr[1,1][1]= param['Exposure']

def adjExp(i): #manual
    global param
    param['Exposure'] = ('%.1f' % (float(param['Exposure']) + i*0.1))
    update_summary()
    arr[1,1][1]= param['Exposure']
    loopFocus(0)

def loopFocus(auto):
    capture()
    with Image.open("/var/tmp/solve/capture.png") as img:
        img = img.convert(mode='L')
        np_image = np.asarray(img, dtype=np.uint8)
        pk = np.max(np_image)
        if auto == 1 and (pk < 200 or pk > 250):
            adjExposure(pk)
            handpad.display('Adjusting Exposure','trying',str(param['Exposure']) + ' sec')
            loopFocus(1)
        elif auto == 1 and (200 <= pk <= 250):
            handpad.display('Exposure OK','','')
        centroids = tetra3.get_centroids_from_image(
            np_image,
            downsample=1,
            )
        if centroids.size < 1: 
            handpad.display('No stars found','','')
            time.sleep(3)
            handpad.display(arr[x, y][0], arr[x, y][1], arr[x, y][2])
            return
        
        w=16
        x1=int(centroids[0][0]-w)
        if x1 < 0:
            x1 = 0
            x2 = 2 * w
        x2=int(centroids[0][0]+w)
        if x2 > img.size[1]:
            x2 = img.size[1]
            x1 = img.size[1] - (2 * w)
        y1=int(centroids[0][1]-w)
        if y1 < 0:
            y1 = 0
            y2 = 2 * w
        y2=int(centroids[0][1]+w)
        if y2 > img.size[0]:
            y2 = img.size[0]
            y1 = img.size[0] - (2 * w)

        patch = np_image[x1:x2,y1:y2]
        imp = Image.fromarray(np.uint8(patch),'L')
        imp = imp.resize((32,32),Image.LANCZOS)
        im = imp.convert(mode='1')

        imgPlot = Image.new("1",(32,32))
        shape=[]

        for h in range (x1,x2):
            shape.append(((h-x1),int((255-np_image[h][y1+w])/8)))
        draw = ImageDraw.Draw(imgPlot)
        draw.line(shape,fill="white",width=1)

        shape=[]

        for h in range (y1,y2):
            shape.append(((h-y1),int((255-np_image[x1+w][h])/8)))

        draw = ImageDraw.Draw(imgPlot)
        draw.line(shape,fill="white",width=1)

        txtPlot = Image.new("1",(50,32))
        txt = ImageDraw.Draw(txtPlot)
        txt.text((0,0),"Pk="+ str(np.max(np_image)),font = fnt,fill='white')
        txt.text((0,10),"No="+ str(int(centroids.size/2)),font = fnt,fill='white')
        txt.text((0,20),"Ex="+str(param['Exposure']),font = fnt,fill='white')
        screen = Image.new("1",(128,32))
        screen.paste(im,box=(0,0))
        screen.paste(txtPlot,box=(35,0))
        screen.paste(imgPlot,box=(80,0))
        # create image for saving
        img = ImageEnhance.Contrast(img).enhance(5)
        combo = ImageDraw.Draw(img)
        combo.rectangle((0,0,65,65),outline='white',width=2)
        combo.rectangle((0,0,img.size[0],img.size[1]),outline='white',width=2)
        combo.text((70,5),"Peak = "+ str(np.max(np_image)) + "   Number of centroids = "+ str(int(centroids.size/2)) + "    Exposure = "+str(param['Exposure'])+ 'secs',font = fnt,fill='white')
        imp = imp.resize((64,64),Image.LANCZOS)
        imp = ImageEnhance.Contrast(imp).enhance(5)
        img.paste(imp,box=(1,1))
        img.save('/home/efinder/Solver/images/image.png')

    handpad.dispFocus(screen)

def saveImage():
    with Image.open("/var/tmp/solve/capture.png") as img:
        img = img.convert(mode='L')
    annotated = ImageDraw.Draw(img)
    annotated.rectangle((0,0,img.size[0],img.size[1]),outline='white',width=2)
    sta = datetime.datetime.now(timezone.utc)
    stamp = sta.strftime("%d%m%y_%H%M%S")
    annotated.text((4,4),stamp,font = fnt,fill='white')
    img.save(home_path + "/Solver/images/image.png")
    handpad.display(arr[x, y][0], arr[x, y][1], "image saved")

def setWifi():
    global arr, hotspot
    hotspot =  not hotspot
    if hotspot == True:
        handpad.display('Setting up','Wifi Hotspot','please wait')
        os.system("sudo nmcli device wifi hotspot ssid 'efinder' password 'efinder1'")
        arr[2,0][0] = 'ssid: efinder' 
        arr[2,0][1] = '10.42.0.1'
        handpad.display(arr[x, y][0], arr[x, y][1], arr[x,y][2])
    else:
        os.system('sudo nmcli device disconnect wlan0')
        os.system('sudo nmcli connection up preconfigured')
        handpad.display('Connecting to','Preconfigured wifi','please wait')
        time.sleep(5)
        hostname = socket.gethostname()
        addr = socket.gethostbyname(hostname + '.local')
        arr[2,0][0] = hostname
        arr[2,0][1] = 'IP:'+addr
        handpad.display(arr[x, y][0], arr[x, y][1], arr[x,y][2])
# main code starts here

coordinates = Coordinates_Lite.Coordinates()
geoloc = Location_live.Geoloc(handpad, coordinates)
geoloc.read()
setTilt()

if param["Camera"]=='ASI':
    import ASICamera_Lite
    camera = ASICamera_Lite.ASICamera(handpad)
    if param["Lens_focal_length"] == '50':
        dataBase = 't3_fov5_mag8'
        camCam = (1280,960,15.4,5.5) # width pixels,height pixels,pixel scale, width field of view
    elif param["Lens_focal_length"] == '25':
        dataBase = 't3_fov11_mag8'
        camCam = (1280,960,30.8,11)
elif param["Camera"]=='RPI':
    import RPICamera_Lite
    camera = RPICamera_Lite.RPICamera(handpad)
    if param["Lens_focal_length"] == '50':
        dataBase = 't3_fov7_mag8'
        camCam = (960,760,25.4,6.8)
    elif param["Lens_focal_length"] == '25':
        dataBase = 't3_fov14_mag8'
        camCam = (960,760,50.8,13.5)   

Testcam = (960,760,50.8,13.5)
handpad.display('Please wait','loading Tetra3','database')
if param["Test_mode"] == '1' or param["Test_mode"] == "True":
    cam = Testcam
    t3 = Tetra3('t3_fov14_mag8')
else:
    cam = camCam
    t3 = Tetra3(dataBase)
handpad.display('Done','','')

pix_x, pix_y, dxstr, dystr = dxdy2pixel(float(param["d_x"])/60, float(param["d_y"])/60)
offset_str = dxstr + "," + dystr

offset = (pix_y, pix_x) 
print(offset)
# array determines what is displayed, computed and what each button does for each screen.
# [first line,second line,third line, up button action,down...,left...,right...,select button short press action, long press action]
# empty string does nothing.
# example: left_right(-1) allows left button to scroll to the next left screen
# button texts are infact def functions
p = ""
hostname = socket.gethostname()
addr = socket.gethostbyname(hostname + '.local')

locStr = ('Geo: %2.2f , %3.2f' % (geoloc.get_lat(),geoloc.get_long()))
home = [
    "Nexus live",
    " RA:",
    "Dec:",
    "",
    "up_down(1)",
    "AdjBright(0)",
    "left_right(1)",
    "go_solve()",
    "goto()",
]
sol = [
    "No solution yet",
    "'OK' solves",
    "",
    "",
    "",
    "left_right(-1)",
    "left_right(1)",
    "go_solve()",
    "solveLoop()",
]
polar = [
    "'OK' Bright Star",
    offset_str,
    "",
    "",
    "",
    "left_right(-1)",
    "left_right(1)",
    "measure_offset()",
    "reset_offset()",
]
summary = ["","", "", "up_down(-1)", "up_down(1)", "", "left_right(1)", "go_solve()", ""]
exp = [
    "Exposure",
    param["Exposure"],
    "",
    "up_down_inc(expInc,1)",
    "up_down_inc(expInc,-1)",
    "left_right(-1)",
    "left_right(1)",
    "go_solve()",
    "saveImage()",
]
gn = [
    "Gain",
    param["Gain"],
    "",
    "up_down_inc(gainInc,1)",
    "up_down_inc(gainInc,-1)",
    "left_right(-1)",
    "left_right(1)",
    "go_solve()",
    "",
]
gotoMode = [
    "Goto++_mode",
    int(param["Goto++_mode"]),
    "",
    "flip()",
    "flip()",
    "left_right(-1)",
    "",
    "go_solve()",
    "",
]
mode = [
    "Test_mode",
    param["Test_mode"],
    "",
    "flip()",
    "flip()",
    "newBase()",
    "",
    "go_solve()",
    "",
]
status = [
    hostname, 
    "IP:"+addr,
    locStr,
    "up_down(-1)",
    "",
    "",
    "left_right(1)",
    "go_solve()",
    "setWifi()",
]
bright = [
    "Handpad",
    "Display",
    "Bright Adj " + str(param["Brightness"]),
    "AdjBright(1)",
    "AdjBright(-1)",
    "left_right(-1)",
    "",
    "go_solve()",
    "",
]
focus = [
    "Focus",
    "Utility",
    "OK to image",
    "adjExp(1)",
    "adjExp(-1)",
    "left_right(-1)",
    "",
    "loopFocus(0)",
    "loopFocus(1)",
]
arr = np.array(
    [
        [home, sol, polar, focus],
        [summary, exp, gn, mode],
        [status, bright, gotoMode, gotoMode],
    ]
)


if param["Ramdisk"].lower()=='true':
    destPath = "/var/tmp/solve/"
else:
    destPath = home_path + "/Solver/images/"

update_summary()

up = Button(5, bounce_time=0.1)
down = Button(6, bounce_time=0.1)
left = Button(13, bounce_time=0.1)
right = Button(19, bounce_time=0.1)
ok = Button(26, bounce_time=0.1)
left.when_pressed = doButton
right.when_pressed = doButton
up.when_pressed = doButton
down.when_pressed = doButton
ok.when_pressed = doButton

wifiloop = Thread(target=serveWifi)
wifiloop.start()
time.sleep(0.5)

while True:
    if x == 0 and y == 0 and gotoFlag == False:
        sta = datetime.datetime.now(timezone.utc)
        stamp = sta.strftime("%d/%m/%y %H:%M:%S")
        handpad.display('eFinder Live','Ver: '+version,stamp)
    time.sleep(0.2)
