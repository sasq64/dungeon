import asyncio
import random
import time
from pathlib import Path
from typing import Final

import pixpy as pix

from client import Client
from generate import Map

# from collections.abc import MutableSet


class Game:
    def __init__(self, client: Client, screen: pix.Canvas):
        self.screen = screen
        sprite_path = Path("gfx/Characters")
        self.sprites = pix.load_png(
            sprite_path / "Soldier/Soldier/Soldier-Walk.png"
        ).split(cols=8, rows=1)

        self.client = client

        # s = 32.0
        self.tile_size = pix.Float2(16, 16)

        self.tiles = pix.load_png("gfx/mono_tiles.png").split(size=self.tile_size)
        self.con = pix.Console(cols=128, rows=128, tile_size=self.tile_size)
        self.con.set_color(pix.color.GREEN, pix.color.DARK_GREY)
        self.con.set_tile_images(1024, self.tiles)
        self.frame = 0
        self.pos: pix.Float2 = pix.Float2(100, 100)
        self.target: pix.Float2 = self.pos

        # con.set_tiles([ord('#')] * 128 * 128)

        self.seed = time.time_ns()
        # seed = 1766348969638435230
        # seed = 1766260133058949000
        random.seed(self.seed)

        size = pix.Int2(120, 75)
        self.map = Map(size)

        print(self.seed)
        # map.join_rooms()

        for p in self.con.grid_size.grid_coordinates():
            self.con.put(p, 1024 + 3 * 32)

        for xy in size.grid_coordinates():
            t = self.map.tiles[xy.x + size.x * xy.y]
            if t > 0:
                self.con.put(xy, 0x20)

        colors = [
            pix.color.WHITE,
            pix.color.LIGHT_BLUE,
            pix.color.LIGHT_RED,
            pix.color.LIGHT_GREY,
            pix.color.ORANGE,
        ]
        for t, room in enumerate(self.map.rooms):
            for u, r in enumerate(room.rects):
                self.con.set_color(colors[u % 5], pix.color.BLACK)
                self.con.put((r.x, r.y), 0x30 + t // 10)
                self.con.put((r.x + 1, r.y), 0x30 + t % 10)

        self.interval = 0.2

        self.xy = self.map.rooms[9].rects[0].center
        self.pos = self.xy.tof()
        self.target = self.pos

        self.next_time = pix.get_display().seconds + self.interval
        self.delta = pix.Float2.ZERO
        self.moving = 0

    def update(self):
        self.screen.draw(self.con, size=self.con.size)

        p = pix.get_pointer().toi() // self.tile_size.toi()
        size = self.map.size
        if p.x < size.x and p.y < size.y:
            t = self.map.tiles[p.x + size.x * p.y] - 10
            self.con.cursor_pos = (0, 0)
            self.con.set_color(pix.color.WHITE, pix.color.RED)
            self.con.write(f"X {p.x:02} Y {p.y:02}  ")
            if t >= 0:
                room = self.map.rooms[t]
                for c in room.connections:
                    r2 = self.map.rooms[c]
                    p0 = pix.Float2(r2.rects[0].x, r2.rects[0].y) * self.tile_size
                    self.screen.rect(p0, size=(32, 32))

        time = pix.get_display().seconds
        tick = False
        if time >= self.next_time:
            tick = True
            # self.pos = self.target
            self.next_time = time + self.interval

        pos = self.pos * self.tile_size
        if self.moving > 0:
            c = 1.0 - (self.moving / 16)
            d = (self.target - self.pos) * self.tile_size * c
            pos += d
            self.moving -= 1
            if self.moving == 0:
                print("ARRIVE")
                self.pos = self.target
                if pix.is_pressed(pix.key.LEFT):
                    self.target = self.pos + (-1, 0)
                if pix.is_pressed(pix.key.RIGHT):
                    self.target = self.pos + (1, 0)
                if pix.is_pressed(pix.key.UP):
                    self.target = self.pos + (0, -1)
                if pix.is_pressed(pix.key.DOWN):
                    self.target = self.pos + (0, 1)
        else:
            if pix.was_pressed(pix.key.LEFT):
                self.target = self.pos + (-1, 0)
            if pix.was_pressed(pix.key.RIGHT):
                self.target = self.pos + (1, 0)
            if pix.was_pressed(pix.key.UP):
                self.target = self.pos + (0, -1)
            if pix.was_pressed(pix.key.DOWN):
                self.target = self.pos + (0, 1)
        if self.moving == 0 and self.pos != self.target:
            print("DIFF")
            t = self.target.toi()
            self.client.move_to(t.x, t.y)
            self.moving = 16

        frame = (pos.x / 10) % 8
        sprite = self.sprites[int(frame) % 8]

        self.screen.draw(image=sprite, top_left=pos, size=sprite.size)

        # s = 16.0
        # if tick:
        #     if pix.is_pressed(pix.key.LEFT):
        #         self.target = self.pos + pix.Float2(-s, 0)
        #     if pix.is_pressed(pix.key.RIGHT):
        #         self.target = self.pos + pix.Float2(s, 0)
        #     if pix.is_pressed(pix.key.UP):
        #         self.target = self.pos + pix.Float2(0, -s)
        #     if pix.is_pressed(pix.key.DOWN):
        #         self.target = self.pos + pix.Float2(0, s)
        #     self.delta = self.target - self.pos
        #
        # self.pos = self.pos + (self.delta * pix.get_display().delta / self.interval)


async def main():
    client = Client()
    await client.connect()
    screen = pix.open_display(size=(1280, 1024), full_screen=False, id="dungeon")

    game = Game(client, screen)

    while pix.run_loop():
        screen.clear(0xFF0000FF)
        game.update()
        await asyncio.sleep(0.002)
        if pix.was_pressed(pix.key.ESCAPE):
            break
        screen.swap()
    print("EXIT")
    await client.quit()


if __name__ == "__main__":
    asyncio.run(main())
