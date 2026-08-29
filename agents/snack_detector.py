#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
零食识别与定位。单独一个模块、不依赖 rclpy —— 这样 Mac 上能拿合成场景
把「识别 -> 像素 -> base_link 坐标」整条链路离线跑通（见 test_pipeline.py）。
"""
import numpy as np
import cv2
import vision_geometry as vg

COLOR_BGR = {"red": (60, 60, 230), "orange": (40, 140, 240), "yellow": (60, 220, 235),
             "green": (90, 200, 90), "blue": (230, 150, 60), "purple": (200, 90, 180)}


class ColorDetector:
    def __init__(self, cfg):
        self.cfg = cfg

    def detect(self, bgr):
        cfg = self.cfg
        hsv = cv2.cvtColor(cv2.GaussianBlur(bgr, (5, 5), 0), cv2.COLOR_BGR2HSV)
        out = []
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        for name in cfg['enabled_colors']:
            ranges = cfg['colors'].get(name)
            if not ranges:
                continue
            mask = None
            for lo, hi in ranges:
                m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
                mask = m if mask is None else cv2.bitwise_or(mask, m)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in cnts:
                area = cv2.contourArea(c)
                if area < cfg['min_area_px'] or area > cfg['max_area_px']:
                    continue
                M = cv2.moments(c)
                if M['m00'] <= 0:
                    continue
                u, v = M['m10'] / M['m00'], M['m01'] / M['m00']
                x, y, w, h = cv2.boundingRect(c)
                (_, _), (rw, rh), ang = cv2.minAreaRect(c)   # 长边朝向 -> 夹爪转多少度
                if rw < rh:
                    ang += 90.0
                out.append({'label': name, 'u': float(u), 'v': float(v), 'area': float(area),
                            'bbox': [int(x), int(y), int(w), int(h)],
                            'angle_px': float(ang),
                            'fill': float(area / max(1.0, w * h)),
                            '_cnt': c})
        out.sort(key=lambda d: -d['area'])
        return out


def _mask_pixels(det, shape, max_n=400):
    """检测轮廓内部的像素坐标（下采样到 max_n 个）"""
    m = np.zeros(shape[:2], np.uint8)
    cv2.drawContours(m, [det['_cnt']], -1, 255, -1)
    m = cv2.erode(m, np.ones((5, 5), np.uint8))     # 往里缩一圈，避开边缘混合像素
    ys, xs = np.nonzero(m)
    if xs.size == 0:
        ys, xs = np.array([int(det['v'])]), np.array([int(det['u'])])
    if xs.size > max_n:
        idx = np.linspace(0, xs.size - 1, max_n).astype(int)
        xs, ys = xs[idx], ys[idx]
    return xs, ys


def locate(det, depth_img, rgb_shape, K, T_bo, table_z, assume_object_h=0.028,
           depth_min=0.05, depth_max=2.0, min_valid=12):
    """
    检测结果 -> base_link 坐标 (x, y, z_顶面), 以及用了哪条路径。

    两个关键做法：
      1) **不是**只反投影 2D 质心那一个像素，而是把整个掩膜内的像素各自反投影、取 3D 中位数。
         几何上两者精度相当，但深度图真机上到处是空洞和边缘穿透（黑色包装、反光、
         轮廓外圈打到桌面），单点或小窗口很容易直接读到桌面深度，中位数能扛过去。
      2) 深度失效时退化成射线求交，交的平面是 **桌面 + 假设物体高度**，
         因为我们看到的是物体顶面而不是桌面。交在桌面上会系统性抓偏（合成场景实测 12~33 mm，
         补上物体高度后降到 6 mm 以内）。
    """
    xs, ys = _mask_pixels(det, rgb_shape)
    pts = []
    if depth_img is not None:
        dh, dw = depth_img.shape[:2]
        sx = dw / float(rgb_shape[1])
        sy = dh / float(rgb_shape[0])
        dxs = np.clip((xs * sx).astype(int), 0, dw - 1)
        dys = np.clip((ys * sy).astype(int), 0, dh - 1)
        d = depth_img[dys, dxs].astype(np.float32)
        if depth_img.dtype == np.uint16:
            d = d / 1000.0
        ok = (d > depth_min) & (d < depth_max)
        if ok.sum() >= min_valid:
            # 剔野值必须**对称**：斜视时顶面本身就有几厘米的深度跨度，
            # 只砍远端（早先的写法）会把估计整体拉向近边，最斜的那块能偏 1.4 cm。
            dv = d[ok]
            keep = np.abs(dv - np.median(dv)) <= 0.05
            u_ok, v_ok, d_ok = xs[ok][keep], ys[ok][keep], dv[keep]
            for uu, vv, dd in zip(u_ok, v_ok, d_ok):
                pts.append(vg.pixel_to_base(float(uu), float(vv), float(dd), K, None, T_bo=T_bo))
    if len(pts) >= min_valid:
        a = np.asarray(pts)
        return (float(np.median(a[:, 0])), float(np.median(a[:, 1])),
                float(np.median(a[:, 2]))), 'depth'

    # --- 兜底：射线 x 「桌面 + 假设物体高」平面 ---
    plane = table_z + assume_object_h
    hits = []
    for uu, vv in zip(xs, ys):
        p = vg.pixel_to_base_on_plane(float(uu), float(vv), K, None, plane, T_bo=T_bo)
        if p:
            hits.append(p)
    if not hits:
        return None, 'no_ray_hit'
    a = np.asarray(hits)
    return (float(np.median(a[:, 0])), float(np.median(a[:, 1])), plane), 'plane'
