#!/usr/bin/env python3
"""Mac 本地机器人模拟器（最小 rosbridge v2 兼容实现，零第三方依赖）。

用于网页、探索/抓取流程及故障恢复联调；它不控制任何实体硬件，也不是物理仿真。
运行：python3 tools/sim_robot.py，然后打开 http://localhost:5274/?sim=1#explore
"""
import argparse
import asyncio
import base64
import hashlib
import json
import math
import os
import struct
import time
import uuid


TOPICS = {
    '/ros_robot_controller/battery': 'std_msgs/msg/UInt16',
    '/odom': 'nav_msgs/msg/Odometry', '/scan': 'sensor_msgs/msg/LaserScan',
    '/map': 'nav_msgs/msg/OccupancyGrid', '/jetson/stats': 'std_msgs/msg/String',
    '/snack_butler/state': 'std_msgs/msg/String', '/explorer/state': 'std_msgs/msg/String',
    '/nav_safety/state': 'std_msgs/msg/String', '/system/log': 'std_msgs/msg/String',
    '/system/services': 'std_msgs/msg/String', '/controller_manager/joint_states': 'sensor_msgs/msg/JointState',
}


def string(data):
    return {'data': json.dumps(data, ensure_ascii=False)}


class SimRobot:
    def __init__(self):
        self.clients = set()
        self.subs = {}
        self.x = self.y = self.yaw = 0.0
        self.batt = 11640
        self.faults = set()
        self.explorer = {'mode': 'idle', 'step': '本地模拟器待命', 'home': None,
                         'recovery_available': False, 'visited': 0, 'blacklist': 0,
                         'breadcrumbs': 0, 'events': []}
        self.snack = {'state': 'IDLE', 'step': '本地模拟器待命', 'detector': 'hybrid',
                      'model': 'simulated', 'objects': [], 'recovery': None}
        self.nav = {'armed': False, 'locked': True, 'lidar_ok': True, 'reason': '模拟安全闸门锁定'}
        self.last_log = '本地仿真环境已启动；不会向实体机器人发送任何控制命令'

    def log(self, src, msg, lvl='info'):
        self.last_log = msg
        self.publish('/system/log', string({'t': time.strftime('%F %T'), 'src': src, 'msg': msg, 'lvl': lvl}))

    def publish(self, topic, msg):
        for client in list(self.subs.get(topic, set())):
            client.send({'op': 'publish', 'topic': topic, 'msg': msg})

    def command(self, topic, data):
        try:
            cmd = json.loads(data.get('data', '{}'))
        except (TypeError, json.JSONDecodeError):
            return
        action = cmd.get('action')
        if topic == '/sim/cmd':
            name = cmd.get('fault')
            if action == 'fault' and name:
                self.faults.add(name); self.log('sim', f'已注入故障：{name}', 'warn')
            elif action == 'clear_fault':
                self.faults.discard(name); self.log('sim', f'已清除故障：{name}')
            elif action == 'reset':
                self.faults.clear(); self.explorer.update(mode='idle', step='模拟器已重置', recovery_available=False)
                self.snack.update(state='IDLE', step='模拟器已重置', recovery=None)
            return
        if topic == '/explorer/cmd':
            if action == 'start':
                self.explorer.update(mode='exploring', step='正在模拟 Frontier 探索', home=[self.x, self.y, self.yaw], recovery_available=False)
                self.nav.update(armed=True, locked=False, reason='模拟探索已解锁')
            elif action == 'pause': self.explorer.update(mode='paused', step='模拟任务已暂停')
            elif action == 'resume':
                self.explorer.update(mode='exploring', step='已人工确认继续模拟探索', recovery_available=False)
                self.nav.update(armed=True, locked=False)
            elif action in ('home', 'returnHome'):
                self.explorer.update(mode='returning', step='正在模拟返航')
            elif action == 'stop':
                self.explorer.update(mode='idle', step='模拟任务已停止')
                self.nav.update(armed=False, locked=True, reason='模拟任务停止')
            self.log('explorer-agent', self.explorer['step'])
        elif topic == '/snack_butler/cmd':
            if self.snack.get('recovery') and action not in ('recover', 'stop'):
                return
            if action in ('pick', 'grasp', 'auto'):
                self.snack.update(state='WORKING', step='模拟抓取：移动至预抓取位')
                self.snack['recovery'] = {'pending': True, 'phase': 'pre_grasp', 'id': uuid.uuid4().hex[:8]}
            elif action == 'recover':
                self.snack.update(state='IDLE', step='模拟安全恢复完成，已回观察位', recovery=None)
            elif action == 'stop': self.snack.update(state='RECOVERY', step='模拟动作已停止，等待安全恢复')
            self.log('snack-butler', self.snack['step'])
        elif topic == '/nav_safety/cmd':
            if action == 'arm': self.nav.update(armed=True, locked=False, reason='模拟安全闸门已解锁')
            if action in ('disarm', 'lock'): self.nav.update(armed=False, locked=True, reason='模拟安全闸门已锁定')

    def tick(self):
        now = time.time()
        lidar_ok = 'lidar_offline' not in self.faults
        self.nav['lidar_ok'] = lidar_ok
        if self.explorer['mode'] == 'exploring' and lidar_ok:
            self.x += 0.025 * math.cos(self.yaw); self.y += 0.025 * math.sin(self.yaw)
            self.yaw += 0.018; self.explorer['visited'] += 1
            self.explorer['breadcrumbs'] = min(80, self.explorer['breadcrumbs'] + 1)
            if self.explorer['visited'] % 60 == 0: self.log('explorer-agent', '模拟 Frontier 目标已完成，寻找下一个边界')
        if 'service_restart' in self.faults:
            self.faults.discard('service_restart')
            if self.explorer['mode'] in ('exploring', 'returning', 'paused'):
                self.explorer.update(mode='recovery', step='发现中断任务，底盘已锁定；请确认继续探索或立即返航', recovery_available=True)
                self.nav.update(armed=False, locked=True, reason='模拟服务重启恢复锁')
            if self.snack['state'] == 'WORKING':
                self.snack.update(state='RECOVERY', step='动作中断，等待人工安全恢复')
            self.log('sim', '已模拟服务重启：所有未完成任务均进入人工恢复状态', 'warn')
        qz, qw = math.sin(self.yaw / 2), math.cos(self.yaw / 2)
        if 'battery_low' in self.faults: self.batt = 9600
        else: self.batt = min(11800, self.batt + 1)
        self.publish('/ros_robot_controller/battery', {'data': self.batt})
        self.publish('/odom', {'pose': {'pose': {'position': {'x': self.x, 'y': self.y, 'z': 0}, 'orientation': {'x': 0, 'y': 0, 'z': qz, 'w': qw}}},
                               'twist': {'twist': {'linear': {'x': .05 if self.explorer['mode'] == 'exploring' else 0, 'y': 0, 'z': 0}, 'angular': {'x': 0, 'y': 0, 'z': .036 if self.explorer['mode'] == 'exploring' else 0}}}})
        self.publish('/scan', {'angle_min': -3.14, 'angle_increment': 0.0174, 'range_min': .12, 'range_max': 8.0,
                               'ranges': ([] if not lidar_ok else [1.4 + .3 * math.sin(i / 20) for i in range(360)])})
        self.publish('/map', self.map_msg())
        self.publish('/jetson/stats', string({'online': True, 'gpu': 17, 'gpu_mem': 312,
            'cpu': [{'load': 13}, {'load': 11}, {'load': 15}, {'load': 12}], 'temps': {'cpu': 43, 'gpu': 42},
            'ram_used': 1420, 'ram_total': 4096, 'power': 7.8, 'simulated': True, 'at': now}))
        self.publish('/explorer/state', string({**self.explorer, 'pose': [round(self.x, 2), round(self.y, 2), round(self.yaw, 2)],
            'elapsed_sec': self.explorer['visited'] // 2, 'battery_v': round(self.batt / 1000, 2),
            'map_ready': True, 'scan_ready': lidar_ok, 'nav_ready': True, 'safety_ready': True,
            'safety_armed': self.nav['armed'], 'arm_ready': True, 'arm_stowed': True,
            'clearance_ready': True, 'safety_legacy_active': False, 'lidar_ok': lidar_ok,
            'safety_vision_m': 1.2, 'safety_front_m': 1.4, 'safety_body_m': 1.1, 'events': []}))
        self.publish('/snack_butler/state', string(self.snack))
        self.publish('/nav_safety/state', string(self.nav))
        self.publish('/system/services', string({'services': [
            {'name': n, 'active': 'active', 'status': 'running'} for n in ('snack-butler', 'explorer-agent', 'nav-safety')]}))
        self.publish('/controller_manager/joint_states', {'name': ['joint1', 'joint2', 'joint3', 'joint4', 'joint5'],
                                                           'position': [0, .14, 1.32, 1.77, 0]})

    @staticmethod
    def map_msg():
        width = height = 80
        data = [0] * (width * height)
        for y in range(height):
            for x in range(width):
                if x < 3 or y < 3 or x > 76 or y > 76 or (32 < x < 37 and 12 < y < 57): data[y * width + x] = 100
                elif (x + y) % 17 == 0: data[y * width + x] = -1
        return {'info': {'resolution': .1, 'width': width, 'height': height, 'origin': {'position': {'x': -4, 'y': -4, 'z': 0}, 'orientation': {'w': 1}}}, 'data': data}


class WsClient:
    def __init__(self, writer): self.writer, self.lock = writer, asyncio.Lock()
    def send(self, value): asyncio.create_task(self._send(value))
    async def _send(self, value):
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
        n = len(raw); header = bytes([0x81]) + (bytes([n]) if n < 126 else bytes([126]) + struct.pack('!H', n))
        async with self.lock:
            self.writer.write(header + raw); await self.writer.drain()


async def websocket(reader, writer, sim):
    try:
        request = await reader.readuntil(b'\r\n\r\n')
        key = next(x.split(':', 1)[1].strip() for x in request.decode().split('\r\n') if x.lower().startswith('sec-websocket-key:'))
        accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        writer.write(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + '\r\n\r\n').encode()); await writer.drain()
        client = WsClient(writer); sim.clients.add(client)
        while True:
            first = await reader.readexactly(2); length = first[1] & 127
            if length == 126: length = struct.unpack('!H', await reader.readexactly(2))[0]
            elif length == 127: length = struct.unpack('!Q', await reader.readexactly(8))[0]
            mask = await reader.readexactly(4) if first[1] & 128 else b''
            payload = bytearray(await reader.readexactly(length))
            if mask:
                for i in range(length): payload[i] ^= mask[i % 4]
            if first[0] & 15 == 8: break
            try: message = json.loads(payload)
            except json.JSONDecodeError: continue
            op, topic = message.get('op'), message.get('topic')
            if op == 'subscribe': sim.subs.setdefault(topic, set()).add(client)
            elif op == 'unsubscribe': sim.subs.get(topic, set()).discard(client)
            elif op == 'publish': sim.command(topic, message.get('msg', {}))
            elif op == 'call_service':
                response = {'op': 'service_response', 'service': message.get('service'), 'id': message.get('id'), 'result': True, 'values': {}}
                if message.get('service') == '/rosapi/topics': response['values'] = {'topics': list(TOPICS), 'types': list(TOPICS.values())}
                elif message.get('service') == '/rosapi/nodes': response['values'] = {'nodes': ['/sim_robot', '/explorer-agent', '/snack-butler']}
                elif message.get('service') == '/rosapi/services': response['values'] = {'services': ['/rosapi/topics', '/rosapi/nodes', '/rosapi/services']}
                client.send(response)
    except (asyncio.IncompleteReadError, ConnectionError, StopAsyncIteration): pass
    finally:
        sim.clients.discard(locals().get('client'))
        for subscribers in sim.subs.values(): subscribers.discard(locals().get('client'))
        writer.close(); await writer.wait_closed()


async def main(port):
    sim = SimRobot()
    server = await asyncio.start_server(lambda r, w: websocket(r, w, sim), '127.0.0.1', port)
    print(f'模拟 rosbridge 已监听 ws://127.0.0.1:{port}（按 Ctrl-C 退出）', flush=True)
    async with server:
        while True:
            sim.tick(); await asyncio.sleep(.5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=19090)
    asyncio.run(main(parser.parse_args().port))
