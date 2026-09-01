#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nav2 到底盘之间的独立安全闸门。

Nav2 输出 /nav_cmd_vel，本节点只有在显式 arm 且雷达持续出帧时才转发到
/controller/cmd_vel。任何异常、命令超时或近障都会发布零速度。
发现遗留 /cmd_vel 非零命令时立即锁定并用零速度兜底，但这不能代替在厂商
底盘节点中彻底移除该旁路。
它不是硬件急停，不能识别悬崖、玻璃或低于二维雷达扫描面的障碍。
"""
import json
import math
import os
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from nav_safety_logic import safe_velocity, sector_min, twist_nonzero
from service_watchdog import ServiceWatchdog


class NavSafetyGuard(Node):
    def __init__(self):
        super().__init__('nav_safety_guard')
        self.armed = False
        self.reason = '导航驱动锁定'
        self.last_scan = 0.0
        self.last_cmd = 0.0
        self.scan = None
        self.nav_cmd = Twist(); self.manual_cmd = Twist()
        self.last_nav_cmd = 0.0; self.last_manual_cmd = 0.0
        self.source = None
        self.zero_ticks = 0
        self.last_legacy_cmd = 0.0
        self.vision_guard_m = None; self.vision_guard_reason = None; self.last_vision = 0.0
        self.legacy_count = 0
        self.out = self.create_publisher(Twist, '/controller/cmd_vel', 10)
        self.state_pub = self.create_publisher(String, '/nav_safety/state', 10)
        self.create_subscription(LaserScan, '/scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(Twist, '/nav_cmd_vel', self.on_cmd, 10)
        self.create_subscription(Twist, '/manual_cmd_vel', self.on_manual_cmd, 10)
        self.create_subscription(Twist, '/cmd_vel', self.on_legacy_cmd, 10)
        self.create_subscription(String, '/nav_safety/cmd', self.on_control, 10)
        self.create_subscription(String, '/snack_butler/state', self.on_vision, 10)
        self.create_timer(0.05, self.tick)       # 20 Hz 转发/死手保护
        self.create_timer(0.5, self.publish_state)

        self.max_vx = 0.12
        self.max_vy = 0.08
        self.max_wz = 0.45
        self.stop_distance = 0.38
        self.slow_distance = 0.72
        self.turn_stop_distance = 0.30
        # 真机 TF: base_link -> lidar_frame yaw=180°。scan 的 0° 指向车尾，
        # base_link +X（车头）对应 scan ±180°。
        self.scan_forward_angle = math.pi
        self.config_file = os.path.join(os.path.expanduser('~'), 'nav_safety_config.json')
        self.load_config()
        self.last_log_state = None
        self.last_heartbeat = time.monotonic()
        self.watchdog = ServiceWatchdog('nav-safety')
        self.get_logger().info('[startup] 导航安全闸门已启动，默认锁定，等待雷达与显式控制源授权')
        self.create_timer(5.0, self.watchdog_tick)
        self.watchdog.ready('已启动，默认锁定')

    def watchdog_tick(self):
        self.watchdog.ping('armed=%s scan=%s source=%s' %
                           (self.armed, self.scan_fresh(), self.source or 'none'))

    def load_config(self):
        try:
            with open(self.config_file, encoding='utf-8') as f:
                data = json.load(f)
            self.max_vx = max(0.05, min(0.25, float(data.get('max_vx', self.max_vx))))
            self.max_vy = max(0.04, min(0.18, float(data.get('max_vy', self.max_vy))))
            self.max_wz = max(0.20, min(1.00, float(data.get('max_wz', self.max_wz))))
            self.get_logger().info('[config] 已恢复限速 vx=%.2f vy=%.2f wz=%.2f' %
                                   (self.max_vx, self.max_vy, self.max_wz))
        except FileNotFoundError:
            pass
        except Exception as e:
            self.get_logger().warn('[config] 忽略无效限速配置: %s' % e)

    def save_config(self):
        tmp = self.config_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'max_vx': self.max_vx, 'max_vy': self.max_vy,
                       'max_wz': self.max_wz, 'saved_at': time.time()}, f, indent=2)
        os.replace(tmp, self.config_file)

    def on_scan(self, msg):
        self.scan = msg
        self.last_scan = time.monotonic()

    def on_cmd(self, msg):
        self.nav_cmd = msg
        self.last_nav_cmd = time.monotonic()

    def on_manual_cmd(self, msg):
        self.manual_cmd = msg
        self.last_manual_cmd = time.monotonic()

    def on_legacy_cmd(self, msg):
        # 厂商程序可能仍直接订阅 /cmd_vel；本节点无法阻止同一消息被它收到，
        # 只能尽快锁定并向受控底盘入口连续补零。真机调试前仍须核对订阅关系。
        if not twist_nonzero(msg):
            return
        self.last_legacy_cmd = time.monotonic()
        self.legacy_count += 1
        self.armed, self.source = False, None
        self.reason = '检测到旧 /cmd_vel 旁路，已急停锁定'
        self.zero_ticks = max(self.zero_ticks, 30)

    def on_vision(self, msg):
        try:
            vision = json.loads(msg.data)
            self.vision_guard_m = vision.get('vision_guard_m')
            self.vision_guard_reason = vision.get('vision_guard_reason')
            self.last_vision = time.monotonic()
        except Exception:
            pass

    def on_control(self, msg):
        try:
            data = json.loads(msg.data); action = data.get('action'); source = data.get('source')
        except Exception: action = source = None
        if action == 'arm':
            if self.legacy_active():
                self.armed, self.source, self.reason = False, None, '拒绝解锁：旧 /cmd_vel 仍有非零指令'
            elif source not in ('nav', 'manual'):
                self.armed, self.source, self.reason = False, None, '拒绝解锁：控制源无效'
            elif self.scan_fresh():
                self.armed, self.source, self.reason = True, source, '%s 驱动已解锁' % source
            else:
                self.armed, self.source, self.reason = False, None, '拒绝解锁：雷达无数据'
        elif action in ('disarm', 'stop'):
            self.armed, self.source, self.reason = False, None, '驱动锁定'
            self.zero_ticks = 10
        elif action == 'set_limits':
            if self.armed:
                self.reason = '驱动已解锁，拒绝修改限速；请先锁定底盘'
            else:
                try:
                    self.max_vx = max(0.05, min(0.25, float(data['max_vx'])))
                    self.max_vy = max(0.04, min(0.18, float(data['max_vy'])))
                    self.max_wz = max(0.20, min(1.00, float(data['max_wz'])))
                    self.save_config()
                    self.reason = '限速配置已保存'
                except Exception as e:
                    self.reason = '限速配置无效：%s' % e
        self.get_logger().info('[command] action=%s source=%s -> armed=%s selected=%s reason=%s' %
                               (action, source, self.armed, self.source, self.reason))

    def scan_fresh(self): return self.scan is not None and time.monotonic() - self.last_scan < 0.5

    def legacy_active(self): return self.last_legacy_cmd > 0 and time.monotonic() - self.last_legacy_cmd < 2.0

    def sector_min(self, center, half_width):
        s = self.scan
        if not s: return math.inf
        return sector_min(s.ranges, s.angle_min, s.angle_increment, s.range_min, s.range_max,
                          center, half_width)

    @staticmethod
    def clamp(v, limit): return max(-limit, min(limit, float(v)))

    def safe_twist(self):
        now = time.monotonic()
        if not self.armed: return None, '导航驱动锁定'
        if not self.scan_fresh():
            self.armed = False; self.source = None; self.zero_ticks = 10
            return None, '雷达数据中断，已自动锁定'
        if self.source == 'nav': cmd, stamp = self.nav_cmd, self.last_nav_cmd
        elif self.source == 'manual': cmd, stamp = self.manual_cmd, self.last_manual_cmd
        else: return None, '没有已授权的控制源'
        if now - stamp > 0.35: return None, '%s 速度指令超时' % self.source
        if (self.last_vision and now-self.last_vision < 1.0 and self.vision_guard_m is not None and
                self.vision_guard_m < .36 and cmd.linear.x > .01):
            # 视觉禁行区只描述车头前上方障碍。此前连“原地转向/向后脱困”都冻结，
            # Frontier 脱困会傻停原地；这两种动作继续由下面的全车雷达检查兜底。
            return self.make_twist(0, 0, 0), '%s，禁止继续前进' % (self.vision_guard_reason or '视觉检测到车体上方障碍')

        vx, vy, wz, reason = safe_velocity(
            cmd.linear.x, cmd.linear.y, cmd.angular.z, self.scan,
            max_vx=self.max_vx, max_vy=self.max_vy, max_wz=self.max_wz,
            stop_distance=self.stop_distance, slow_distance=self.slow_distance,
            turn_stop_distance=self.turn_stop_distance,
            scan_forward_angle=self.scan_forward_angle)
        return self.make_twist(vx, vy, wz), reason

    @staticmethod
    def make_twist(vx, vy, wz):
        # rclpy 的 geometry_msgs 字段严格要求 Python float。视觉急停路径传入的
        # 0 是 int，曾导致安全节点在急停时自身崩溃，反而让探索判为安全闸门失联。
        t = Twist(); t.linear.x = float(vx); t.linear.y = float(vy); t.angular.z = float(wz)
        return t

    def publish_zero(self): self.out.publish(Twist())

    def tick(self):
        if not self.armed:
            if self.zero_ticks > 0:
                self.publish_zero(); self.zero_ticks -= 1
            return
        cmd, reason = self.safe_twist()
        self.reason = reason
        self.out.publish(cmd if cmd is not None else Twist())

    def publish_state(self):
        front = self.sector_min(self.scan_forward_angle, math.radians(38)) if self.scan else None
        body = self.sector_min(self.scan_forward_angle, math.pi) if self.scan else None
        data = {'armed': self.armed, 'source': self.source, 'reason': self.reason, 'scan_ready': self.scan_fresh(),
                'legacy_active': self.legacy_active(), 'legacy_count': self.legacy_count,
                'front_m': None if front is None or not math.isfinite(front) else round(front, 3),
                'body_m': None if body is None or not math.isfinite(body) else round(body, 3),
                'vision_guard_m': self.vision_guard_m if time.monotonic()-self.last_vision < 1.0 else None,
                'vision_guard_reason': self.vision_guard_reason if time.monotonic()-self.last_vision < 1.0 else None,
                'limits': {'vx': self.max_vx, 'vy': self.max_vy, 'wz': self.max_wz,
                           'stop_m': self.stop_distance, 'slow_m': self.slow_distance,
                           'turn_stop_m': self.turn_stop_distance,
                           'scan_forward_deg': round(math.degrees(self.scan_forward_angle))}}
        self.state_pub.publish(String(data=json.dumps(data, ensure_ascii=False)))
        key = (self.armed, self.source, self.reason, data['scan_ready'], data['legacy_active'])
        now = time.monotonic()
        if key != self.last_log_state:
            self.get_logger().info('[transition] armed=%s source=%s scan=%s legacy=%s reason=%s' %
                                   (self.armed, self.source, data['scan_ready'], data['legacy_active'], self.reason))
            self.last_log_state = key
        elif now - self.last_heartbeat >= 60:
            self.get_logger().info('[heartbeat] armed=%s source=%s scan=%s front_m=%s legacy_count=%s reason=%s' %
                                   (self.armed, self.source, data['scan_ready'], data['front_m'],
                                    self.legacy_count, self.reason))
            self.last_heartbeat = now


def main():
    rclpy.init(); node = NavSafetyGuard()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        try:
            if rclpy.ok():
                for _ in range(5): node.publish_zero()
        except Exception: pass
        try: node.destroy_node()
        except Exception: pass
        try:
            if rclpy.ok(): rclpy.shutdown()
        except Exception: pass


if __name__ == '__main__': main()
