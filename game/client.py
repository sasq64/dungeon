import asyncio
import logging
import ssl
import sys
from asyncio import StreamReader, StreamWriter
from pathlib import Path

import msgpack
from aioquic.asyncio.client import connect
from aioquic.quic.configuration import QuicConfiguration

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class Client:

    async def handle(self, reader: StreamReader, writer: StreamWriter):
        try:
            logger.info("Server initiated a bidirectional stream")

            unpacker = msgpack.Unpacker(raw=False)

            turn = -1
            while self.running:
                data = await reader.read(4096)
                unpacker.feed(data)
                for msg in unpacker:
                    if msg[0] == 2:
                        turn = msg[1]
                        d2 = msgpack.packb([0])
                        print("WRITE")
                        writer.write(d2)
                    print(msg)
            # Send a response back to the server
            # writer.write(b"Hello from Python client!")
            # writer.write_eof()

            logger.info("Response sent to server")
        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)

    def run_client(self, reader: StreamReader, writer: StreamWriter):
        _ = asyncio.create_task(self.handle(reader, writer))

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

    def quit(self):
        self.running = False

    def connect(self):
        logger.info("Connecting to 127.0.0.1:5000...")
        return connect(
            "127.0.0.1",
            5000,
            configuration=self.configuration,
            stream_handler=self.run_client,
        )


async def main():
    client = Client()
    await client.connect()


if __name__ == "__main__":
    asyncio.run(main())
