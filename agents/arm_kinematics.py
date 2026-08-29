#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JetRover 5 轴机械臂正/逆运动学（纯 math，无第三方依赖，Mac 上可直接跑测试）

尺寸全部从 jetrover_description 的 URDF 里读出来的实测值：
    joint1  base_link -> link1        xyz (0.0251328, 0, 0.0774027)  axis (0,0,-1)
    joint2  servo_link1 -> link2      xyz (0, 0, 0.0338648)          axis (0,1,0)
    joint3  link2 -> link3            xyz (0, 0, 0.1294164)          axis (0,1,0)
    joint4  link3 -> link4            xyz (0, 0, 0.1294446)          axis (0,1,0)
    joint5  servo_link2 -> link5      xyz (0, 0, 0.0544833)          axis (0,0,-1)
    end_effector_link                 xyz (0, 0, 0.08)  相对 link5

于是这是一个「底座回转 + 竖直平面内 3 连杆 + 腕部自转」的结构，
平面部分有闭式解，不需要迭代 IK（Twin.vue 里的 CCD 只是可视化用）。

平面内角度约定：a 从 +Z 轴量起，向 +R（水平前方）为正，
连杆方向 = (sin a, cos a)。因此
    a = 0     竖直朝上
    a = pi/2  水平朝前
    a = pi    竖直朝下（垂直抓取姿态）
累计角 a1=q2, a2=q2+q3, a3=q2+q3+q4，a3 即末端俯仰(pitch)。
"""
import math

# ---- URDF 实测尺寸（米）----
BASE_X = 0.0251328065010765          # joint1 相对 base_link 的 x 偏置
Z_SHOULDER = 0.0774026880954513 + 0.0338648012164686   # base_link -> joint2 高度 = 0.1112675
L1 = 0.129416446394797               # joint2 -> joint3
L2 = 0.129444631186569               # joint3 -> joint4
L3 = 0.0544833339503674 + 0.08       # joint4 -> end_effector_link = 0.1344833

JOINT_LIMIT = 2.09                   # URDF 每个关节 ±2.09 rad（±119.8°）
JOINT_NAMES = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5']
SERVO_IDS = [1, 2, 3, 4, 5]
GRIPPER_ID = 10

# 幻尔总线舵机：脉冲 0~1000 对应 240°，中位 500。
# 与 URDF 的 ±2.09 rad(±119.8°) 限位刚好吻合 → 0~1000 用满。
PULSE_PER_RAD = 1000.0 / math.radians(240.0)   # 238.732


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


# ---------------- 正运动学 ----------------
def fk(q):
    """q = [q1..q5] (rad) -> 末端在 base_link 系的 (x, y, z) 与 pitch(rad)"""
    q1, q2, q3, q4 = q[0], q[1], q[2], q[3]
    a1, a2, a3 = q2, q2 + q3, q2 + q3 + q4
    r = L1 * math.sin(a1) + L2 * math.sin(a2) + L3 * math.sin(a3)
    z = Z_SHOULDER + L1 * math.cos(a1) + L2 * math.cos(a2) + L3 * math.cos(a3)
    # joint1 轴是 (0,0,-1)：关节值 q1 让手臂平面指向方位角 -q1
    psi = -q1
    x = BASE_X + r * math.cos(psi)
    y = r * math.sin(psi)
    return (x, y, z, a3)


def fk_wrist(q):
    """joint4（腕心）在 base_link 系的位置，深度相机就挂在 link4 上"""
    q1, q2, q3 = q[0], q[1], q[2]
    a1, a2 = q2, q2 + q3
    r = L1 * math.sin(a1) + L2 * math.sin(a2)
    z = Z_SHOULDER + L1 * math.cos(a1) + L2 * math.cos(a2)
    psi = -q1
    return (BASE_X + r * math.cos(psi), r * math.sin(psi), z)


# ---------------- 逆运动学 ----------------
def ik(x, y, z, pitch, elbow='up', wrist_roll=0.0, limit=JOINT_LIMIT):
    """闭式解。pitch = 末端轴与 +Z 的夹角（pi = 垂直向下抓）。
    返回 [q1..q5]（rad），不可达/超限返回 None。"""
    dx, dy = x - BASE_X, y
    psi = math.atan2(dy, dx)
    r = math.hypot(dx, dy)
    zs = z - Z_SHOULDER
    q1 = -psi

    # 腕心（joint4）位置：从末端沿 pitch 方向退 L3
    rw = r - L3 * math.sin(pitch)
    zw = zs - L3 * math.cos(pitch)

    d2 = rw * rw + zw * zw
    d = math.sqrt(d2)
    if d > L1 + L2 - 1e-6 or d < abs(L1 - L2) + 1e-6:
        return None                       # 超出/低于平面 2 连杆可达范围

    cos3 = (d2 - L1 * L1 - L2 * L2) / (2.0 * L1 * L2)
    q3 = math.acos(clamp(cos3, -1.0, 1.0))
    if elbow == 'up':
        q3 = -q3                          # 肘部向后弓，桌面抓取更常用
    beta = math.atan2(rw, zw)             # 腕心方向（从 +Z 量起）
    q2 = beta - math.atan2(L2 * math.sin(q3), L1 + L2 * math.cos(q3))
    q4 = pitch - q2 - q3
    q = [q1, q2, q3, q4, wrist_roll]
    for v in q:
        if abs(v) > limit + 1e-9:
            return None
    return q


def ik_best(x, y, z, pitch, seed=None, wrist_roll=0.0):
    """两种肘型都试，选可达且离 seed 最近的那个"""
    cands = [c for c in (ik(x, y, z, pitch, 'up', wrist_roll),
                         ik(x, y, z, pitch, 'down', wrist_roll)) if c]
    if not cands:
        return None
    if seed is None:
        return cands[0]
    return min(cands, key=lambda c: sum((a - b) ** 2 for a, b in zip(c[:4], seed[:4])))


def ik_auto_pitch(x, y, z, pitches=None, seed=None, wrist_roll=0.0):
    """按优先级尝试一串 pitch，返回 (q, pitch)。
    默认从「竖直向下」开始，逐步放平——离底座太近时纯垂直抓是够不着的。"""
    if pitches is None:
        # 180=纯垂直下抓（最干净）。往大了走(>180)是「向后仰着下抓」，够近处；
        # 往小了走(<180)是「斜着前伸」，够远处。交替试，优先离 180 近的。
        pitches = [math.radians(a) for a in
                   (180, 190, 170, 200, 160, 210, 150, 220, 140, 130, 120, 110, 100, 90)]
    for p in pitches:
        q = ik_best(x, y, z, p, seed, wrist_roll)
        if q:
            return q, p
    return None, None


# ---------------- 关节角 <-> 舵机脉冲 ----------------
class ServoMap:
    """脉冲 = center + dir * angle * PULSE_PER_RAD
    dir/center 出厂未知（取决于舵机装配方向与零位），可由 calibrate_from_samples()
    用驱动自己发的 /servo_states(脉冲) 与 /joint_states(弧度) 现场拟合出来。"""

    def __init__(self, dirs=None, centers=None):
        self.dirs = list(dirs) if dirs else [1.0] * 5
        self.centers = list(centers) if centers else [500.0] * 5

    def to_pulse(self, q):
        return [int(round(clamp(self.centers[i] + self.dirs[i] * q[i] * PULSE_PER_RAD, 0, 1000)))
                for i in range(5)]

    def to_angle(self, pulses):
        return [(pulses[i] - self.centers[i]) / (self.dirs[i] * PULSE_PER_RAD) for i in range(5)]

    def as_dict(self):
        return {'dirs': self.dirs, 'centers': self.centers}

    def calibrate_from_samples(self, samples, min_span=0.15):
        """samples: [(pulses[5], angles[5]), ...] 至少两组、且关节动过。
        对每个关节最小二乘拟合 pulse = center + k*angle，k 的符号即 dir。
        返回被成功标定的关节下标列表。"""
        done = []
        for i in range(5):
            xs = [s[1][i] for s in samples]
            ys = [s[0][i] for s in samples]
            n = len(xs)
            if n < 2 or (max(xs) - min(xs)) < min_span:
                continue
            mx, my = sum(xs) / n, sum(ys) / n
            sxx = sum((v - mx) ** 2 for v in xs)
            if sxx < 1e-9:
                continue
            k = sum((xs[j] - mx) * (ys[j] - my) for j in range(n)) / sxx
            if abs(k) < PULSE_PER_RAD * 0.5:      # 斜率离 ±238.7 太远 → 数据不可信
                continue
            self.dirs[i] = 1.0 if k > 0 else -1.0
            self.centers[i] = clamp(my - k * mx, 0.0, 1000.0)
            done.append(i)
        return done
