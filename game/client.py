import asyncio
import logging
import ssl
import struct
import sys
from asyncio import StreamReader, StreamWriter
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager
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

    def get_moved(self) -> tuple[int, int] | None:
        res = self.moved_to
        self.moved_to = None
        return res

    async def handle(self, reader: StreamReader, writer: StreamWriter):
        try:
            logger.info("Server initiated a bidirectional stream")

            _turn = -1
            while self.running:
                data = await reader.readexactly(2)
                (sz,) = struct.unpack(">H", data)
                print(f"LEN {sz} packet")
                data = await reader.readexactly(sz)
                msg = msgpack.unpackb(data)
                if msg[0] == 1:
                    self.id = msg[1]
                    print(f"I am {self.id}")

                elif msg[0] == 2:  # TURN
                    turn = msg[1]
                    print(f"TURN {turn}")
                    d2 = []
                    if self.target:
                        d2 = msgpack.packb([3, self.target[0], self.target[1]])
                        self.target = None
                    else:
                        d2 = msgpack.packb([0])
                    print("WRITE")
                    payload = struct.pack(">H", len(d2))
                    writer.write(payload)
                    writer.write(d2)
                elif msg[0] == 3:  # MOVE
                    id = msg[1]
                    x = msg[2]
                    y = msg[3]
                    self.moved_to = (x, y)

                    print(msg)
            # Send a response back to the server
            # writer.write(b"Hello from Python client!")
            # writer.write_eof()

            logger.info("Response sent to server")
        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)

    def run_client(self, reader: StreamReader, writer: StreamWriter):
        _ = asyncio.create_task(self.handle(reader, writer))

    def move_to(self, x: int, y: int):
        self.target = (x, y)

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
            print("ENTER")
            await self.connection.__aenter__()


async def main():
    client = Client()
    await client.connect()
    await asyncio.sleep(5000)


if __name__ == "__main__":
    asyncio.run(main())
