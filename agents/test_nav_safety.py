#!/usr/bin/env python3
"""纯标准库验证导航安全闸门的方向、限速、减速和急停。"""
import math
from types import SimpleNamespace

from nav_safety_logic import safe_velocity, twist_nonzero


def scan(obstacles=()):
    n = 360
    values = [5.0] * n
    for deg, distance in obstacles:
        values[int(deg) % n] = distance
    return SimpleNamespace(ranges=values, angle_min=0.0, angle_increment=2*math.pi/n,
                           range_min=.12, range_max=12.0)


def check(name, cond):
    if not cond: raise AssertionError(name)
    print('ok ', name)


vx, vy, wz, _ = safe_velocity(1, 1, 2, scan())
check('三轴硬限速', (vx, vy, wz) == (.12, .08, .45))

vx, vy, _, reason = safe_velocity(.1, 0, 0, scan([(0, .25)]))
check('前方近障停止前进', vx == 0 and vy == 0 and '急停' in reason)

vx, _, _, _ = safe_velocity(-.1, 0, 0, scan([(180, .25)]))
check('后方近障停止倒车', vx == 0)

vx, _, _, _ = safe_velocity(.1, 0, 0, scan([(90, .25)]))
check('侧面障碍不误停直行', vx > 0)

_, vy, _, _ = safe_velocity(0, .08, 0, scan([(90, .25)]))
check('侧向运动按对应扇区急停', vy == 0)

vx, _, _, _ = safe_velocity(.1, 0, 0, scan([(0, .55)]))
check('减速区按距离降速', 0 < vx < .1)

_, _, wz, _ = safe_velocity(0, 0, .3, scan([(225, .25)]))
check('原地旋转检查全车周围', wz == 0)

vx, _, _, _ = safe_velocity(.1, 0, 0, scan([(0, float('nan')), (1, float('inf'))]))
check('忽略无效雷达值', vx > 0)

# 真机 lidar_frame 相对 base_link 转了 180°：雷达 180° 才是车头。
vx, _, _, reason = safe_velocity(.1, 0, 0, scan([(180, .25)]), scan_forward_angle=math.pi)
check('雷达反装时正确识别车头近障', vx == 0 and '急停' in reason)
vx, _, _, _ = safe_velocity(.1, 0, 0, scan([(0, .25)]), scan_forward_angle=math.pi)
check('雷达反装时车尾障碍不误停前进', vx > 0)

zero = SimpleNamespace(linear=SimpleNamespace(x=0, y=0, z=0),
                       angular=SimpleNamespace(x=0, y=0, z=0))
moving = SimpleNamespace(linear=SimpleNamespace(x=.01, y=0, z=0),
                         angular=SimpleNamespace(x=0, y=0, z=0))
check('零速度不触发旧入口告警', not twist_nonzero(zero))
check('非零旧入口会触发告警', twist_nonzero(moving))

print('\n✓ 导航安全逻辑全部通过')
