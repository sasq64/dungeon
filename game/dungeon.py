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
    def __init__(self, screen: pix.Canvas):
        self.screen = screen
        sprite_path = Path("gfx/Characters")
        self.sprites = pix.load_png(
            sprite_path / "Soldier/Soldier/Soldier-Walk.png"
        ).split(cols=8, rows=1)

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

        self.interval = 0.2

        self.pos = pix.Float2(1, 1)
        self.target = self.pos

        # self.next_time = pix.get_seconds() + self.interval
        self.delta = pix.Float2.ZERO
        self.moving = 0
        self.waiting_turn = True
        self.current_turn = -1
        self.seed = 0

    def populate(self):
        # seed = 1766348969638435230
        # seed = 1766260133058949000
        random.seed(self.seed)
        size = pix.Int2(120, 75)
        self.map = Map(size)
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

    def set_tile(self, x: int, y: int, tile: int):
        self.con.put((x, y), tile + 1024)

    def set_client(self, client: Client, seed: int):
        self.client = client
        self.seed = seed
        self.populate()
        print("SETTING set_tile")
        client.set_tile = self.set_tile
        client.flush_tiles()

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

        # new_turn = self.client.get_new_turn()
        # if new_turn is not None:
        #     print(f"New turn {new_turn}")
        #     self.current_turn = new_turn
        #     self.waiting_turn = True
        if self.waiting_turn:
            target = self.pos
            if pix.was_pressed(pix.key.LEFT):
                target = self.pos + (-1, 0)
            if pix.was_pressed(pix.key.RIGHT):
                target = self.pos + (1, 0)
            if pix.was_pressed(pix.key.UP):
                target = self.pos + (0, -1)
            if pix.was_pressed(pix.key.DOWN):
                target = self.pos + (0, 1)
            if self.pos != target:
                self.target = target
                t = self.target.toi()
                self.client.move_to(t.x, t.y)
                self.waiting_turn = False
                # self.pos = self.target

        new_pos = self.client.get_moved()
        if new_pos is not None:
            print("Moved OK")
            self.pos = pix.Float2(new_pos[0], new_pos[1])
            self.target = self.pos
            self.waiting_turn = True

        arrows = 10 * 32 + 17

        if self.pos != self.target:
            d = (self.target - self.pos).toi()
            idx = arrows + d.x + d.y * 32
            img = self.tiles[idx]
            self.screen.draw(
                image=img, top_left=self.target * self.tile_size, size=img.size
            )

        for player in self.client.get_players().values():
            if player.id == self.client.id:
                continue
            if player.x >= 0:
                tile = self.tiles[player.tile]  # player.tile]
                pos = pix.Float2(player.x, player.y) * self.tile_size
                self.screen.draw_color = player.color
                self.screen.draw(image=tile, top_left=pos, size=tile.size)
                self.screen.draw_color = pix.color.WHITE

        pos = (self.pos * self.tile_size) - (40, 40)
        frame = (pos.x / 10) % 8
        sprite = self.sprites[int(frame) % 8]
        self.screen.draw(image=sprite, top_left=pos, size=sprite.size)


async def main():
    client = Client()
    await client.connect()
    screen = pix.open_display(size=(1280, 1024), full_screen=False, id="dungeon")

    game = Game(screen)
    seed = await client.get_seed()
    game.set_client(client, seed)

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
