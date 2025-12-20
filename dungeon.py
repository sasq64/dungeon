from pathlib import Path
from typing import MutableSet

import pixpy as pix
import random
import time

from generate import Map

screen = pix.open_display(size=(1280, 1024), full_screen=True, id="dungeon")

sprite_path = Path("gfx/Characters")
sprites = pix.load_png(sprite_path / "Soldier/Soldier/Soldier-Walk.png").split(
    cols=8, rows=1
)

s = 32.0
tile_size = pix.Float2(16, 16)

tiles = pix.load_png("gfx/mono_tiles.png").split(size=tile_size)
con = pix.Console(cols=128, rows=128, tile_size=tile_size)
con.set_color(pix.color.GREEN, pix.color.DARK_GREY)
con.set_tile_images(1024, tiles)
frame = 0
pos = pix.Float2(100, 100)
target = pos

# con.set_tiles([ord('#')] * 128 * 128)

size = pix.Int2(128, 128)
map = Map(size)

# map.join_rooms()

for p in con.grid_size.grid_coordinates():
    con.put(p, 0x20)

used: MutableSet[int] = set()
for y in range(128):
    for x in range(128):
        t = map.tiles[x + 128 * y]
        if t > 0:
            con.put((x, y), 1024 + 3 * 32)

colors = [
    pix.color.WHITE,
    pix.color.LIGHT_BLUE,
    pix.color.LIGHT_RED,
    pix.color.LIGHT_GREY,
    pix.color.ORANGE,
]
for t, room in enumerate(map.rooms):
    for u, r in enumerate(room.rects):
        con.set_color(colors[u % 5], pix.color.BLACK)
        con.put((r.x, r.y), 0x30 + t // 10)
        con.put((r.x + 1, r.y), 0x30 + t % 10)


# for p in con.grid_size.grid_coordinates():
#    con.put(p, 1024 + 3 * 32)

## Movement rules:
## target = target square
## when moving

interval = 0.2

next_time = screen.seconds + interval
delta = pix.Float2.ZERO

seed = time.time_ns()
random.seed(seed)
print(seed)

while pix.run_loop():
    screen.clear(0xFF0000FF)
    screen.draw(con, size=con.size)

    p = pix.get_pointer().toi() // tile_size.toi()
    t = map.tiles[p.x + 128 * p.y] - 10
    con.cursor_pos = (0, 0)
    con.set_color(pix.color.WHITE, pix.color.RED)
    con.write(f"X {p.x:02} Y {p.y:02}  ")
    if t >= 0:
        room = map.rooms[t]
        for c in room.connections:
            r2 = map.rooms[c]
            p0 = pix.Float2(r2.rects[0].x, r2.rects[0].y) * tile_size
            screen.rect(p0, size=(32, 32))

    time = screen.seconds
    tick = False
    if time >= next_time:
        tick = True
        pos = target
        next_time = time + interval

    sprite = sprites[int(frame) % 8]
    screen.draw(image=sprite, top_left=pos + (8, 2), size=sprite.size * 2)

    if tick:
        if pix.is_pressed(pix.key.LEFT):
            target = pos + (-s, 0)
        if pix.is_pressed(pix.key.RIGHT):
            target = pos + (s, 0)
        if pix.is_pressed(pix.key.UP):
            target = pos + (0, -s)
        if pix.is_pressed(pix.key.DOWN):
            target = pos + (0, s)
        delta = target - pos

    pos = pos + (delta * screen.delta / interval)

    frame = (pos.x / 10) % 8

    screen.swap()
