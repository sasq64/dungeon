import asyncio
from asyncio import StreamReader, StreamWriter
import logging
import ssl
import sys
from pathlib import Path
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def handle(reader: StreamReader, writer: StreamWriter):
    try:
        logger.info("Server initiated a bidirectional stream")

        # Read data from the stream
        data = await reader.read(1024)
        logger.info(f"Received {len(data)} bytes: {data}")
        logger.info(f"Data content: {list(data)}")

        # Send a response back to the server
        writer.write(b"Hello from Python client!")
        writer.write_eof()

        logger.info("Response sent to server")
    except Exception as e:
        logger.error(f"Stream error: {e}", exc_info=True)


async def main():
    repo_root = Path(__file__).resolve().parents[1]
    ca_path = repo_root / "server" / "server.crt"
    if not ca_path.exists():
        sys.exit(0)

    # Configure QUIC to trust the server's self-signed certificate
    configuration = QuicConfiguration(
        is_client=True,
        alpn_protocols=["h3"],
    )
    configuration.verify_mode = ssl.CERT_REQUIRED
    configuration.load_verify_locations(cafile=str(ca_path))

    logger.info("Connecting to 127.0.0.1:5000...")

    try:
        async with connect(
            "127.0.0.1",
            5000,
            configuration=configuration,
            # stream_handler=handle_stream,
            stream_handler=lambda r, w: (asyncio.create_task(handle(r, w)), None)[1],
        ) as client:
            logger.info("Connected to server")
            logger.info("Waiting for server to initiate streams...")

            # Keep the connection alive to receive streams
            await asyncio.sleep(500)

    except Exception as e:
        logger.error(f"Connection error: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
