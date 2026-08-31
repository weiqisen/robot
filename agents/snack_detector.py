#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
零食识别与定位。单独一个模块、不依赖 rclpy —— 这样 Mac 上能拿合成场景
把「识别 -> 像素 -> base_link 坐标」整条链路离线跑通（见 test_pipeline.py）。
"""
import os
import sys
import threading
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


class UniversalDetector:
    """YOLOv5 通用物体检测 + HSV 小物体兜底。

    真机自带 YOLOv5 和 COCO 权重，不额外联网下载。YOLO 负责常见语义类别，HSV
    继续覆盖没有 COCO 类别的彩色零食；两者重叠时保留 YOLO 的语义框。
    """
    def __init__(self, cfg):
        self.cfg = cfg
        self.color = ColorDetector(cfg)
        self.model = None
        self.torch = None
        self.yolo_error = ''
        self.device = 'not-loaded'
        self.yolo_loading = False
        self._load_lock = threading.Lock()

    @staticmethod
    def _iou(a, b):
        ax, ay, aw, ah = a['bbox']; bx, by, bw, bh = b['bbox']
        x1, y1 = max(ax, bx), max(ay, by)
        x2, y2 = min(ax+aw, bx+bw), min(ay+ah, by+bh)
        inter = max(0, x2-x1) * max(0, y2-y1)
        union = aw*ah + bw*bh - inter
        return inter / max(1, union)

    def _load_yolo(self):
        if self.model is not None or self.yolo_error or self.yolo_loading:
            return
        with self._load_lock:
            if self.model is not None or self.yolo_error:
                return
            self.yolo_loading = True
            try:
                root = self.cfg.get('yolo_root', '/home/ubuntu/third_party_ros2/yolov5')
                weights = self.cfg.get('yolo_weights', os.path.join(root, 'yolov5s.pt'))
                if root not in sys.path:
                    sys.path.insert(0, root)
                import torch
                from models.common import DetectMultiBackend
                from utils.torch_utils import select_device
                device = select_device('0' if torch.cuda.is_available() else 'cpu')
                # 先在局部变量里完整构造并 warmup，最后一次性发布。否则后台预加载与
                # 识别线程并发时会看到 model 非空、torch 仍为空的“半初始化”状态。
                model = DetectMultiBackend(weights, device=device, fp16=torch.cuda.is_available())
                model.warmup(imgsz=(1, 3, int(self.cfg.get('yolo_size', 640)),
                                    int(self.cfg.get('yolo_size', 640))))
                self.torch = torch
                self.model = model
                self.device = str(device)
            except Exception as e:
                self.yolo_error = '%s: %s' % (type(e).__name__, e)
                self.model = None
            finally:
                self.yolo_loading = False

    def preload(self):
        if self.cfg.get('detector_mode', 'hybrid') in ('hybrid', 'yolo'):
            self._load_yolo()

    def _detect_yolo(self, bgr):
        self._load_yolo()
        if self.model is None:
            return []
        from utils.augmentations import letterbox
        from utils.general import non_max_suppression, scale_boxes
        size = int(self.cfg.get('yolo_size', 640))
        img = letterbox(bgr, size, stride=self.model.stride, auto=True)[0]
        img = img.transpose((2, 0, 1))[::-1]
        img = np.ascontiguousarray(img)
        t = self.torch.from_numpy(img).to(self.model.device)
        t = t.half() if self.model.fp16 else t.float()
        t /= 255.0
        if t.ndim == 3:
            t = t[None]
        pred = self.model(t, augment=False, visualize=False)
        pred = non_max_suppression(pred, float(self.cfg.get('yolo_conf', .35)),
                                   float(self.cfg.get('yolo_iou', .45)), max_det=40)
        out = []
        names = self.model.names
        for det in pred:
            if not len(det):
                continue
            det[:, :4] = scale_boxes(t.shape[2:], det[:, :4], bgr.shape).round()
            for x1, y1, x2, y2, conf, cls in det.tolist():
                x, y = int(x1), int(y1)
                w, h = max(1, int(x2-x1)), max(1, int(y2-y1))
                area = float(w*h)
                if area < self.cfg['min_area_px'] or area > self.cfg['max_area_px']:
                    continue
                label = names[int(cls)] if isinstance(names, (list, tuple, dict)) else str(int(cls))
                # 定位阶段需要轮廓内取深度；框向内缩 10%，减少混入背景桌面。
                ix, iy = x + max(1, w//10), y + max(1, h//10)
                iw, ih = max(2, w - 2*max(1, w//10)), max(2, h - 2*max(1, h//10))
                cnt = np.array([[[ix, iy]], [[ix+iw, iy]], [[ix+iw, iy+ih]], [[ix, iy+ih]]],
                               dtype=np.int32)
                out.append({'label': str(label), 'u': x+w/2.0, 'v': y+h/2.0,
                            'area': area, 'bbox': [x, y, w, h], 'angle_px': 0.0,
                            'fill': 1.0, 'confidence': round(float(conf), 3),
                            'detector': 'yolov5', '_cnt': cnt})
        return out

    def detect(self, bgr):
        self.color.cfg = self.cfg
        mode = self.cfg.get('detector_mode', 'hybrid')
        yolo = self._detect_yolo(bgr) if mode in ('hybrid', 'yolo') else []
        colors = self.color.detect(bgr) if mode in ('hybrid', 'color') else []
        if mode == 'hybrid':
            colors = [c for c in colors if not any(self._iou(c, y) > .45 for y in yolo)]
        out = yolo + colors
        for d in out:
            d.setdefault('detector', 'hsv')
        out.sort(key=lambda d: -d['area'])
        return out

    def status(self):
        return {'mode': self.cfg.get('detector_mode', 'hybrid'),
                'yolo_loaded': self.model is not None, 'yolo_device': self.device,
                'yolo_loading': self.yolo_loading,
                'yolo_error': self.yolo_error,
                'weights': self.cfg.get('yolo_weights',
                                        '/home/ubuntu/third_party_ros2/yolov5/yolov5s.pt')}


def detect_depth_objects(depth_img, rgb_shape, K, T_bo, table_z, cfg):
    """用桌面上方的深度点生成任意物体候选，补足 COCO 未训练过的商品包装。"""
    if depth_img is None or K is None or T_bo is None:
        return []
    h, w = rgb_shape[:2]
    depth = cv2.resize(depth_img, (w, h), interpolation=cv2.INTER_NEAREST)
    d = depth.astype(np.float32) / (1000.0 if depth.dtype == np.uint16 else 1.0)
    fy, fx, cy, cx = float(K[4]), float(K[0]), float(K[5]), float(K[2])
    yy, xx = np.indices((h, w), dtype=np.float32)
    ox = (xx - cx) / fx * d
    oy = (yy - cy) / fy * d
    T = np.asarray(T_bo, dtype=np.float32)
    bx = T[0, 0]*ox + T[0, 1]*oy + T[0, 2]*d + T[0, 3]
    by = T[1, 0]*ox + T[1, 1]*oy + T[1, 2]*d + T[1, 3]
    bz = T[2, 0]*ox + T[2, 1]*oy + T[2, 2]*d + T[2, 3]
    ws = cfg.get('workspace_rel') or {'x': [0.10, 0.32], 'y': [-0.22, 0.22]}
    min_h = float(cfg.get('depth_object_min_h', .012))
    max_h = float(cfg.get('depth_object_max_h', .16))
    valid = ((d > .08) & (d < 1.5) & (bx >= ws['x'][0]) & (bx <= ws['x'][1]) &
             (by >= ws['y'][0]) & (by <= ws['y'][1]) &
             (bz >= table_z + min_h) & (bz <= table_z + max_h))
    mask = (valid.astype(np.uint8) * 255)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    out = []
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        area = cv2.contourArea(c)
        if area < cfg['min_area_px'] or area > cfg['max_area_px']:
            continue
        x, y, ww, hh = cv2.boundingRect(c)
        M = cv2.moments(c)
        if M['m00'] <= 0:
            continue
        (_, _), (rw, rh), ang = cv2.minAreaRect(c)
        if rw < rh: ang += 90.0
        out.append({'label': 'object', 'u': M['m10']/M['m00'], 'v': M['m01']/M['m00'],
                    'area': float(area), 'bbox': [x, y, ww, hh], 'angle_px': float(ang),
                    'fill': float(area/max(1, ww*hh)), 'confidence': 1.0,
                    'detector': 'depth', '_cnt': c})
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
