import time as t
import pyautogui as pg
import keyboard

while True:
    if keyboard.is_pressed("q"):
        pos = pg.position()
        print(f'"x": {pos.x}, "y": {pos.y}')
        t.sleep(0.1)
    if keyboard.is_pressed("e"):
        break
