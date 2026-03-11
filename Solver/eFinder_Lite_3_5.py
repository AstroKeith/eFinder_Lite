#!/usr/bin/python3

# Program to implement an eFinder (electronic finder) on motorised Alt Az telescopes
# Copyright (C) 2022 Keith Venables.
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# This variant is customised for ZWO ASI ccds as camera, Nexus DSC as telescope interface
# It requires astrometry.net installed
import os
import sys
if len(sys.argv) > 1:
    print ('Killing running version')
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
version = "Lite_3_5"
handpad = Display_Lite.Handpad(version,param["Flip"])
handpad.display('ScopeDog eFinder','Lite','Version '+ version)
import time
import math
from PIL import Image, ImageDraw,ImageFont, ImageEnhance
import re
from skyfield.api import Star
import numpy as np
np.math = math
import Nexus_Lite
import Coordinates_Lite
from gpiozero import Button
from tetra3 import Tetra3, cedar_detect_client
cedar_detect = cedar_detect_client.CedarDetectClient()
import tetra3
import csv
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
aligning = False
dispBright = 241

c= 0
fnt = ImageFont.truetype(home_path+"/Solver/text.ttf",8)

if len(sys.argv) > 1:
    os.system('pkill -9 -f eFinder_Lite.py') # stops the autostart eFinder program running
try:
    os.mkdir("/var/tmp/solve")
except:
    pass

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


def solveImage():
    global offset_flag, solve, solvedPos, elapsed_time, solved_radec, solved_altaz, firstStar, solution, cam, stars

    start_time = time.time()
    handpad.display("Started solving", "", "")
    captureFile = destPath + "capture.png"
    with Image.open(captureFile).convert('L') as img:
        centroids = cedar_detect.extract_centroids(
            img,
            max_size=10,
            sigma=8,
            use_binned=False,
            )
        stars = str(len(centroids))
        if len(centroids) < 30:
            handpad.display("Bad image","only"+ stars," centroids")
            solve = False
            time.sleep(3)
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
        nexus.get_location().at(coordinates.get_ts().now()).observe(solved)
    )  # now at Jnow and current location

    ra, dec, d = solvedPos.apparent().radec(coordinates.get_ts().now())
    solved_radec = ra.hours, dec.degrees
    solved_altaz = coordinates.conv_altaz(nexus, *(solved_radec))
    arr[0, 1][0] = "Sol: RA " + coordinates.hh2dms(solved_radec[0])
    arr[0, 1][1] = "   Dec " + coordinates.dd2dms(solved_radec[1])
    arr[0, 1][2] = stars + " stars in " + elapsed_time + " s"
    solve = True

def align():
    global aligning, align_count
    if nexus.is_aligned() == False: # need to do the 2* alignment procedure.
        aligning = True
        if align_count == 0: # need to prepare to do first star
            handpad.display('Nexus 2 star align','Point scope','then press OK')
            align_count = 1
            #time.sleep(5)
            return
        elif align_count == 1: # now do the first star & prepare for next
            doAlign()
            handpad.display('First star done','Move scope','then press OK')
            align_count = 2
            return
        elif align_count == 2: # now do 2nd star
            doAlign()
            p = nexus.get(":GW#")
            if p[1] == "T": 
                arr[2,0][1] = "Nexus is aligned"
                nexus.set_aligned(True)
                handpad.display('Nexus 2 star align','Successful','')
                time.sleep(5)
                aligning = False
            else:
                handpad.display('Align unsuccessful','Reboot Nexus','Then try again')
                time.sleep(5)
                aligning = False
    else:
        doAlign()
        handpad.display(arr[x, y][0], arr[x, y][1], arr[x, y][2])

def doAlign():
    global align_count, solve, sync_count, param, offset_flag, arr, x,y, cam
    new_arr = nexus.read_altAz(arr)
    arr = new_arr
    capture()
    solveImage()
    if solve == False:
        handpad.display(arr[x, y][0], "Solved Failed", arr[x, y][2])
        return
    align_ra = ":Sr" + coordinates.dd2dms((solved_radec)[0]) + "#"
    align_dec = ":Sd" + coordinates.dd2aligndms((solved_radec)[1]) + "#"
    valid = nexus.get(align_ra)
    if valid == "0":
        handpad.display(arr[x, y][0], "Invalid position", arr[x, y][2])
        time.sleep(3)
        return
    valid = nexus.get(align_dec)
    if valid == "0":
        handpad.display(arr[x, y][0], "Invalid position", arr[x, y][2])
        time.sleep(3)
        return
    reply = nexus.get(":CM#")
    nexus.read_altAz(arr)
   

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
    if drive == True:
        arr[1, 0][1] = "Test:" + str(param["Test_mode"]) + " GoTo++:" + str(param["Goto++_mode"])
    else:
        arr[1, 0][1] = "Test:" + str(param["Test_mode"])
    save_param()

def go_solve():
    global x, y, solve, arr
    new_arr = nexus.read_altAz(arr)
    arr = new_arr
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

def gotoDistant():
    nexus.read_altAz(arr)
    nexus_radec = nexus.get_radec()
    deltaRa = abs(nexus_radec[0]-goto_radec[0])*15
    if deltaRa > 180:
        deltaRa = abs(deltaRa - 360)
    deltaDec = abs(nexus_radec[1]-goto_radec[1])
    if deltaRa+deltaDec > 5:
        return(True)
    else:
        return(False)

def readTarget():
    global goto_radec,goto_ra,goto_dec
    goto_ra = nexus.get(":Gr#")
    if (goto_ra[0:2] == "00" and goto_ra[3:5] == "00"):  # not a valid goto target set yet.
        handpad.display("no GoTo target","set yet","")
        return
    goto_dec = nexus.get(":Gd#")
    ra = goto_ra.split(":")
    dec = re.split(r"[:*]", goto_dec)
    goto_radec = (float(ra[0]) + float(ra[1]) / 60 + float(ra[2]) / 3600), math.copysign(
            abs(abs(float(dec[0])) + float(dec[1]) / 60 + float(dec[2]) / 3600),
            float(dec[0]))

def goto():
    global gotoFlag
    if drive == False:
        handpad.display("No Drive", "Connected", "")
        return
    handpad.display("Starting", "GoTo", "")
    gotoFlag = True
    readTarget()
    if gotoDistant():
        if sDog == True:     
            nexus.write(":Sr" + goto_ra + "#")
            nexus.write(":Sd" + goto_dec + "#")
            reply = nexus.get(":MS#")
        else:    
            gotoStr = '%s%06.3f %+06.3f' %("g",goto_radec[0],goto_radec[1])
            servocat.send(gotoStr)
        handpad.display("Performing", " GoTo", "")
        time.sleep(1)
        gotoStopped()
        handpad.display("Finished", " GoTo", "")
        go_solve()
        if int(param["Goto++_mode"]) == 0:
            return
    handpad.display("Attempting", " GoTo++", "")
    align() # close, so local sync scope to true RA & Dec
    if sDog == True:
        nexus.write(":Sr" + goto_ra + "#")
        nexus.write(":Sd" + goto_dec + "#")
        reply = nexus.get(":MS#")
    else:
        gotoStr = '%s%06.3f %+06.3f' %("g",goto_radec[0],goto_radec[1])
        servocat.send(gotoStr)
    gotoStopped()
    gotoFlag = False
    handpad.display("Finished", " GoTo++", "")
    go_solve()


def getRadec():
    nexus.read_altAz(None)
    return(nexus.get_radec())

def gotoStopped():
    radecNow = getRadec()
    while True:
        time.sleep(2)
        radec = getRadec()
        if (abs(radecNow[0] - radec[0])*15 < 0.01) and (abs(radecNow[1] - radec[1]) < 0.01):
            return
        else:
            radecNow = radec

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
        while x ==0 and y==0:
            nexus.read_altAz(arr)
            radec = nexus.get_radec()
            ra = coordinates.hh2dms(radec[0])
            dec = coordinates.dd2dms(radec[1])
            handpad.display('Nexus live',' RA:  '+ra, 'Dec: '+dec)
            time.sleep(0.5)
        else:
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
    param['Exposure'] = ('%.1f' % (float(param['Exposure']) + i*expInc))
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
            y2 =2 * w
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

# main code starts here

coordinates = Coordinates_Lite.Coordinates()
nexus = Nexus_Lite.Nexus(handpad, coordinates)
nexus.read()
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
home = [
    "Nexus live",
    " RA:",
    "Dec:",
    "",
    "up_down(1)",
    "AdjBright(0)",
    "left_right(1)",
    "align()",
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
    "saveImage()",
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
summary = ["", "", "", "up_down(-1)", "up_down(1)", "", "left_right(1)", "go_solve()", ""]
exp = [
    "Exposure",
    param["Exposure"],
    "",
    "up_down_inc(expInc,1)",
    "up_down_inc(expInc,-1)",
    "left_right(-1)",
    "left_right(1)",
    "go_solve()",
    "",
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
    "Nexus via " + nexus.get_nexus_link(),
    "Nex align " + str(nexus.is_aligned()),
    param["Camera"]+ ' with ' + str(param["Lens_focal_length"]) + 'mm lens',
    "up_down(-1)",
    "",
    "",
    "left_right(1)",
    "go_solve()",
    "",
]
bright = [
    "Handpad",
    "Display",
    "Bright Adj " + str(param["Brightness"]),
    "AdjBright(1)",
    "AdjBright(-1)",
    "left_right(-1)",
    "left_right(1)",
    "go_solve()",
    "",
]
focus = [
    "Focus",
    "Utility",
    "'OK' to image",
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

new_arr = nexus.read_altAz(arr)
arr = new_arr

if param["Drive"].lower()=='servocat':
    import ServoCat
    servocat = ServoCat.ServoCat()
    sDog = False
    print('ServoCat mode')
    drive = True
    arr[2,0][1] = "ServoCat mode"
elif param["Drive"].lower()=='scopedog':
    print('ScopeDog mode')
    drive = True
    arr[2,0][1] = "ScopeDog mode"
elif param["Drive"].lower()=='sitech':
    print('SiTech mode')
    drive = True
    arr[2,0][1] = "SiTech mode" 
else:
    print('No drive')
    arr[2,0][1] = "No drive"
    drive = False
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

while True:
    if x == 0 and y == 0 and gotoFlag == False and aligning == False:
        nexus.read_altAz(arr)
        radec = nexus.get_radec()
        if nexus.is_aligned() == True:
            tick = "Aligned"
        else:
            tick = "Not Aligned"
        if param["Test_mode"] == '1':
            tick = 'test mode'
        ra = coordinates.hh2dms(radec[0])
        dec = coordinates.dd2dms(radec[1])
        handpad.display('Nexus:  '+tick,' RA:  '+ra, 'Dec: '+dec)
        time.sleep(0.2)
    time.sleep(0.2)
