#!/usr/bin/env python3
"""恢复 sllidar 在 USB 断连重枚举后仍握着旧文件描述符的问题。"""
import os
import glob
import subprocess
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan


class LidarWatchdog(Node):
    def __init__(self):
        super().__init__('lidar_watchdog')
        self.boot = time.monotonic()
        self.last_scan = 0.0
        self.last_restart = 0.0
        self.attempts = 0
        self.last_heartbeat = 0.0
        self.create_subscription(LaserScan, '/scan', self.on_scan, qos_profile_sensor_data)
        self.create_timer(2.0, self.tick)
        self.get_logger().info('[startup] 雷达 watchdog 已启动；串口存在且 /scan 中断时才执行受限恢复')

    def on_scan(self, _msg):
        self.last_scan = time.monotonic()
        self.attempts = 0

    def tick(self):
        now = time.monotonic()
        raw = sorted(glob.glob('/dev/ttyCH341USB*') + glob.glob('/dev/ttyUSB*'))
        if now - self.last_heartbeat >= 60.0:
            age = None if self.last_scan == 0 else round(now - self.last_scan, 1)
            self.get_logger().info('[heartbeat] device=%s scan_age=%s attempts=%s cooldown=%ss' %
                                   (os.path.exists('/dev/lidar'), age, self.attempts,
                                    max(0, round(120 - (now - self.last_restart))) if self.last_restart else 0))
            self.last_heartbeat = now
        if raw and not os.path.exists('/dev/lidar'):
            if now - self.last_restart >= 120.0:
                self.get_logger().error('[udev] 发现雷达候选串口 %s，但 /dev/lidar 不存在；请检查 99-jetrover-lidar.rules' % raw)
                self.last_restart = now
            return
        # Jetson 单独供电时雷达串口不存在：这是预期状态，不重启任何服务。
        if not os.path.exists('/dev/lidar'):
            return
        if now - self.boot < 45.0:
            return
        stale = self.last_scan == 0.0 or now - self.last_scan > 6.0
        if not stale or now - self.last_restart < 120.0 or self.attempts >= 3:
            return
        self.attempts += 1; self.last_restart = now
        self.get_logger().error('/scan 中断且 /dev/lidar 存在，重启 start_app_node（第%d次）' % self.attempts)
        try:
            subprocess.run(['sudo', '-n', '/usr/bin/systemctl', 'restart', 'start_app_node.service'],
                           timeout=30, check=True)
        except Exception as e:
            self.get_logger().error('重启失败: %s' % e)


def main():
    rclpy.init(); node = LidarWatchdog()
    try: rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()


if __name__ == '__main__': main()
