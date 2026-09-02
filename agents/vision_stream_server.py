#!/usr/bin/env python3
"""独立视觉 MJPEG 桥：只服务视觉抓取图像，重启不影响底盘/导航。"""
import threading
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image

PORT = 8082


class VideoHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

class Bridge(Node):
    def __init__(self):
        super().__init__('vision_stream_server')
        self.lock, self.jpeg = threading.Lock(), None
        self.frames = 0
        self.seen = 0
        # snack_butler publishes reliably; match it exactly.  Some DDS versions
        # on the Jetson fail to deliver a reliable publisher to a best-effort
        # Python subscriber even though the profile is nominally compatible.
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         history=HistoryPolicy.KEEP_LAST)
        self.create_subscription(Image, '/snack_butler/image_result', self.on_image, qos)
        self.get_logger().info('subscribed to /snack_butler/image_result')

    def on_image(self, msg):
        try:
            self.seen += 1
            if self.seen == 1:
                self.get_logger().info('received first image (%dx%d %s)' % (msg.width, msg.height, msg.encoding))
            img = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
            ok, data = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                with self.lock: self.jpeg = data.tobytes()
                self.frames += 1
                if self.frames == 1 or self.frames % 90 == 0:
                    self.get_logger().info('encoded frame #%d (%d bytes)' % (self.frames, len(self.jpeg)))
        except Exception as e:
            self.get_logger().warn('frame encode failed: %s' % e)

def main():
    rclpy.init(); bridge = Bridge()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            if self.path.split('?', 1)[0] != '/stream': self.send_error(404); return
            self.send_response(200); self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame'); self.end_headers()
            try:
                while rclpy.ok():
                    with bridge.lock: frame = bridge.jpeg
                    if frame:
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' + str(len(frame)).encode() + b'\r\n\r\n' + frame + b'\r\n')
                    threading.Event().wait(1 / 3)
            except (BrokenPipeError, ConnectionResetError): pass
    server = VideoHTTPServer(('0.0.0.0', PORT), Handler)
    def stop(*_):
        # systemd/guard restart must never wait for a browser's long-lived MJPEG
        # request.  shutdown is invoked off the serve_forever thread.
        threading.Thread(target=server.shutdown, daemon=True).start()
        rclpy.shutdown()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # Keep ROS spinning on the process main thread.  With the Jetson's DDS
    # build, an executor created in a worker thread can discover a topic yet
    # never dispatch its image callbacks.
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        rclpy.spin(bridge)
    finally:
        server.shutdown()
        server.server_close()
        bridge.destroy_node()

if __name__ == '__main__': main()
