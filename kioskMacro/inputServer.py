
#!/usr/bin/env python3
"""
inputServer.py
- ws://localhost:8080/api/chat 에서 WebSocket 서버 실행
- 매크로(run_voice.py)가 마이크 활성화 시 전송하는 음성 바이너리 프레임을 수신하여
  단순히 "받았다" 로그만 출력

필요 패키지: websockets (requirements에 포함)
실행: python inputServer.py
"""

import asyncio
import json
import logging
import websockets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("inputServer")

async def handle_client(websocket):
    client = id(websocket)
    # websockets 11 기준으로 path 속성이 제공될 수 있어 안전 접근
    path = getattr(websocket, "path", "(unknown)")
    logger.info(f"[WS] client connected: id={client}, path={path}")
    try:
        async for message in websocket:
            if isinstance(message, bytes):
                logger.info(f"[WS] audio frame received: {len(message)} bytes")
            else:
                # 텍스트 메시지(예: {"type":"start"})
                try:
                    data = json.loads(message)
                    logger.info(f"[WS] text message: {data}")
                except json.JSONDecodeError:
                    logger.info(f"[WS] text message (raw): {message}")
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"[WS] client disconnected: id={client}")
    except Exception as e:
        logger.exception(f"[WS] error: {e}")

async def main():
    host = "localhost"
    port = 8080
    # 경로가 /api/chat 이어도 포트 단위로 수락됨 (경로는 핸들러에서 확인만)
    logger.info(f"[WS] starting input server at ws://{host}:{port}/chat")
    async with websockets.serve(handle_client, host, port):
        logger.info("[WS] server running... (Ctrl+C to stop)")
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[WS] server stopped")
