#!/usr/bin/env python3
"""独立视觉 MJPEG 桥：只服务视觉抓取图像，重启不影响底盘/导航。"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image

PORT = 8082

class Bridge(Node):
    def __init__(self):
        super().__init__('vision_stream_server')
        self.lock, self.jpeg = threading.Lock(), None
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                         history=HistoryPolicy.KEEP_LAST)
        self.create_subscription(Image, '/snack_butler/image_result', self.on_image, qos)

    def on_image(self, msg):
        try:
            img = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
            ok, data = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                with self.lock: self.jpeg = data.tobytes()
        except Exception as e:
            self.get_logger().warn('frame encode failed: %s' % e)

def main():
    rclpy.init(); bridge = Bridge()
    threading.Thread(target=rclpy.spin, args=(bridge,), daemon=True).start()
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
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()

if __name__ == '__main__': main()
