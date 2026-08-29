#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
像素 + 深度 -> base_link 三维点。纯 math，无依赖，可离线自测。

关键事实（来自 URDF）：JetRover 的 Orbbec 深度相机不是装在车身上，而是
挂在 **link4**（腕部）上，属于 eye-in-hand —— 相机位姿随机械臂一起动。
所以「像素->世界」必须带上当前关节角。

URDF 里的固定链：
    link4 --camera_connect_joint--> camera_connect_link
           rpy(0, 0, -1.5707963)  xyz(-0.0507060, 0, 0.0505385)
    camera_connect_link --depth_cam_joint--> depth_cam_link
           rpy(pi, -pi/2, -pi/2)  xyz(0, 0, 0.014475)
    depth_cam_link --depth_cam_joint_sim--> depth_cam_frame   (光学系: z前 x右 y下)
           rpy(-pi/2, 0, -pi/2)  xyz(0,0,0)

真机上优先用 tf2 查 base_link <- <相机光学系>；这里的静态链是 tf 不可用时的兜底，
也用来离线验证几何是否自洽。
"""
import math
from arm_kinematics import fk_wrist

# ---------- 4x4 齐次变换（行优先的 list of list）----------
def mat_ident():
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]

def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

def mat_apply(m, p):
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3))

def rpy_xyz(roll, pitch, yaw, x=0.0, y=0.0, z=0.0):
    """URDF 的 origin：R = Rz(yaw)·Ry(pitch)·Rx(roll)，再加平移"""
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, x],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, y],
        [-sp,     cp * sr,                cp * cr,                z],
        [0, 0, 0, 1],
    ]

def translate(x, y, z):
    m = mat_ident()
    m[0][3], m[1][3], m[2][3] = x, y, z
    return m


def axis_angle(axis, ang):
    """Rodrigues：绕单位轴 axis 转 ang 弧度的 4x4"""
    n = math.sqrt(sum(c * c for c in axis))
    if n < 1e-12 or abs(ang) < 1e-12:
        return mat_ident()
    x, y, z = (c / n for c in axis)
    c, s, t = math.cos(ang), math.sin(ang), 1.0 - math.cos(ang)
    return [
        [t * x * x + c,     t * x * y - s * z, t * x * z + s * y, 0.0],
        [t * x * y + s * z, t * y * y + c,     t * y * z - s * x, 0.0],
        [t * x * z - s * y, t * y * z + s * x, t * z * z + c,     0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def fit_plane(points):
    """最小二乘 z = a*x + b*y + c，返回 (a, b, c)。点不足或退化返回 None"""
    n = len(points)
    if n < 8:
        return None
    sx = sy = sz = sxx = syy = sxy = sxz = syz = 0.0
    for x, y, z in points:
        sx += x; sy += y; sz += z
        sxx += x * x; syy += y * y; sxy += x * y
        sxz += x * z; syz += y * z
    A = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, float(n)]]
    b = [sxz, syz, sz]
    # 3x3 高斯消元
    M = [A[i][:] + [b[i]] for i in range(3)]
    for i in range(3):
        piv = max(range(i, 3), key=lambda r: abs(M[r][i]))
        if abs(M[piv][i]) < 1e-12:
            return None
        M[i], M[piv] = M[piv], M[i]
        for r in range(3):
            if r == i:
                continue
            f = M[r][i] / M[i][i]
            for cix in range(i, 4):
                M[r][cix] -= f * M[i][cix]
    return tuple(M[i][3] / M[i][i] for i in range(3))


def plane_correction(a, b, c, cam_xyz, target_z):
    """把「实测地面 z = a*x + b*y + c」摆平到 z = target_z 的刚体修正矩阵。

    绕相机自身位置转（装配/零位带来的俯仰滚转误差就是绕相机转的），再补一个竖直平移，
    这样远处近处一起对上，而不是只把某一个点对上。
    """
    nx, ny, nz = -a, -b, 1.0
    ln = math.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / ln, ny / ln, nz / ln
    axis = (ny * 1.0 - nz * 0.0, nz * 0.0 - nx * 1.0, 0.0)   # n x (0,0,1)
    ang = math.acos(max(-1.0, min(1.0, nz)))
    R = axis_angle(axis, ang)
    cx, cy, cz = cam_xyz
    T = mat_mul(mat_mul(translate(cx, cy, cz), R), translate(-cx, -cy, -cz))
    # 旋转后地面在相机正下方的高度
    z_after = mat_apply(T, (cx, cy, a * cx + b * cy + c))[2]
    return mat_mul(translate(0.0, 0.0, target_z - z_after), T)


def rot_z(a): return rpy_xyz(0, 0, a)
def rot_y(a): return rpy_xyz(0, a, 0)

# ---------- 固定链：link4 -> depth_cam_frame ----------
T_LINK4_CONNECT = rpy_xyz(0, 0, -1.57079632679489, -0.0507060266977644, 0.0, 0.0505384841187764)
T_CONNECT_CAMLINK = rpy_xyz(math.pi, -math.pi / 2, -math.pi / 2, 0.0, 0.0, 0.014475)
T_CAMLINK_OPTICAL = rpy_xyz(-math.pi / 2, 0.0, -math.pi / 2, 0.0, 0.0, 0.0)
T_LINK4_OPTICAL = mat_mul(mat_mul(T_LINK4_CONNECT, T_CONNECT_CAMLINK), T_CAMLINK_OPTICAL)


def T_base_link4(q):
    """link4 在 base_link 系的位姿：R = Rz(-q1)·Ry(q2+q3+q4)，原点 = joint4 位置"""
    T = mat_mul(rot_z(-q[0]), rot_y(q[1] + q[2] + q[3]))
    px, py, pz = fk_wrist(q)
    T[0][3], T[1][3], T[2][3] = px, py, pz
    return T


def T_base_optical(q):
    return mat_mul(T_base_link4(q), T_LINK4_OPTICAL)


# ---------- 像素 -> 相机光学系 ----------
def deproject(u, v, depth_m, K):
    """K = [fx,0,cx, 0,fy,cy, 0,0,1]（CameraInfo.k）。光学系: x右 y下 z前"""
    fx, cx, fy, cy = K[0], K[2], K[4], K[5]
    if fx == 0 or fy == 0:
        raise ValueError('bad intrinsics')
    return ((u - cx) * depth_m / fx, (v - cy) * depth_m / fy, float(depth_m))


def project(p, K):
    """光学系点 -> 像素，用于把目标画回图上做闭环校验"""
    fx, cx, fy, cy = K[0], K[2], K[4], K[5]
    if p[2] <= 1e-6:
        return None
    return (fx * p[0] / p[2] + cx, fy * p[1] / p[2] + cy)


def pixel_to_base(u, v, depth_m, K, q, T_bo=None):
    """(像素, 深度, 内参, 当前关节角) -> base_link 系 (x,y,z)"""
    return mat_apply(T_bo if T_bo else T_base_optical(q), deproject(u, v, depth_m, K))


def ray_to_base(u, v, K, q, T_bo=None):
    """返回 (相机光心 in base, 单位方向 in base)。深度失效时用来跟桌面求交。"""
    T = T_bo if T_bo else T_base_optical(q)
    o = (T[0][3], T[1][3], T[2][3])
    d = mat_apply(T, deproject(u, v, 1.0, K))
    vx, vy, vz = d[0] - o[0], d[1] - o[1], d[2] - o[2]
    n = math.sqrt(vx * vx + vy * vy + vz * vz) or 1.0
    return o, (vx / n, vy / n, vz / n)


def ray_plane_z(origin, direction, plane_z):
    """射线与水平面 z=plane_z 求交。深度图打不到（黑色/反光/太近）时的兜底：
    假设零食都放在已知高度的桌面上，只用 RGB 也能算出坐标。"""
    if abs(direction[2]) < 1e-6:
        return None
    t = (plane_z - origin[2]) / direction[2]
    if t <= 0:
        return None
    return (origin[0] + direction[0] * t,
            origin[1] + direction[1] * t,
            plane_z)


def pixel_to_base_on_plane(u, v, K, q, plane_z, T_bo=None):
    o, d = ray_to_base(u, v, K, q, T_bo)
    return ray_plane_z(o, d, plane_z)


# ---------- tf2 的 (trans, quat) -> 4x4，真机上优先走这条 ----------
def tf_to_mat(t, quat):
    x, y, z, w = quat
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w),     2 * (x * z + y * w),     t[0]],
        [2 * (x * y + z * w),     1 - 2 * (x * x + z * z), 2 * (y * z - x * w),     t[1]],
        [2 * (x * z - y * w),     2 * (y * z + x * w),     1 - 2 * (x * x + y * y), t[2]],
        [0, 0, 0, 1],
    ]
