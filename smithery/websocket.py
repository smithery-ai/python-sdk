import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from urllib.parse import urlparse, urlunparse

import anyio
from pydantic import ValidationError
from websockets.asyncio.client import connect as ws_connect
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from websockets.typing import Subprotocol

import mcp.types as types

logger = logging.getLogger(__name__)


def convert_to_websocket_url(url: str) -> str:
    """
    Convert an HTTP URL to a WebSocket URL if needed.
    
    Args:
        url (str): The URL to convert
        
    Returns:
        str: The WebSocket URL (ws:// or wss://)
    """
    parsed = urlparse(url)
    if parsed.scheme in ('http', 'https'):
        scheme = 'wss' if parsed.scheme == 'https' else 'ws'
        return urlunparse((scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    return url


@asynccontextmanager
async def websocket_client(url: str) -> AsyncGenerator[
    tuple[
        MemoryObjectReceiveStream[types.JSONRPCMessage | Exception],
        MemoryObjectSendStream[types.JSONRPCMessage],
    ],
    None,
]:
    """
    WebSocket client transport for MCP, symmetrical to the server version.

    Connects to 'url' using the 'mcp' subprotocol, then yields:
        (read_stream, write_stream)

    - read_stream: As you read from this stream, you'll receive either valid
      JSONRPCMessage objects or Exception objects (when validation fails).
    - write_stream: Write JSONRPCMessage objects to this stream to send them
      over the WebSocket to the server.
    """
    # Convert HTTP URL to WebSocket URL if needed
    ws_url = convert_to_websocket_url(url)

    # Create two in-memory streams:
    # - One for incoming messages (read_stream, written by ws_reader)
    # - One for outgoing messages (write_stream, read by ws_writer)
    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    # Connect using websockets, requesting the "mcp" subprotocol
    async with ws_connect(ws_url, subprotocols=[Subprotocol("mcp")]) as ws:
        async def ws_reader():
            """
            Reads text messages from the WebSocket, parses them as JSON-RPC messages,
            and sends them into read_stream_writer.
            """
            try:
                async with read_stream_writer:
                    async for raw_text in ws:
                        try:
                            message = types.JSONRPCMessage.model_validate_json(raw_text)
                            await read_stream_writer.send(message)
                        except ValidationError as exc:
                            # If JSON parse or model validation fails, send the exception
                            await read_stream_writer.send(exc)
            except (anyio.ClosedResourceError, Exception):
                await ws.close()

        async def ws_writer():
            """
            Reads JSON-RPC messages from write_stream_reader and sends them to the server.
            """
            try:
                async with write_stream_reader:
                    async for message in write_stream_reader:
                        # Convert to a dict, then to JSON
                        msg_dict = message.model_dump(
                            by_alias=True, mode="json", exclude_none=True
                        )
                        await ws.send(json.dumps(msg_dict))
            except (anyio.ClosedResourceError, Exception):
                await ws.close()

        async with anyio.create_task_group() as tg:
            # Start reader and writer tasks
            tg.start_soon(ws_reader)
            tg.start_soon(ws_writer)

            # Yield the receive/send streams
            yield (read_stream, write_stream)

            # Once the caller's 'async with' block exits, we shut down
            tg.cancel_scope.cancel()
