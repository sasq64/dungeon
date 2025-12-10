from pathlib import Path

import pixpy as pix

screen = pix.open_display(size=(1280, 1024))

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

#con.set_tiles([ord('#')] * 128 * 128)

for p in con.grid_size.grid_coordinates():
    con.put(p, 1024 + 3*32)

## Movement rules:
## target = target square
## when moving

interval = 0.2

next_time = screen.seconds + interval
delta = pix.Float2.ZERO

while pix.run_loop():
    screen.clear(0xff0000ff)
    screen.draw(con, size=con.size * 2)

    time = screen.seconds
    tick = False
    if time >= next_time:
        tick = True
        pos = target
        next_time = time + interval

    sprite = sprites[int(frame) % 8]
    screen.draw(image=sprite, top_left=pos + (8,2), size=sprite.size * 2)

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

