#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vision_geometry 自检：相机外参链自洽性 + 像素<->世界往返 + 桌面射线兜底"""
import math, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from arm_kinematics import ik_best, ik_auto_pitch, fk, fk_wrist
from vision_geometry import (T_base_optical, T_LINK4_OPTICAL, deproject, project,
                             pixel_to_base, ray_to_base, ray_plane_z,
                             pixel_to_base_on_plane, mat_apply, tf_to_mat)

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + detail) if not cond else ''))
    if not cond: fails.append(name)

# Orbbec Gemini 类深度相机 640x480 的典型内参（真机会用 /camera_info 覆盖）
W, H = 640, 480
K = [477.0, 0.0, 319.5, 0.0, 477.0, 239.5, 0.0, 0.0, 1.0]

print('=== 1. 光学系约定 ===')
p = deproject(319.5, 239.5, 0.5, K)
check('主点反投影 = 正前方', abs(p[0]) < 1e-9 and abs(p[1]) < 1e-9 and abs(p[2] - 0.5) < 1e-9, str(p))
p = deproject(619.5, 239.5, 1.0, K)
check('像素往右 -> 光学系 +x', p[0] > 0, str(p))
p = deproject(319.5, 439.5, 1.0, K)
check('像素往下 -> 光学系 +y', p[1] > 0, str(p))
uv = project(deproject(120, 400, 0.42, K), K)
check('投影/反投影往返', abs(uv[0] - 120) < 1e-6 and abs(uv[1] - 400) < 1e-6, str(uv))

print('\n=== 2. 观察位姿下相机朝向 ===')
# base_link 在轮子接地面上方 0.11609 m，所以机器人所站的台面 z = -0.116
TABLE_Z = -0.116
# 观察位（由「可抓格点 × 视场覆盖」搜索得到）：169/169 全覆盖，夹爪不进画面
q_obs = [math.radians(a) for a in (0.0, 8.0, 75.6, 101.4, 0.0)]
check('观察位在限位内', all(abs(v) <= 2.09 for v in q_obs))
T = T_base_optical(q_obs)
cam = (T[0][3], T[1][3], T[2][3])
fwd = (T[0][2], T[1][2], T[2][2])      # 光学系 z = 视线方向
right = (T[0][0], T[1][0], T[2][0])    # 光学系 x = 画面右
down = (T[0][1], T[1][1], T[2][1])     # 光学系 y = 画面下
print(f'  关节角 {[round(math.degrees(v),1) for v in q_obs]}')
print(f'  相机位置 base_link ({cam[0]:.3f}, {cam[1]:.3f}, {cam[2]:.3f})')
print(f'  视线方向 ({fwd[0]:+.3f}, {fwd[1]:+.3f}, {fwd[2]:+.3f})')
print(f'  画面右   ({right[0]:+.3f}, {right[1]:+.3f}, {right[2]:+.3f})')
print(f'  画面下   ({down[0]:+.3f}, {down[1]:+.3f}, {down[2]:+.3f})')
check('相机悬在可抓区上方', 0.10 < cam[0] < 0.30 and cam[2] > 0.15, str(cam))
# 搜索出来的观察位几乎是正俯视(nadir)。这比斜看好：视差小，深度失效走平面兜底时
# 桌面高度估错的横向放大系数≈tan(视线与竖直夹角)，几乎为 0。
check('视线接近垂直向下', fwd[2] < -0.95, f'{fwd} 与竖直夹角 {math.degrees(math.acos(-fwd[2])):.1f}°')
check('画面右 ≈ base -Y（相机横滚为0，画面不歪）', abs(right[2]) < 0.05 and right[1] < -0.9, str(right))
check('三轴正交', abs(sum(a*b for a,b in zip(fwd,right))) < 1e-9
      and abs(sum(a*b for a,b in zip(fwd,down))) < 1e-9, 'not orthogonal')

print('\n=== 3. 像素 <-> base_link 往返 ===')
target = (0.20, 0.04, TABLE_Z + 0.03)   # 桌上一块 3cm 高的零食
rel = mat_apply([[T[j][i] for j in range(3)] + [0] for i in range(3)] + [[0,0,0,1]],
                (target[0]-cam[0], target[1]-cam[1], target[2]-cam[2]))  # 世界->光学系(R^T)
uvp = project(rel, K)
check('目标落在画面内', uvp is not None and 0 <= uvp[0] < W and 0 <= uvp[1] < H,
      str(uvp))
if uvp:
    print(f'  base {target} -> 像素 ({uvp[0]:.1f}, {uvp[1]:.1f}), 深度 {rel[2]:.3f} m')
    back = pixel_to_base(uvp[0], uvp[1], rel[2], K, q_obs)
    err = math.dist(back, target)
    check('像素+深度 反算回 base_link 误差 < 1e-9', err < 1e-9, f'{err:.3e} {back}')

R_wo = [[T[j][i] for j in range(3)] + [0] for i in range(3)] + [[0, 0, 0, 1]]
def to_px(pt):
    rel = mat_apply(R_wo, (pt[0]-cam[0], pt[1]-cam[1], pt[2]-cam[2]))
    return project(rel, K) if rel[2] > 0.01 else None
corners = [(0.13,-0.15,TABLE_Z), (0.13,0.15,TABLE_Z),
           (0.26,-0.15,TABLE_Z), (0.26,0.15,TABLE_Z)]
cpx = [to_px(c) for c in corners]
check('可抓桌面区(x .13~.26, y ±.15)四角全在画面内',
      all(c and 0 <= c[0] < W and 0 <= c[1] < H for c in cpx),
      str([None if not c else (round(c[0]),round(c[1])) for c in cpx]))
print('  桌面四角像素:', [(round(c[0]), round(c[1])) for c in cpx])
gr = fk(q_obs)[:3]
gpx = to_px(gr)
check('夹爪自身不挡镜头', not (gpx and 0 <= gpx[0] < W and 0 <= gpx[1] < H), str(gpx))

print('\n=== 4. 深度失效时的桌面射线兜底 ===')
o, d = ray_to_base(uvp[0], uvp[1], K, q_obs)
hit = ray_plane_z(o, d, TABLE_Z + 0.03)
check('射线与桌面求交成功', hit is not None)
if hit:
    err = math.hypot(hit[0]-target[0], hit[1]-target[1])
    check('目标本就在桌面上 -> 与真值一致', err < 1e-9, f'{err:.3e} {hit}')
    print(f'  无深度时解出 ({hit[0]:.4f}, {hit[1]:.4f}, {hit[2]:.4f})')
# 物体实际比假设桌面高 2cm 时，平面法会产生多大偏差？
hit2 = ray_plane_z(o, d, TABLE_Z + 0.05)
print(f'  若桌面高度估错 2cm -> 水平偏差 {math.hypot(hit2[0]-target[0], hit2[1]-target[1])*1000:.1f} mm')
check('朝天的射线不返回交点', ray_plane_z((0,0,0.5), (0,0,1.0), TABLE_Z) is None)

print('\n=== 5. 手眼耦合：抓取时相机会跟着动 ===')
q_grasp, _ = ik_auto_pitch(*target)
Tg = T_base_optical(q_grasp)
camg = (Tg[0][3], Tg[1][3], Tg[2][3])
print(f'  观察位相机 ({cam[0]:.3f},{cam[1]:.3f},{cam[2]:.3f})'
      f' -> 抓取位相机 ({camg[0]:.3f},{camg[1]:.3f},{camg[2]:.3f})')
check('相机确实随臂移动（必须在观察位定位、不能边下探边算）',
      math.dist(cam, camg) > 0.03, f'{math.dist(cam,camg):.3f} m')

print('\n=== 6. tf2 四元数转换 ===')
m = tf_to_mat((1, 2, 3), (0, 0, math.sin(math.pi/4), math.cos(math.pi/4)))  # 绕z 90°
r = mat_apply(m, (1, 0, 0))
check('绕 Z 转 90° 后 +X -> +Y', abs(r[0]-1) < 1e-9 and abs(r[1]-3) < 1e-9 and abs(r[2]-3) < 1e-9, str(r))

print()
if fails: print(f'✗ {len(fails)} 项失败:', fails); sys.exit(1)
print('✓ 全部通过')
