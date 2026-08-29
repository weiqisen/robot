#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JetRover WebRTC 视频 agent
从本地 web_video_server 的 MJPEG 流读取帧 -> 通过 WebRTC 低延迟推送到浏览器。
信令: HTTP POST /offer  (JSON: {sdp, type, topic})  ->  返回 answer
依赖: aiortc, aiohttp, opencv-python(或系统cv2), av
作为 systemd 服务常驻; 浏览器端在 WebRTC 失败时回退 MJPEG。
"""
import asyncio, json, sys
from aiohttp import web

try:
    import cv2
    import numpy as np
    from av import VideoFrame
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
except Exception as e:
    print("缺少依赖(aiortc/aiohttp/av/cv2):", e, file=sys.stderr)
    raise

VIDEO_BASE = "http://127.0.0.1:8080/stream"
DEFAULT_TOPIC = "/depth_cam/rgb/image_raw"
PORT = 8091
pcs = set()


class MjpegCameraTrack(VideoStreamTrack):
    """从 web_video_server 的 MJPEG 流拉帧，作为 WebRTC 视频轨。"""
    def __init__(self, topic):
        super().__init__()
        url = "%s?topic=%s&type=mjpeg" % (VIDEO_BASE, topic)
        self.cap = cv2.VideoCapture(url)
        try: self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception: pass
        self.topic = topic

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        # 在线程池里读帧，避免阻塞事件循环
        ok, frame = await asyncio.get_event_loop().run_in_executor(None, self.cap.read)
        if not ok or frame is None:
            # 读失败：尝试重开
            await asyncio.sleep(0.05)
            try: self.cap.release()
            except Exception: pass
            self.cap = cv2.VideoCapture("%s?topic=%s&type=mjpeg" % (VIDEO_BASE, self.topic))
            frame = None
        if frame is None:
            frame = np.zeros((360, 640, 3), dtype='uint8')  # 黑帧占位
        vf = VideoFrame.from_ndarray(frame, format="bgr24")
        vf.pts = pts
        vf.time_base = time_base
        return vf

    def stop(self):
        super().stop()
        try: self.cap.release()
        except Exception: pass


async def offer(request):
    params = await request.json()
    topic = params.get("topic", DEFAULT_TOPIC)
    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_state():
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await pc.close(); pcs.discard(pc)

    track = MjpegCameraTrack(topic)
    pc.addTrack(track)

    await pc.setRemoteDescription(RTCSessionDescription(sdp=params["sdp"], type=params["type"]))
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return web.json_response(
        {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
        headers={"Access-Control-Allow-Origin": "*"})


async def options(request):
    return web.Response(headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"})


async def health(request):
    return web.json_response({"ok": True, "pcs": len(pcs)},
                             headers={"Access-Control-Allow-Origin": "*"})


async def on_shutdown(app):
    await asyncio.gather(*[pc.close() for pc in list(pcs)])
    pcs.clear()


def main():
    app = web.Application()
    app.router.add_post("/offer", offer)
    app.router.add_options("/offer", options)
    app.router.add_get("/health", health)
    app.on_shutdown.append(on_shutdown)
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
