#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_kinematics 自检：FK/IK 往返、工作空间扫描、舵机标定拟合。
纯标准库，Mac 上 `python3 agents/test_kinematics.py` 直接跑。"""
import math, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from arm_kinematics import (fk, fk_wrist, ik, ik_best, ik_auto_pitch, ServoMap,
                            L1, L2, L3, Z_SHOULDER, BASE_X, PULSE_PER_RAD)

fails = []
def check(name, cond, detail=''):
    (print(f'  ok   {name}') if cond else fails.append(f'{name} {detail}'))
    if not cond: print(f'  FAIL {name}  {detail}')

print('=== 1. FK 基本姿态 ===')
x, y, z, p = fk([0, 0, 0, 0, 0])
check('全零位=竖直伸直', abs(x - BASE_X) < 1e-9 and abs(y) < 1e-9 and
      abs(z - (Z_SHOULDER + L1 + L2 + L3)) < 1e-9, f'{x:.4f},{y:.4f},{z:.4f}')
print(f'  伸直高度 z = {z:.4f} m  (臂全长 {L1+L2+L3:.4f} m)')

x, y, z, p = fk([0, math.pi / 2, 0, 0, 0])
check('肩转90°=水平前伸', abs(z - Z_SHOULDER) < 1e-9 and
      abs(x - (BASE_X + L1 + L2 + L3)) < 1e-9, f'{x:.4f},{z:.4f}')
print(f'  最大水平前伸 x = {x:.4f} m')

x, y, z, p = fk([-math.pi / 2, math.pi / 2, 0, 0, 0])
check('joint1=-90°朝 +Y (轴为 0,0,-1)', abs(y - (L1 + L2 + L3)) < 1e-6 and abs(x - BASE_X) < 1e-6,
      f'{x:.4f},{y:.4f}')

print('\n=== 2. IK -> FK 往返 ===')
worst = 0.0
n_ok = n_try = 0
for tx in [0.10, 0.15, 0.20, 0.25, 0.30]:
    for ty in [-0.15, -0.05, 0.0, 0.05, 0.15]:
        for tz in [0.02, 0.06, 0.12, 0.20]:
            for pitch in [math.pi, math.radians(150), math.radians(90)]:
                n_try += 1
                q = ik_best(tx, ty, tz, pitch)
                if not q: continue
                n_ok += 1
                fx, fy, fz, fp = fk(q)
                e = math.dist((fx, fy, fz), (tx, ty, tz))
                worst = max(worst, e)
                if e > 1e-6:
                    print(f'  FAIL 位置误差 {e:.6f} @ {tx},{ty},{tz} pitch={math.degrees(pitch):.0f}')
                if abs(fp - pitch) > 1e-9:
                    print(f'  FAIL pitch 误差 {fp-pitch:.2e}')
check('往返最大位置误差 < 1e-9 m', worst < 1e-9, f'worst={worst:.3e}')
print(f'  {n_ok}/{n_try} 个位姿可达，最大误差 {worst:.2e} m')

print('\n=== 3. 关节限位 ===')
bad = []
for tx in [0.08, 0.12, 0.18, 0.24, 0.30]:
    for ty in [-0.2, 0.0, 0.2]:
        for tz in [0.0, 0.05, 0.15]:
            q = ik_best(tx, ty, tz, math.pi)
            if q and any(abs(v) > 2.09 + 1e-9 for v in q): bad.append((tx, ty, tz, q))
check('返回解全部在 ±2.09 rad 内', not bad, str(bad[:1]))

print('\n=== 4. 自动 pitch 兜底 ===')
NEAR, FAR = (0.10, 0.0, -0.086), (0.30, 0.0, -0.116)
check('近点 (0.10,0,0.03) 纯垂直抓不到', ik_best(*NEAR, math.pi) is None)
check('远点 (0.32,0,0.02) 纯垂直抓不到', ik_best(*FAR, math.pi) is None)
qn, pn = ik_auto_pitch(*NEAR)
check('近点靠后仰 pitch>180 抓到', qn is not None and pn > math.pi,
      f'pitch={None if pn is None else round(math.degrees(pn))}')
if qn: print(f'  {NEAR} -> pitch {math.degrees(pn):.0f}°  q={[round(math.degrees(v),1) for v in qn]}')
qf, pf = ik_auto_pitch(*FAR)
check('远点靠前倾 pitch<180 抓到', qf is not None and pf < math.pi,
      f'pitch={None if pf is None else round(math.degrees(pf))}')
if qf: print(f'  {FAR} -> pitch {math.degrees(pf):.0f}°  q={[round(math.degrees(v),1) for v in qf]}')
q2, _ = ik_auto_pitch(0.9, 0.0, 0.05)
check('明显够不着的点返回 None', q2 is None)

print('\n=== 5. 桌面垂直抓取可达范围 ===')
# base_link 在 base_footprint(轮子接地面) 上方 0.11609 m ——
# 机器人自己所站的那个台面在 base_link 系里是 -0.116，不是 0。
TABLE_Z = -0.11609
reach = []
xx = 0.05
while xx <= 0.45:
    if ik_best(xx, 0.0, TABLE_Z, math.pi): reach.append(xx)
    xx += 0.005
check('存在垂直抓取可达区间', len(reach) > 0)
if reach:
    print(f'  base_link 前方 x ∈ [{min(reach):.3f}, {max(reach):.3f}] m 可垂直下抓')
ymax = 0.0
yy = 0.0
while yy <= 0.4:
    if ik_best(0.20, yy, TABLE_Z, math.pi): ymax = yy
    yy += 0.005
print(f'  x=0.20 处侧向可达 |y| ≤ {ymax:.3f} m')
reach2 = []
xx = 0.05
while xx <= 0.45:
    if ik_auto_pitch(xx, 0.0, TABLE_Z)[0]: reach2.append(xx)
    xx += 0.005
print(f'  放开 pitch 后 x ∈ [{min(reach2):.3f}, {max(reach2):.3f}] m 可达')

print('\n=== 6. 舵机脉冲映射 ===')
sm = ServoMap()
check('零位 -> 500 脉冲', sm.to_pulse([0]*5) == [500]*5, str(sm.to_pulse([0]*5)))
check('+2.09 rad -> ~999 脉冲', abs(sm.to_pulse([2.09]*5)[0] - 999) <= 1, str(sm.to_pulse([2.09]*5)[0]))
check('-2.09 rad -> ~1 脉冲', abs(sm.to_pulse([-2.09]*5)[0] - 1) <= 1, str(sm.to_pulse([-2.09]*5)[0]))

# 模拟现场标定：真机 dir=[-1,1,-1,1,-1] center=[512,498,505,500,495]
truth = ServoMap(dirs=[-1, 1, -1, 1, -1], centers=[512, 498, 505, 500, 495])
samples = []
for a in (-0.6, -0.2, 0.3, 0.9):
    ang = [a] * 5
    samples.append((truth.to_pulse(ang), ang))
est = ServoMap()
done = est.calibrate_from_samples(samples)
check('5 个关节全部拟合出来', len(done) == 5, str(done))
check('方向 dir 拟合正确', est.dirs == truth.dirs, str(est.dirs))
check('零位 center 误差 < 1 脉冲',
      all(abs(a - b) < 1.0 for a, b in zip(est.centers, truth.centers)),
      str([round(c, 2) for c in est.centers]))
check('数据没动的关节不误标定', ServoMap().calibrate_from_samples(
      [(truth.to_pulse([0]*5), [0]*5), (truth.to_pulse([0]*5), [0]*5)]) == [])

print('\n=== 7. 相机(挂在 link4)腕心位置 ===')
q = ik_best(0.22, 0.0, -0.09, math.pi)
wx, wy, wz = fk_wrist(q)
ex, ey, ez, _ = fk(q)
check('腕心在末端上方 L3 处', abs(math.dist((wx, wy, wz), (ex, ey, ez)) - L3) < 1e-9,
      f'{math.dist((wx,wy,wz),(ex,ey,ez)):.6f}')
print(f'  抓 (0.22,0,-0.09) 时腕心/相机在 ({wx:.3f},{wy:.3f},{wz:.3f})')

print()
if fails:
    print(f'✗ {len(fails)} 项失败'); [print('  -', f) for f in fails]; sys.exit(1)
print('✓ 全部通过')
