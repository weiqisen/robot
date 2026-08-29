#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离线全链路验证：合成一张「观察位看桌面」的 RGB+深度图 -> 跑真实的 ColorDetector ->
跑真实的定位逻辑 -> 比对还原出的 base_link 坐标与真值 -> 跑 IK 看抓不抓得到。

说明：渲染用的是同一套相机模型，所以这不能证明外参标定对（那必须真机验），
但它能证明**识别、像素->坐标、工作区裁剪、深度失效兜底、IK 可达性**这几段代码是通的，
并且给出「桌面高度估错多少 => 抓偏多少毫米」这种上真机前必须心里有数的量。
需要 numpy + opencv：python3 -m venv venv && venv/bin/pip install numpy opencv-python-headless
"""
import math, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import cv2
from arm_kinematics import ik_auto_pitch, ik_best
from vision_geometry import T_base_optical, deproject, project, mat_apply, pixel_to_base, \
    pixel_to_base_on_plane
from snack_detector import ColorDetector, locate as locate_3d

W, H = 640, 480
K = [477.0, 0.0, 319.5, 0.0, 477.0, 239.5, 0.0, 0.0, 1.0]
TABLE_Z = -0.116          # 机器人所站的台面（base_link 在轮子接地面上方 0.116 m）
OBSERVE = [math.radians(a) for a in (0.0, 8.0, 75.6, 101.4, 0.0)]

# 真值：桌上四块「零食」(x, y, 高度, 半径, 颜色)
SNACKS = [
    (0.175, 0.075, 0.030, 0.022, 'red'),
    (0.225, -0.045, 0.025, 0.020, 'green'),
    (0.250, 0.055, 0.035, 0.024, 'blue'),
    (0.145, -0.100, 0.022, 0.018, 'yellow'),
]
BGR = {'red': (40, 40, 210), 'green': (60, 170, 60), 'blue': (200, 110, 40),
       'yellow': (50, 200, 220)}

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + detail) if not cond else ''))
    if not cond: fails.append(name)


def render():
    """逐像素向桌面/物体顶面投射射线，生成 RGB(bgr8) 与深度(16UC1, mm)"""
    T = T_base_optical(OBSERVE)
    cam = np.array([T[0][3], T[1][3], T[2][3]])
    R = np.array([[T[i][j] for j in range(3)] for i in range(3)])
    rgb = np.zeros((H, W, 3), np.uint8)
    depth = np.zeros((H, W), np.uint16)
    uu, vv = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    dirs_c = np.stack([(uu - K[2]) / K[0], (vv - K[5]) / K[4], np.ones_like(uu)], -1)
    dirs = dirs_c @ R.T                                     # 光学系 -> base
    for plane_z, color, mask_fn in (
            [(TABLE_Z, (120, 120, 120), None)] +
            [(TABLE_Z + s[2], BGR[s[4]], s) for s in SNACKS]):
        with np.errstate(divide='ignore', invalid='ignore'):
            t = (plane_z - cam[2]) / dirs[..., 2]
        hit = (t > 0) & np.isfinite(t)
        px = cam[0] + dirs[..., 0] * t
        py = cam[1] + dirs[..., 1] * t
        if mask_fn is None:
            m = hit
        else:
            sx, sy, sh, sr, _ = mask_fn
            m = hit & (((px - sx) ** 2 + (py - sy) ** 2) < sr ** 2)
        # 深度图存的是**光学系 Z**，不是到相机的欧氏距离——离画面中心越远两者差越多。
        # (dirs 是 (u',v',1) 转到 base 系的未归一化方向，所以 z_optical 正好就是 t)
        dist = t
        # 只画更近的表面（物体顶面盖住桌面）
        cur = depth.astype(np.float32) / 1000.0
        closer = m & ((cur == 0) | (dist < cur))
        rgb[closer] = color
        depth[closer] = np.clip(dist[closer] * 1000.0, 0, 65535).astype(np.uint16)
    noise = np.random.default_rng(7).normal(0, 4, rgb.shape)
    return np.clip(rgb.astype(np.float32) + noise, 0, 255).astype(np.uint8), depth


class Cfg(dict):
    pass


CFG = {
    'min_area_px': 400, 'max_area_px': 60000,
    'enabled_colors': ['red', 'green', 'blue', 'yellow'],
    'colors': {
        "red": [[[0, 110, 80], [8, 255, 255]], [[170, 110, 80], [180, 255, 255]]],
        "yellow": [[[23, 110, 90], [35, 255, 255]]],
        "green": [[[36, 80, 60], [85, 255, 255]]],
        "blue": [[[86, 90, 60], [125, 255, 255]]],
    },
}

print('=== 1. 渲染合成场景 ===')
rgb, depth = render()
check('画面里有非桌面像素', int((depth > 0).sum()) > W * H * 0.5, str((depth > 0).sum()))
print(f'  深度范围 {depth[depth>0].min()/1000:.3f} ~ {depth.max()/1000:.3f} m')

print('\n=== 2. 识别 ===')
dets = ColorDetector(CFG).detect(rgb)
check('识别到 4 块零食', len(dets) == 4, f'实际 {len(dets)}: {[d["label"] for d in dets]}')
for d in dets:
    print(f'  {d["label"]:7s} 像素({d["u"]:6.1f},{d["v"]:6.1f}) 面积{d["area"]:7.0f} 填充{d["fill"]:.2f}')

print('\n=== 3. 深度定位（跑的是 snack_detector.locate 生产代码）===')
T_bo = T_base_optical(OBSERVE)
ASSUME_H = 0.028
def truth_of(p):
    return min(SNACKS, key=lambda s: (s[0]-p[0])**2 + (s[1]-p[1])**2)

errs, located = [], {}
for d in dets:
    p, how = locate_3d(d, depth, rgb.shape, K, T_bo, TABLE_Z, ASSUME_H)
    t = truth_of(p)
    located[d['label']] = (p, t)
    ehz = math.hypot(p[0]-t[0], p[1]-t[1]); evz = abs(p[2] - (TABLE_Z + t[2]))
    errs.append(ehz)
    print(f'  {d["label"]:7s} [{how}] -> ({p[0]:.4f},{p[1]:.4f},{p[2]:.4f})  '
          f'真值({t[0]:.3f},{t[1]:.3f},{TABLE_Z+t[2]:.3f})  '
          f'水平 {ehz*1000:5.1f} mm  高度 {evz*1000:4.1f} mm')
    check(f'{d["label"]} 颜色匹配', d['label'] == t[4], f'{d["label"]} vs {t[4]}')
check('全部水平误差 < 3 mm（掩膜内 3D 中位数 + 对称剔野值）',
      max(errs) < 0.003, f'max={max(errs)*1000:.1f}mm')
check('全部高度误差 < 3 mm', max(abs(located[d['label']][0][2] - (TABLE_Z + located[d['label']][1][2]))
                                for d in dets) < 0.003)

print('\n对照：质心那块正好没有深度时（反光高光/黑色印刷区），单点 vs 掩膜中位数')
rng = np.random.default_rng(3)
depth_bad = depth.copy()
depth_bad[rng.random(depth.shape) < 0.35] = 0          # 全局 35% 空洞
for d in dets:                                          # 再把质心周围 12px 整块打掉
    cv2.circle(depth_bad, (int(d['u']), int(d['v'])), 12, 0, -1)
n_single_lost = 0
mask_errs = []
for d in dets:
    t = located[d['label']][1]
    win = depth_bad[int(d['v'])-7:int(d['v'])+8, int(d['u'])-7:int(d['u'])+8].astype(np.float32)/1000.
    vv = win[win > 0.05]
    single = '取不到深度 -> 只能退平面法' if vv.size < 5 else f'{vv.size} 个有效点'
    if vv.size < 5: n_single_lost += 1
    pm, how = locate_3d(d, depth_bad, rgb.shape, K, T_bo, TABLE_Z, ASSUME_H)
    em = math.hypot(pm[0]-t[0], pm[1]-t[1]); mask_errs.append((em, how))
    print(f'  {d["label"]:7s} 单点窗口: {single:26s} 掩膜中位数[{how}] 误差 {em*1000:4.1f} mm')
check('单点窗口这时全军覆没', n_single_lost == len(dets), f'{n_single_lost}/{len(dets)}')
check('掩膜中位数仍走深度路径', all(h == 'depth' for _, h in mask_errs),
      str([h for _, h in mask_errs]))
check('且精度仍 < 5 mm', max(e for e, _ in mask_errs) < 0.005,
      f'{max(e for e,_ in mask_errs)*1000:.1f}mm')

print('\n=== 4. 深度失效时的平面兜底 ===')
print('  (a) 交在「桌面」上 —— 错的，因为看到的是物体顶面')
bad = []
for d in dets:
    p, how = locate_3d(d, None, rgb.shape, K, T_bo, TABLE_Z, 0.0)
    t = located[d['label']][1]
    e = math.hypot(p[0]-t[0], p[1]-t[1]); bad.append(e)
    print(f'    {d["label"]:7s} 物体高 {t[2]*1000:.0f} mm -> 偏差 {e*1000:5.1f} mm')
print(f'  (b) 交在「桌面 + 假设物体高 {ASSUME_H*1000:.0f}mm」上 —— 现在的做法')
good = []
for d in dets:
    p, how = locate_3d(d, None, rgb.shape, K, T_bo, TABLE_Z, ASSUME_H)
    t = located[d['label']][1]
    e = math.hypot(p[0]-t[0], p[1]-t[1]); good.append(e)
    print(f'    {d["label"]:7s} 物体高 {t[2]*1000:.0f} mm (差 {abs(t[2]-ASSUME_H)*1000:.0f}mm) '
          f'-> 偏差 {e*1000:5.1f} mm')
check('假设物体高把兜底误差压下来了', max(good) < max(bad) * 0.5,
      f'{max(good)*1000:.1f} vs {max(bad)*1000:.1f} mm')
check('兜底偏差在夹爪容差内 (<10mm)', max(good) < 0.010, f'{max(good)*1000:.1f}mm')

print('\n=== 5. 工作区裁剪 + IK 可达性 ===')
WS_REL = {'x': [0.11, 0.28], 'y': [-0.17, 0.17], 'z': [-0.03, 0.12]}   # z 相对桌面
n_reach = 0
for d in dets:
    p = located[d['label']][0]
    inws = (WS_REL['x'][0] <= p[0] <= WS_REL['x'][1] and WS_REL['y'][0] <= p[1] <= WS_REL['y'][1]
            and WS_REL['z'][0] <= p[2] - TABLE_Z <= WS_REL['z'][1])
    gz = max(p[2] - 0.015, TABLE_Z + 0.005)
    q, pitch = ik_auto_pitch(p[0], p[1], gz)
    if inws and q: n_reach += 1
    print(f'  {d["label"]:7s} 在工作区={inws}  IK={"可解 pitch %.0f°" % math.degrees(pitch) if q else "无解"}')
check('4 块零食全部可抓', n_reach == 4, f'{n_reach}/4')

print('\n=== 6. 误检抑制：画面外的干扰色块 ===')
rgb2 = rgb.copy()
cv2.circle(rgb2, (60, 60), 30, (40, 40, 210), -1)      # 画面左上角一团红 = 地面/远处杂物
dets2 = ColorDetector(CFG).detect(rgb2)
extra = [d for d in dets2 if d['v'] < 120 and d['u'] < 140]
check('干扰块确实被识别成了色块（说明它进得来）', len(extra) == 1, str(len(extra)))
if extra:
    p, _ = locate_3d(extra[0], depth, rgb.shape, K, T_bo, TABLE_Z, ASSUME_H)
    inws = p is not None and (WS_REL['x'][0] <= p[0] <= WS_REL['x'][1]
                              and WS_REL['y'][0] <= p[1] <= WS_REL['y'][1])
    print(f'  干扰块投影到 {None if p is None else tuple(round(v,3) for v in p)}')
    check('工作区裁剪把它挡掉了', not inws)

print('\n=== 7. 小于阈值的碎屑不误触发 ===')
rgb3 = rgb.copy()
cv2.circle(rgb3, (300, 300), 5, (60, 170, 60), -1)
n3 = len(ColorDetector(CFG).detect(rgb3))
check('直径 10px 的碎屑被 min_area_px 滤掉', n3 == len(dets), f'{n3} vs {len(dets)}')

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                   'docs', 'sim_scene.png')
os.makedirs(os.path.dirname(out), exist_ok=True)
vis = rgb.copy()
for d in dets:
    x, y, w, h = d['bbox']
    cv2.rectangle(vis, (x, y), (x+w, y+h), (255, 255, 255), 1)
    p = located[d['label']][0]
    cv2.putText(vis, '%s %.2f,%.2f' % (d['label'], p[0], p[1]), (x, y-5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
cv2.imwrite(out, vis)
print(f'\n合成场景已存到 {os.path.normpath(out)}')

print()
if fails: print(f'✗ {len(fails)} 项失败:', fails); sys.exit(1)
print('✓ 全部通过')
