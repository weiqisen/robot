#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JetRover frontier 自主探索 agent。

订阅 /map，在已知自由区与未知区的边界上聚类并选择目标；运动交给 Nav2
NavigateToPose，因此全局规划、局部避障和恢复行为仍由机器人已有 Nav2 配置负责。
启动时记录 map -> base_link 作为返航点，探索完成/超时后自动返回。

命令 /explorer/cmd (std_msgs/String JSON):
  {"action":"start","max_minutes":15,"min_frontier_cells":8,"goal_timeout":90}
  {"action":"pause"} | {"action":"resume"} | {"action":"stop"} | {"action":"home"}
状态 /explorer/state (std_msgs/String JSON)
"""
import json
import math
import os
import threading
import time
from collections import deque

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import OccupancyGrid, Odometry
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from std_msgs.msg import String, UInt16
from sensor_msgs.msg import LaserScan
from service_watchdog import ServiceWatchdog

try:
    from tf2_ros import Buffer, TransformListener
except Exception:
    Buffer = TransformListener = None


class Explorer(Node):
    def __init__(self):
        super().__init__('jetrover_explorer')
        self.map = None
        self.last_map = 0.0
        self.odom = None
        self.batt_mv = None
        self.last_scan = 0.0
        self.safety_state = None
        self.last_safety = 0.0
        self.snack_state = None
        self.last_snack = 0.0
        self.prepare_started = 0.0
        self.prepare_next = 'exploring'
        self.safety_blocked_since = 0.0
        self.mode = 'idle'
        self.step = '等待开始'
        self.home = None
        self.home_saved_at = None
        self.home_restored = False
        self.home_restore_status = 'none'
        self.session_candidate = None
        self.recovery_available = False
        self.recovery_mode = None
        self.recovery_elapsed = 0.0
        self.recovery_last_target = None
        self.session_file = os.path.join(os.path.expanduser('~'), 'explorer_session.json')
        self.target = None
        self.started_at = 0.0
        self.visited = []
        self.blacklist = []
        self.breadcrumbs = deque(maxlen=80)
        self.last_breadcrumb = None
        self.last_blacklist_retry = 0.0
        self.escape_target = None
        self.escape_attempts = 0
        self.goal_handle = None
        self.goal_started = 0.0
        self.goal_seq = 0
        self.event_seq = 0
        self.events = deque(maxlen=80)
        self.objects = deque(maxlen=100)
        self.lock = threading.RLock()
        self.watchdog = ServiceWatchdog('explorer-agent')
        self.cfg = {'max_minutes': 15.0, 'min_frontier_cells': 8,
                    'goal_timeout': 90.0, 'goal_tolerance': 0.35,
                    # 小于 Nav2 到达容差的目标只会让车原地转向；开阔处的下一簇边界
                    # 又常在 1.5m 之外。限定为 0.45~2.0m，保持短步且确保有实际位移。
                    'clearance_cells': 5, 'min_goal_distance': 0.45,
                    'max_goal_distance': 2.0,
                    # 安全闸门短暂拦截旋转很常见，不能 3 秒就永久淘汰一个 frontier。
                    # 给 Nav2 足够的局部重规划时间；失败目标只临时降权，稍后可重试。
                    'near_block_timeout': 10.0, 'blacklist_ttl': 75.0,
                    'blacklist_retry_interval': 45.0, 'arm_stow_timeout': 8.0,
                    # 近障持续时仅请求 Nav2 做短距离脱困，绝不绕过安全闸门直发 /cmd_vel。
                    'escape_distance': .32, 'max_escape_attempts': 2,
                    'arm_tolerance_deg': 6.0,
                    'low_voltage': 9.7, 'min_start_voltage': 10.5}

        self.load_session()

        self.create_subscription(OccupancyGrid, '/map', self.on_map, 1)
        self.create_subscription(Odometry, '/odom', self.on_odom, 10)
        self.create_subscription(UInt16, '/ros_robot_controller/battery', self.on_batt, 10)
        self.create_subscription(LaserScan, '/scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(String, '/nav_safety/state', self.on_safety_state, 10)
        self.create_subscription(String, '/snack_butler/state', self.on_snack_state, 10)
        self.create_subscription(String, '/explorer/cmd', self.on_cmd, 10)
        self.pub = self.create_publisher(String, '/explorer/state', 10)
        self.safety_pub = self.create_publisher(String, '/nav_safety/cmd', 10)
        self.snack_pub = self.create_publisher(String, '/snack_butler/cmd', 10)
        self.nav = ActionClient(self, NavigateToPose, '/navigate_to_pose')
        self.tf_buffer = Buffer() if Buffer else None
        self.tf_listener = TransformListener(self.tf_buffer, self) if self.tf_buffer else None
        self.create_timer(1.0, self.tick)
        self.create_timer(0.5, self.publish_state)
        self.create_timer(5.0, self.watchdog_tick)
        self.create_timer(5.0, self.checkpoint_tick)
        self.create_timer(60.0, self.log_heartbeat)
        self.get_logger().info('[startup] 自主探索 agent 已启动，等待地图、雷达、Nav2 与安全闸门')
        self.add_event('startup', '探索大脑已启动，正在等待地图、雷达、Nav2 与安全闸门')
        self.watchdog.ready('已启动，等待依赖')

    def watchdog_tick(self):
        self.watchdog.ping('mode=%s map=%s scan=%s safety=%s' %
                           (self.mode, self.map_ready(), self.scan_ready(), self.safety_ready()))

    def add_event(self, kind, text, level='info', data=None):
        """给页面展示可验证的决策事件，不输出不可审计的隐藏推理。"""
        self.event_seq += 1
        item = {'seq': self.event_seq, 'time': time.strftime('%H:%M:%S'),
                'kind': kind, 'level': level, 'text': text}
        if data is not None:
            item['data'] = data
        self.events.append(item)

    @staticmethod
    def _poses(values, limit=80):
        result = []
        for value in (values or [])[:limit]:
            if (isinstance(value, (list, tuple)) and len(value) == 3 and
                    all(isinstance(v, (int, float)) and math.isfinite(v) for v in value)):
                result.append(tuple(float(v) for v in value))
        return result

    def load_session(self):
        """恢复返航点和中断任务检查点；绝不在启动后自动恢复移动。"""
        try:
            with open(self.session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            home = data.get('home')
            if (not isinstance(home, list) or len(home) != 3 or
                    not all(isinstance(v, (int, float)) and math.isfinite(v) for v in home)):
                raise ValueError('home 必须是 3 个有限数值')
            map_to_odom = data.get('map_to_odom')
            if (not isinstance(map_to_odom, list) or len(map_to_odom) != 3 or
                    not all(isinstance(v, (int, float)) and math.isfinite(v) for v in map_to_odom)):
                raise ValueError('缺少地图连续性校验数据')
            self.session_candidate = {
                'home': tuple(float(v) for v in home),
                'map_to_odom': tuple(float(v) for v in map_to_odom),
                'mission': data.get('mission') if isinstance(data.get('mission'), dict) else None,
            }
            self.home_saved_at = data.get('saved_at')
            self.home_restore_status = 'pending'
            self.step = '正在校验上次任务检查点'
            self.add_event('session', '发现持久化返航原点与任务检查点，等待校验地图坐标连续性')
            self.get_logger().info('[session] 找到持久化原点，等待地图连续性校验')
        except FileNotFoundError:
            return
        except Exception as e:
            self.get_logger().warn('[session] 忽略无效的原点文件 %s: %s' % (self.session_file, e))
            self.add_event('session', '持久化原点无效，已忽略：%s' % e, 'warn')

    def odom_pose(self):
        if not self.odom:
            return None
        p, q = self.odom.pose.pose.position, self.odom.pose.pose.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y*q.y + q.z*q.z))
        return (p.x, p.y, yaw)

    @staticmethod
    def angle_error(a, b):
        return abs(math.atan2(math.sin(a-b), math.cos(a-b)))

    def map_to_odom_signature(self):
        """用 map/base 与 odom/base 推出 map/odom，识别 SLAM/里程计坐标重置。"""
        map_pose, odom_pose = self.current_pose(), self.odom_pose()
        if not map_pose or not odom_pose:
            return None
        yaw = math.atan2(math.sin(map_pose[2]-odom_pose[2]), math.cos(map_pose[2]-odom_pose[2]))
        c, s = math.cos(yaw), math.sin(yaw)
        return (map_pose[0] - (c*odom_pose[0] - s*odom_pose[1]),
                map_pose[1] - (s*odom_pose[0] + c*odom_pose[1]), yaw)

    def validate_session(self):
        if not self.session_candidate:
            return
        current = self.map_to_odom_signature()
        if not current:
            return
        saved = self.session_candidate['map_to_odom']
        shift = math.hypot(current[0]-saved[0], current[1]-saved[1])
        turn = self.angle_error(current[2], saved[2])
        if shift <= .25 and turn <= math.radians(10):
            self.home = self.session_candidate['home']
            self.home_restored = True
            self.home_restore_status = 'restored'
            mission = self.session_candidate.get('mission')
            if mission and mission.get('mode') in ('preparing', 'exploring', 'returning', 'paused'):
                self.visited = self._poses(mission.get('visited'), 200)
                self.blacklist = [b for b in (mission.get('blacklist') or [])
                                  if isinstance(b, dict) and isinstance(b.get('until'), (int, float)) and
                                  b.get('until') > time.time() and self._poses([b.get('p')], 1)]
                self.breadcrumbs = deque(self._poses(mission.get('breadcrumbs'), 80), maxlen=80)
                self.recovery_available = True
                self.recovery_mode = mission.get('mode')
                self.recovery_elapsed = max(0.0, float(mission.get('elapsed_sec') or 0.0))
                last_target = self._poses([mission.get('target')], 1)
                self.recovery_last_target = last_target[0] if last_target else None
                self.mode = 'recovery'
                self.step = '发现中断任务，底盘已锁定；请确认继续探索或立即返航'
                self.safety('disarm')
                self.add_event('recovery', '已恢复任务检查点，等待人工确认；不会自动移动', 'warn')
            else:
                self.step = '已恢复上次任务原点，等待命令'
            self.get_logger().info('[session] 地图连续，已恢复原点 home=%s shift=%.3fm turn=%.1fdeg' %
                                   (self.home, shift, math.degrees(turn)))
            self.add_event('session', '地图坐标连续，已恢复原点 (%.2f, %.2f)' % self.home[:2])
        else:
            self.home = None
            self.home_restore_status = 'stale'
            self.step = '地图坐标已重置，旧返航原点已作废；请重新开始任务'
            self.get_logger().warn('[session] 地图坐标不连续，拒绝恢复旧原点 shift=%.3fm turn=%.1fdeg' %
                                   (shift, math.degrees(turn)))
            self.add_event('session', '地图坐标已重置，旧原点作废（偏移 %.2fm / %.1f°）' %
                           (shift, math.degrees(turn)), 'error')
        self.session_candidate = None

    def mission_snapshot(self):
        active = self.mode in ('preparing', 'exploring', 'returning', 'paused')
        if not active:
            return None
        return {
            'mode': self.mode, 'elapsed_sec': round(time.time() - self.started_at, 1) if self.started_at else 0.0,
            'target': list(self.target) if self.target else None,
            'visited': [list(p) for p in self.visited[-200:]],
            'blacklist': [{'p': list(b['p']), 'until': b['until'], 'reason': b.get('reason')}
                          for b in self.blacklist[-80:] if b.get('until', 0) > time.time()],
            'breadcrumbs': [list(p) for p in self.breadcrumbs],
            'saved_at': time.time(),
        }

    def save_session(self, event=False):
        signature = self.map_to_odom_signature()
        if not signature or not self.home:
            self.get_logger().error('[session] 缺少 map/odom 变换，未保存返航原点')
            return
        self.home_saved_at = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        data = {'version': 2, 'home': list(self.home), 'map_to_odom': list(signature),
                'saved_at': self.home_saved_at, 'mission': self.mission_snapshot()}
        tmp = self.session_file + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.session_file)
            self.home_restored = False
            self.home_restore_status = 'saved'
            if event:
                self.get_logger().info('[session] 已持久化返航原点 home=%s saved_at=%s' %
                                       (self.home, self.home_saved_at))
                self.add_event('home', '已记录并持久化返航原点 (%.2f, %.2f)' % self.home[:2])
        except Exception as e:
            self.get_logger().error('[session] 保存返航原点失败: %s' % e)
            self.add_event('home', '返航原点保存失败：%s' % e, 'error')

    def checkpoint_tick(self):
        with self.lock:
            if self.mode not in ('preparing', 'exploring', 'returning', 'paused'):
                return
            pose = self.current_pose()
            if pose and (not self.last_breadcrumb or math.hypot(pose[0] - self.last_breadcrumb[0],
                                                                 pose[1] - self.last_breadcrumb[1]) >= .45):
                self.breadcrumbs.append(pose)
                self.last_breadcrumb = pose
            self.save_session()

    def log_heartbeat(self):
        self.get_logger().info('[heartbeat] mode=%s step=%s map=%s scan=%s safety=%s nav=%s battery=%s' %
                               (self.mode, self.step, self.map_ready(), self.scan_ready(),
                                self.safety_ready(), self.nav.server_is_ready(), self.batt_mv))

    def on_map(self, msg): self.map = msg; self.last_map = time.time()
    def on_odom(self, msg): self.odom = msg
    def on_batt(self, msg): self.batt_mv = msg.data
    def on_scan(self, _msg): self.last_scan = time.time()
    def on_safety_state(self, msg):
        try:
            self.safety_state = json.loads(msg.data); self.last_safety = time.time()
        except Exception: pass

    def on_snack_state(self, msg):
        try:
            self.snack_state = json.loads(msg.data); self.last_snack = time.time()
            pose = self.current_pose()
            if pose:
                for d in self.snack_state.get('detections') or []:
                    if d.get('detector') != 'yolov5' or not d.get('xyz'): continue
                    x, y = d['xyz'][:2]; c, s = math.cos(pose[2]), math.sin(pose[2])
                    item = {'label':d.get('label','object'), 'confidence':d.get('confidence'),
                            'x':round(pose[0]+c*x-s*y,2), 'y':round(pose[1]+s*x+c*y,2),
                            'seen_at':time.strftime('%Y-%m-%dT%H:%M:%S%z')}
                    if not any(o['label']==item['label'] and math.hypot(o['x']-item['x'],o['y']-item['y'])<.5 for o in self.objects):
                        self.objects.append(item); self.add_event('vision','发现 %s，记录于地图 (%.2f, %.2f)'%(item['label'],item['x'],item['y']))
        except Exception: pass

    def scan_ready(self): return time.time() - self.last_scan < 2.0
    def map_ready(self): return self.map is not None and time.time() - self.last_map < 3.0
    def safety_ready(self): return self.safety_state is not None and time.time() - self.last_safety < 2.0
    def snack_ready(self): return self.snack_state is not None and time.time() - self.last_snack < 2.0
    def legacy_clear(self): return self.safety_ready() and not self.safety_state.get('legacy_active', False)

    def clearance_ready(self):
        if not self.safety_ready(): return False
        limits = self.safety_state.get('limits') or {}
        front, body = self.safety_state.get('front_m'), self.safety_state.get('body_m')
        return ((front is None or front >= float(limits.get('stop_m', .38))) and
                (body is None or body >= float(limits.get('turn_stop_m', .30))))

    def safety(self, action):
        self.safety_pub.publish(String(data=json.dumps({'action': action, 'source': 'nav'})))

    def stow_arm(self):
        self.snack_pub.publish(String(data=json.dumps({'action': 'home'})))

    def arm_stowed(self):
        if not self.snack_ready(): return False
        q = self.snack_state.get('q_deg') or []
        home = (self.snack_state.get('cfg') or {}).get('home_deg') or []
        return len(q) >= 5 and len(home) >= 5 and max(abs(float(a)-float(b)) for a, b in zip(q, home)) <= self.cfg['arm_tolerance_deg']

    def recovery_ready(self):
        if not self.map_ready(): return '没有 /map'
        if not self.scan_ready(): return '激光雷达 /scan 没有数据'
        if not self.safety_ready() or not self.legacy_clear(): return '导航安全闸门未就绪或发现控制旁路'
        if not self.snack_ready(): return '机械臂节点未连接，不能确认收臂'
        if self.batt_mv is None or self.batt_mv / 1000.0 < self.cfg['min_start_voltage']:
            return '电池电压不足，不能恢复移动'
        if not self.current_pose(): return '没有 map/base_link 位姿'
        return None

    def current_pose(self):
        if self.tf_buffer:
            try:
                t = self.tf_buffer.lookup_transform('map', 'base_link', Time())
                q = t.transform.rotation
                yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y*q.y + q.z*q.z))
                return (t.transform.translation.x, t.transform.translation.y, yaw)
            except Exception:
                pass
        if self.odom:
            p, q = self.odom.pose.pose.position, self.odom.pose.pose.orientation
            yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y*q.y + q.z*q.z))
            return (p.x, p.y, yaw)
        return None

    def on_cmd(self, msg):
        try:
            cmd = json.loads(msg.data)
            action = cmd.get('action')
        except Exception as e:
            self.step = '命令格式错误: %s' % e
            return
        with self.lock:
            self.get_logger().info('[command] action=%s mode=%s payload=%s' % (action, self.mode, msg.data))
            self.add_event('command', '收到命令：%s（当前 %s）' % (action, self.mode))
            if action == 'start':
                if not self.map_ready():
                    self.step = '无法开始：没有 /map'
                    return
                if not self.scan_ready():
                    self.step = '无法开始：激光雷达 /scan 没有数据'
                    return
                if not self.safety_ready():
                    self.step = '无法开始：导航安全闸门未运行'
                    return
                if not self.legacy_clear():
                    self.step = '无法开始：检测到旧 /cmd_vel 控制旁路'
                    return
                if not self.clearance_ready():
                    self.step = '无法开始：车头或车身周围净空不足，请先人工挪开'
                    return
                if not self.snack_ready():
                    self.step = '无法开始：机械臂节点未连接，不能确认收臂'
                    return
                if self.batt_mv is None:
                    self.step = '无法开始：没有底盘电池电压数据'
                    return
                if self.batt_mv / 1000.0 < self.cfg['min_start_voltage']:
                    self.step = '无法开始：电池电压低于 %.1fV' % self.cfg['min_start_voltage']
                    return
                pose = self.current_pose()
                if not pose:
                    self.step = '无法开始：没有 map/base_link 位姿'
                    return
                for k in self.cfg:
                    if k in cmd:
                        self.cfg[k] = type(self.cfg[k])(cmd[k])
                self.started_at = 0.0
                self.visited, self.blacklist = [], []
                self.breadcrumbs.clear(); self.last_breadcrumb = pose
                self.recovery_available = False; self.recovery_mode = None
                self.recovery_elapsed = 0.0; self.recovery_last_target = None
                self.home = pose
                self.mode, self.step = 'preparing', '底盘已锁定，正在收回机械臂'
                self.prepare_next = 'exploring'
                self.cancel_goal()
                self.safety('disarm')
                self.prepare_started = time.time()
                self.stow_arm()
                self.save_session(event=True)
            elif action == 'pause' and self.mode == 'exploring':
                self.cancel_goal(); self.safety('disarm'); self.mode, self.step = 'paused', '已暂停，导航驱动已锁定'
                self.save_session()
            elif action == 'resume' and self.mode in ('paused', 'recovery'):
                reason = self.recovery_ready()
                if reason:
                    self.step = '无法继续：' + reason
                else:
                    target_mode = self.recovery_mode if self.mode == 'recovery' else 'exploring'
                    self.safety('disarm'); self.mode, self.step = 'preparing', '恢复前先确认机械臂收回'
                    self.prepare_next = 'returning' if target_mode == 'returning' else 'exploring'
                    if self.recovery_elapsed:
                        self.started_at = time.time() - self.recovery_elapsed
                    self.recovery_available = False; self.recovery_mode = None
                    self.target = None
                    self.prepare_started = time.time(); self.stow_arm(); self.save_session()
            elif action == 'stop':
                self.cancel_goal(); self.safety('disarm'); self.mode, self.step = 'idle', '任务已停止（不返航）'
                self.recovery_available = False; self.recovery_mode = None; self.save_session()
            elif action == 'home':
                if not self.home:
                    self.step = '没有已记录的原点'
                elif not self.scan_ready():
                    self.step = '无法返航：激光雷达 /scan 没有数据'
                else:
                    self.cancel_goal(); self.safety('disarm'); self.mode, self.step = 'preparing', '返航前先收回机械臂'
                    self.prepare_next = 'returning'; self.prepare_started = time.time(); self.stow_arm()
                    self.recovery_available = False; self.recovery_mode = None; self.save_session()
            elif action == 'set_home_current':
                pose = self.current_pose()
                if self.mode in ('exploring', 'returning', 'preparing'):
                    self.step = '任务运行中，拒绝改写返航原点'
                elif not pose:
                    self.step = '没有 map/base_link 位姿，无法记录当前位置'
                else:
                    self.cancel_goal(); self.safety('disarm'); self.home = pose
                    self.save_session(); self.step = '已将当前位置记录为应急返航原点'
            elif action == 'clear_home':
                if self.mode in ('exploring', 'returning', 'preparing'):
                    self.step = '任务运行中，拒绝清除返航原点'
                else:
                    self.home = None; self.session_candidate = None
                    self.home_restored = False; self.home_restore_status = 'none'
                    try:
                        os.remove(self.session_file)
                    except FileNotFoundError:
                        pass
                    self.step = '返航原点已清除'
                    self.add_event('home', '返航原点已人工清除', 'warn')
            else:
                self.step = '当前状态不接受命令: %s' % action
            self.get_logger().info('[transition] mode=%s step=%s home=%s target=%s' %
                                   (self.mode, self.step, self.home, self.target))
            self.add_event('state', self.step,
                           'error' if self.mode == 'error' else 'warn' if self.mode in ('paused', 'returning') else 'info')

    def cancel_goal(self):
        self.goal_seq += 1
        if self.goal_handle:
            try: self.goal_handle.cancel_goal_async()
            except Exception: pass
        self.goal_handle = None
        self.target = None
        self.safety_blocked_since = 0.0

    def grid_to_world(self, x, y):
        m = self.map.info
        # 地图 origin 通常无旋转；兼容有 yaw 的 OccupancyGrid。
        q = m.origin.orientation
        a = math.atan2(2 * (q.w*q.z + q.x*q.y), 1 - 2 * (q.y*q.y + q.z*q.z))
        lx, ly = (x + .5) * m.resolution, (y + .5) * m.resolution
        return (m.origin.position.x + lx*math.cos(a) - ly*math.sin(a),
                m.origin.position.y + lx*math.sin(a) + ly*math.cos(a))

    def frontier_clusters(self):
        msg = self.map; w, h, data = msg.info.width, msg.info.height, msg.data
        frontier = set()
        for y in range(1, h - 1):
            row = y * w
            for x in range(1, w - 1):
                i = row + x
                if data[i] != 0:
                    continue
                if data[i-1] < 0 or data[i+1] < 0 or data[i-w] < 0 or data[i+w] < 0:
                    frontier.add(i)
        clusters = []
        while frontier:
            seed = frontier.pop(); group = [seed]; q = deque([seed])
            while q:
                i = q.popleft(); x, y = i % w, i // w
                for ny in range(max(1, y-1), min(h-1, y+2)):
                    for nx in range(max(1, x-1), min(w-1, x+2)):
                        j = ny*w + nx
                        if j in frontier:
                            frontier.remove(j); group.append(j); q.append(j)
            if len(group) >= self.cfg['min_frontier_cells']:
                clusters.append(group)
        return clusters

    def target_for_cluster(self, group):
        w, h, data = self.map.info.width, self.map.info.height, self.map.data
        cx = sum(i % w for i in group) / len(group)
        cy = sum(i // w for i in group) / len(group)
        # 取最靠近质心、且周围没有占用格的自由点，避免目标贴墙。
        for i in sorted(group, key=lambda j: (j % w-cx)**2 + (j//w-cy)**2):
            x, y = i % w, i // w; r = self.cfg['clearance_cells']; safe = True
            for yy in range(max(0, y-r), min(h, y+r+1)):
                for xx in range(max(0, x-r), min(w, x+r+1)):
                    if data[yy*w+xx] >= 50:
                        safe = False; break
                if not safe: break
            if safe:
                return self.grid_to_world(x, y)
        return None

    def choose_frontier(self):
        pose = self.current_pose()
        if not pose: return None
        now = time.time()
        self.blacklist = [b for b in self.blacklist if b['until'] > now]
        candidates = []
        groups = self.frontier_clusters()
        rejected = {'unsafe': 0, 'near': 0, 'far': 0, 'blacklist': 0, 'visited': 0}
        for group in groups:
            p = self.target_for_cluster(group)
            if not p:
                rejected['unsafe'] += 1; continue
            if any(math.hypot(p[0]-b['p'][0], p[1]-b['p'][1]) < b.get('radius', .30) for b in self.blacklist):
                rejected['blacklist'] += 1; continue
            if any(math.hypot(p[0]-v[0], p[1]-v[1]) < .35 for v in self.visited):
                rejected['visited'] += 1; continue
            d = math.hypot(p[0]-pose[0], p[1]-pose[1])
            if d < self.cfg['min_goal_distance']:
                rejected['near'] += 1; continue
            if d > self.cfg['max_goal_distance']:
                rejected['far'] += 1; continue
            candidates.append((d - min(len(group), 100) * .012, p, len(group)))
        if not candidates:
            self.get_logger().info('[frontier] 无可用目标 clusters=%d rejected=%s range=%.2f~%.2fm' %
                                   (len(groups), rejected, self.cfg['min_goal_distance'],
                                    self.cfg['max_goal_distance']))
        return min(candidates, default=None, key=lambda x: x[0])

    def blacklist_target(self, p, why, radius=.30):
        if not p:
            return
        self.blacklist.append({'p': (float(p[0]), float(p[1])),
                               'until': time.time() + self.cfg['blacklist_ttl'],
                               'why': why, 'radius': float(radius)})

    def obstacle_assessment(self, reason):
        """把安全传感器信号翻译为可审计的导航决策，不把 YOLO 标签当作事实。"""
        s = self.safety_state or {}
        front, body, vision = s.get('front_m'), s.get('body_m'), s.get('vision_guard_m')
        text = str(reason or s.get('vision_guard_reason') or '')
        if isinstance(body, (int, float)) and body < .38:
            return '硬禁行', '雷达车身净空 %.2fm' % body
        if isinstance(front, (int, float)) and front < .38:
            return '硬禁行', '雷达前方净空 %.2fm' % front
        if '深度' in text:
            return '硬禁行', '深度确认的前上方障碍%s' % ((' %.2fm' % vision) if isinstance(vision, (int, float)) else '')
        if 'YOLO' in text:
            return '疑似障碍', 'YOLO 提示需绕行，等待雷达/深度复核'
        return '可绕行', '视觉禁行区触发，雷达未见近距车身障碍'

    def escape_from_obstacle(self, blocked_target, reason):
        """由 Nav2 执行一次短后退+掉头意图；失败仍只重规划，不直接驱动底盘。"""
        level, evidence = self.obstacle_assessment(reason)
        self.blacklist_target(blocked_target, 'near_obstacle', radius=.60)
        pose = self.current_pose()
        if not pose or self.escape_attempts >= self.cfg['max_escape_attempts']:
            self.step = '近障目标已降权，脱困次数已用完，重新评估其他边界'
            self.add_event('replan', self.step, 'warn')
            return
        self.escape_attempts += 1
        dist = self.cfg['escape_distance']
        # 不再原地重复：根据受阻目标位于车头左/右，选反侧的斜后方小目标。
        # Nav2 会检查该目标的可达性；安全闸门仍限制后退/旋转。
        bearing = math.atan2(blocked_target[1]-pose[1], blocked_target[0]-pose[0]) if blocked_target else pose[2]
        side = -1.0 if math.sin(bearing-pose[2]) > 0 else 1.0
        escape_heading = pose[2] + math.pi + side * .60
        ex, ey = pose[0] + dist * math.cos(escape_heading), pose[1] + dist * math.sin(escape_heading)
        eyaw = pose[2] + side * math.pi / 2
        self.escape_target = (ex, ey)
        self.step = '%s：扩大局部禁区，请求斜后方脱困并重新评估' % level
        self.add_event('decision', '前方障碍评估：%s（%s）；选择%s侧斜后方可绕行退路' %
                       (level, evidence, '右' if side < 0 else '左'), 'warn')
        self.add_event('escape', '%s；尝试 %d/%d：局部禁区半径 0.60m，后撤 %.2fm、转向 %.0f°' %
                       (level, self.escape_attempts, self.cfg['max_escape_attempts'], dist,
                        math.degrees(eyaw)), 'warn')
        self.send_goal(ex, ey, eyaw)

    def send_goal(self, x, y, yaw, returning=False):
        if not self.nav.wait_for_server(timeout_sec=.2):
            self.step = '等待 Nav2 /navigate_to_pose'
            return False
        goal = NavigateToPose.Goal(); goal.pose = PoseStamped()
        goal.pose.header.frame_id = 'map'; goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x, goal.pose.pose.position.y = x, y
        goal.pose.pose.orientation.z, goal.pose.pose.orientation.w = math.sin(yaw/2), math.cos(yaw/2)
        self.goal_seq += 1; seq = self.goal_seq
        self.target = (x, y); self.goal_started = time.time()
        self.get_logger().info('[goal] seq=%d type=%s target=(%.3f, %.3f) yaw=%.1fdeg' %
                               (seq, 'home' if returning else 'frontier', x, y,
                                math.degrees(yaw)))
        pose = self.current_pose()
        dist = math.hypot(x-pose[0], y-pose[1]) if pose else 0.0
        self.add_event('goal', '%s目标 #%d：(%.2f, %.2f)，距离 %.2fm' %
                       ('返航' if returning else '探索', seq, x, y, dist))
        future = self.nav.send_goal_async(goal)
        future.add_done_callback(lambda f: self.on_goal_response(f, seq, returning))
        return True

    def on_goal_response(self, future, seq, returning):
        if seq != self.goal_seq: return
        try: handle = future.result()
        except Exception as e:
            self.goal_failed('Nav2 发送失败: %s' % e, returning); return
        if not handle.accepted:
            self.goal_failed('Nav2 拒绝目标', returning); return
        self.goal_handle = handle
        handle.get_result_async().add_done_callback(lambda f: self.on_goal_result(f, seq, returning))

    def on_goal_result(self, future, seq, returning):
        if seq != self.goal_seq: return
        try: status = future.result().status
        except Exception: status = GoalStatus.STATUS_ABORTED
        p = self.target; self.goal_handle = None; self.target = None
        self.get_logger().info('[goal_result] seq=%d type=%s status=%d target=%s' %
                               (seq, 'home' if returning else 'frontier', status, p))
        self.add_event('result', '%s目标 #%d 结果：%s' %
                       ('返航' if returning else '探索', seq,
                        '到达' if status == GoalStatus.STATUS_SUCCEEDED else '取消' if status == GoalStatus.STATUS_CANCELED else '失败'),
                       'info' if status == GoalStatus.STATUS_SUCCEEDED else 'warn')
        is_escape = self.escape_target and p and math.hypot(p[0]-self.escape_target[0], p[1]-self.escape_target[1]) < .08
        if is_escape:
            self.escape_target = None
            if status == GoalStatus.STATUS_SUCCEEDED:
                self.step = '已完成安全脱困，重新寻找可探索边界'
                self.add_event('escape', self.step, 'info')
            elif status != GoalStatus.STATUS_CANCELED:
                self.step = '安全脱困目标不可达，已改选其他探索边界'
                self.add_event('escape', self.step, 'warn')
            return
        if status == GoalStatus.STATUS_SUCCEEDED:
            if returning:
                self.safety('disarm'); self.mode, self.step = 'complete', '已返回原点，任务完成'
            else:
                if p: self.visited.append(p)
                self.escape_attempts = 0
                self.step = '到达探索点，继续扫描边界'
        elif status != GoalStatus.STATUS_CANCELED:
            if returning:
                self.safety('disarm'); self.mode, self.step = 'error', '返航目标不可达，请人工接管'
            else:
                self.blacklist_target(p, 'nav_failed')
                self.step = '目标不可达，已跳过'

    def goal_failed(self, why, returning):
        if self.target and not returning: self.blacklist_target(self.target, 'goal_rejected')
        self.goal_handle, self.target = None, None
        if returning:
            self.safety('disarm'); self.mode = 'error'
        self.step = why

    def begin_return(self, reason):
        self.cancel_goal(); self.mode, self.step = 'returning', reason + '，正在返回原点'
        self.add_event('return', self.step, 'warn')

    def tick(self):
        with self.lock:
            if self.mode not in ('preparing', 'exploring', 'returning'): return
            if not self.scan_ready():
                self.cancel_goal(); self.safety('disarm'); self.mode, self.step = 'error', '雷达数据中断，已取消导航，请人工接管'
                return
            if not self.map_ready():
                self.cancel_goal(); self.safety('disarm'); self.mode, self.step = 'error', '地图数据中断，已取消导航'
                return
            if not self.safety_ready():
                self.cancel_goal(); self.mode, self.step = 'error', '安全闸门失联，已取消导航'
                return
            if not self.legacy_clear():
                self.cancel_goal(); self.safety('disarm'); self.mode, self.step = 'error', '检测到旧 /cmd_vel 控制旁路，已急停锁定'
                return
            if self.mode == 'preparing':
                if self.arm_stowed():
                    if self.prepare_next == 'exploring' and not self.started_at:
                        self.started_at = time.time()
                    self.mode = self.prepare_next
                    self.step = ('机械臂已收回，正在返回原点' if self.mode == 'returning'
                                 else '机械臂已收回，开始寻找探索边界')
                    self.safety('arm')
                elif time.time() - self.prepare_started > self.cfg['arm_stow_timeout']:
                    self.safety('disarm')
                    self.mode, self.step = 'error', '机械臂未能在限定时间内收回，已禁止移动'
                return
            if not self.safety_state.get('armed'):
                self.step = '等待导航安全闸门解锁'
                self.safety('arm')
                return
            if self.batt_mv and self.batt_mv / 1000.0 < self.cfg['low_voltage'] and self.mode == 'exploring':
                self.begin_return('电压过低'); return
            if self.mode == 'exploring' and time.time() - self.started_at > self.cfg['max_minutes'] * 60:
                self.begin_return('达到最长时间'); return
            reason = str(self.safety_state.get('reason') or '')
            blocked = '急停' in reason and ('障' in reason or '近障' in reason)
            if self.mode == 'exploring' and self.target and blocked:
                if not self.safety_blocked_since:
                    self.safety_blocked_since = time.time()
                elif time.time() - self.safety_blocked_since >= self.cfg['near_block_timeout']:
                    p = self.target
                    self.cancel_goal()
                    self.escape_from_obstacle(p, reason)
                    self.get_logger().warn('[safety_skip] reason=%s target=%s' % (reason, p))
                    self.add_event('safety', '%s；持续 %.0f 秒，目标扩大黑名单并触发安全脱困' %
                                   (reason, self.cfg['near_block_timeout']), 'warn')
                return
            self.safety_blocked_since = 0.0
            if self.target:
                if time.time() - self.goal_started > self.cfg['goal_timeout']:
                    p = self.target
                    self.cancel_goal()
                    if self.mode == 'exploring': self.blacklist_target(p, 'goal_timeout')
                    self.step = '单个目标超时，已跳过'
                return
            if self.mode == 'returning':
                p = self.current_pose()
                if p and math.hypot(p[0]-self.home[0], p[1]-self.home[1]) <= self.cfg['goal_tolerance']:
                    self.safety('disarm'); self.mode, self.step = 'complete', '已在原点附近，任务完成'; return
                self.send_goal(*self.home, returning=True); return
            best = self.choose_frontier()
            if not best and self.blacklist:
                wait = self.cfg['blacklist_retry_interval'] - (time.time() - self.last_blacklist_retry)
                if wait <= 0:
                    count = len(self.blacklist)
                    self.blacklist = []
                    self.last_blacklist_retry = time.time()
                    self.add_event('replan', '候选边界被临时降权耗尽，释放 %d 个目标并重新规划' % count, 'warn')
                    self.get_logger().warn('[frontier_retry] cleared=%d，重新评估仍存在的边界' % count)
                    best = self.choose_frontier()
                else:
                    self.step = '可探索边界暂时受阻，等待 %.0f 秒后重新规划（不返航）' % wait
                    return
            if not best:
                self.begin_return('没有剩余可探索边界'); return
            score, p, cells = best
            cur = self.current_pose(); yaw = math.atan2(p[1]-cur[1], p[0]-cur[0])
            self.add_event('decision', '选择边界：信息簇 %d 格、距离 %.2fm、风险评分 %.2f；避开已访问与临时禁区' %
                           (cells, math.hypot(p[0]-cur[0], p[1]-cur[1]), score))
            if self.send_goal(p[0], p[1], yaw):
                self.step = '前往探索边界（%d 格）' % cells

    def publish_state(self):
        self.validate_session()
        elapsed = time.time() - self.started_at if self.started_at else 0
        pose = self.current_pose()
        data = {'mode': self.mode, 'step': self.step, 'elapsed_sec': round(elapsed),
                'home': self.home, 'target': self.target, 'pose': pose,
                'home_restored': self.home_restored, 'home_saved_at': self.home_saved_at,
                'home_restore_status': self.home_restore_status,
                'recovery_available': self.recovery_available,
                'recovery_mode': self.recovery_mode,
                'recovery_last_target': self.recovery_last_target,
                'breadcrumbs': len(self.breadcrumbs),
                'events': list(self.events),
                'objects': list(self.objects),
                'visited': len(self.visited), 'blacklisted': len(self.blacklist),
                'map_ready': self.map_ready(), 'nav_ready': self.nav.server_is_ready(),
                'scan_ready': self.scan_ready(),
                'safety_ready': self.safety_ready(),
                'safety_armed': bool(self.safety_state and self.safety_state.get('armed')),
                'safety_legacy_active': bool(self.safety_state and self.safety_state.get('legacy_active')),
                'safety_front_m': None if not self.safety_state else self.safety_state.get('front_m'),
                'safety_body_m': None if not self.safety_state else self.safety_state.get('body_m'),
                'safety_vision_m': None if not self.safety_state else self.safety_state.get('vision_guard_m'),
                'clearance_ready': self.clearance_ready(),
                'arm_ready': self.snack_ready(), 'arm_stowed': self.arm_stowed(),
                'battery_v': None if self.batt_mv is None else round(self.batt_mv/1000, 2),
                'config': self.cfg}
        self.pub.publish(String(data=json.dumps(data, ensure_ascii=False)))


def main():
    rclpy.init(); node = Explorer()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        # systemd 停止进程时 ROS context 可能已关闭；此时 publish/shutdown 会抛异常，
        # 但安全闸门本身会独立锁定，清理路径不应制造误导性的失败日志。
        try:
            if rclpy.ok(): node.safety('disarm')
        except Exception:
            pass
        try: node.destroy_node()
        except Exception: pass
        try:
            if rclpy.ok(): rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__': main()
