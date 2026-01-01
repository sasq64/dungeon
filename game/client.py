import asyncio
import logging
import ssl
import struct
import sys
from asyncio import StreamReader, StreamWriter
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import msgpack
from aioquic.asyncio.client import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def log(msg: str):
    logger.info(msg)


Pass = 0
YouAre = 1
Turn = 2
MoveTo = 3
PlayerJoin = 4
PlayerLeave = 5


@dataclass
class Player:
    id: int
    x: int
    y: int
    tile: int
    color: int


class Client:

    def __init__(self):
        self.running = True
        repo_root = Path(__file__).resolve().parents[1]
        ca_path = repo_root / "server" / "server.crt"
        if not ca_path.exists():
            sys.exit(0)

        # Configure QUIC to trust the server's self-signed certificate
        self.configuration = QuicConfiguration(
            is_client=True,
            alpn_protocols=["h3"],
        )
        self.configuration.verify_mode = ssl.CERT_REQUIRED
        self.configuration.load_verify_locations(cafile=str(ca_path))
        self.connection: (
            AbstractAsyncContextManager[QuicConnectionProtocol, None] | None
        ) = None
        # self.connection: AsyncGenerator[QuicConnectionProtocol, None] | None = None

        self.target: tuple[int, int] | None = None
        self.moved_to: tuple[int, int] | None = None
        self.id = 0
        self.turn_event = asyncio.Event()
        self.writer: StreamWriter | None = None
        self.turn: int | None = None
        self.players: dict[int, Player] = {}

    def get_moved(self) -> tuple[int, int] | None:
        res = self.moved_to
        self.moved_to = None
        return res

    async def handle(self, reader: StreamReader, writer: StreamWriter):
        self.writer = writer
        try:
            logger.info("Server initiated a bidirectional stream")

            _turn = -1
            while self.running:
                data = await reader.readexactly(2)
                (sz,) = struct.unpack(">H", data)
                data = await reader.readexactly(sz)
                msg = msgpack.unpackb(data)
                if msg[0] == YouAre:
                    self.id = msg[1]
                    log(f"I AM {self.id}")
                    self.players[self.id] = Player(self.id, 1, 1, 0, 0xFFFFFF)
                elif msg[0] == Turn:
                    turn = msg[1]
                    log(f"TURN {turn}")
                    self.turn = turn
                    self.turn_event.set()
                elif msg[0] == PlayerJoin:
                    id, tile, color = msg[1:]
                    log(f"JOIN {id} {tile} {color}")
                    self.players[id] = Player(id, -1, -1, tile, color)

                elif msg[0] == MoveTo:
                    id, x, y = msg[1:]
                    if not id in self.players:
                        self.players[id] = Player(id, -1, -1, 1, 0xFFFFFF)
                    if id in self.players:
                        p = self.players[id]
                        p.x = x
                        p.y = y
                    else:
                        log(f"Unknown player {id} moved")

                    if id == self.id:
                        log(f"I moved to {x} {y}")
                        self.moved_to = (x, y)

                    log(msg)
            # Send a response back to the server
            # writer.write(b"Hello from Python client!")
            # writer.write_eof()

            logger.info("Response sent to server")
        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)

    def get_players(self) -> dict[int, Player]:
        return self.players

    def run_client(self, reader: StreamReader, writer: StreamWriter):
        _ = asyncio.create_task(self.handle(reader, writer))

    def get_new_turn(self) -> int | None:
        t = self.turn
        self.turn = None
        return t

    def move_to(self, x: int, y: int):
        if not self.writer:
            return
        d2 = msgpack.packb([3, x, y])
        print(f"PACKAGE {x} {y}")
        payload = struct.pack(">H", len(d2))
        self.writer.write(payload)
        self.writer.write(d2)

    async def quit(self):
        self.running = False
        if self.connection:
            await self.connection.__aexit__(None, None, None)
            self.connection = None

    async def connect(self):
        logger.info("Connecting to 127.0.0.1:5000...")
        self.connection = cast(
            AbstractAsyncContextManager[QuicConnectionProtocol, None],
            connect(
                "127.0.0.1",
                5000,
                configuration=self.configuration,
                stream_handler=self.run_client,
            ),
        )
        if self.connection:
            await self.connection.__aenter__()


async def main():
    client = Client()
    await client.connect()
    x = 5
    y = 5
    while True:
        await client.turn_event.wait()
        print(f"TURN {client.turn}")
        await asyncio.sleep(4.0)
        client.move_to(x, y)
        x = x + 1


if __name__ == "__main__":
    asyncio.run(main())
