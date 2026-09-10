#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JetRover WebRTC 视频 agent
标注抓取图直接订阅 ROS，普通相机仍从 web_video_server 的 MJPEG 流读取。
信令: HTTP POST /offer  (JSON: {sdp, type, topic})  ->  返回 answer
依赖: aiortc, aiohttp, opencv-python(或系统cv2), av
作为 systemd 服务常驻; 浏览器端在 WebRTC 失败时回退 MJPEG。
"""
import asyncio, json, sys, threading
from aiohttp import web

try:
    import cv2
    import numpy as np
    from av import VideoFrame
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
except Exception as e:
    print("缺少依赖(aiortc/aiohttp/av/cv2):", e, file=sys.stderr)
    raise

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
    from sensor_msgs.msg import Image
except Exception:
    rclpy = None
    Node = object

VIDEO_BASE = "http://127.0.0.1:8080/stream"
VISION_VIDEO_BASE = "http://127.0.0.1:8082/stream"
DEFAULT_TOPIC = "/depth_cam/rgb/image_raw"
PORT = 8091
pcs = set()
vision_bridge = None


class RosVisionBridge(Node):
    """只缓存最新的标注图，不让慢客户端把 ROS 图像队列堆起来。"""
    def __init__(self):
        super().__init__('webrtc_vision_bridge')
        self.cv = threading.Condition()
        self.frame, self.seq = None, 0
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         history=HistoryPolicy.KEEP_LAST)
        self.create_subscription(Image, '/snack_butler/image_result', self.on_image, qos)

    def on_image(self, msg):
        try:
            raw = np.frombuffer(msg.data, dtype=np.uint8)
            frame = raw.reshape(msg.height, msg.width, 3).copy()
            if str(msg.encoding).lower() == 'rgb8':
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            with self.cv:
                self.frame, self.seq = frame, self.seq + 1
                self.cv.notify_all()
        except Exception:
            pass

    def latest_after(self, previous):
        with self.cv:
            self.cv.wait_for(lambda: self.seq != previous, timeout=.12)
            return self.frame, self.seq


class RosVisionTrack(VideoStreamTrack):
    """直取 ROS 最新帧，去掉 ROS -> MJPEG -> OpenCV 的中间缓存。"""
    def __init__(self, bridge):
        super().__init__()
        self.bridge, self.seq = bridge, -1

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        frame, self.seq = await asyncio.get_event_loop().run_in_executor(
            None, self.bridge.latest_after, self.seq)
        if frame is None:
            frame = np.zeros((360, 640, 3), dtype='uint8')
        vf = VideoFrame.from_ndarray(frame, format='bgr24')
        vf.pts, vf.time_base = pts, time_base
        return vf


class MjpegCameraTrack(VideoStreamTrack):
    """从 web_video_server 的 MJPEG 流拉帧，作为 WebRTC 视频轨。"""
    def __init__(self, topic):
        super().__init__()
        self.base = VISION_VIDEO_BASE if topic == '/snack_butler/image_result' else VIDEO_BASE
        url = "%s?topic=%s&type=mjpeg" % (self.base, topic)
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
            self.cap = cv2.VideoCapture("%s?topic=%s&type=mjpeg" % (self.base, self.topic))
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

    track = (RosVisionTrack(vision_bridge)
             if topic == '/snack_butler/image_result' and vision_bridge is not None
             else MjpegCameraTrack(topic))
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
    global vision_bridge
    if rclpy is not None:
        try:
            rclpy.init()
            vision_bridge = RosVisionBridge()
            threading.Thread(target=rclpy.spin, args=(vision_bridge,), daemon=True).start()
        except Exception as e:
            print('ROS 标注图直连不可用，保留 MJPEG 回退:', e, file=sys.stderr)
            vision_bridge = None
    app = web.Application()
    app.router.add_post("/offer", offer)
    app.router.add_options("/offer", options)
    app.router.add_get("/health", health)
    app.on_shutdown.append(on_shutdown)
    try:
        web.run_app(app, host="0.0.0.0", port=PORT, print=None)
    finally:
        if vision_bridge is not None:
            vision_bridge.destroy_node()
        if rclpy is not None and rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
