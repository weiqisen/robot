"""导航安全闸门的纯计算逻辑；无 ROS 依赖，便于离线测试。"""
import math


def twist_nonzero(msg, epsilon=1e-4):
    """判断 Twist 是否包含运动量；用于发现绕过安全闸门的旧控制入口。"""
    values = (msg.linear.x, msg.linear.y, msg.linear.z,
              msg.angular.x, msg.angular.y, msg.angular.z)
    return any(abs(float(v)) > epsilon for v in values)


def sector_min(ranges, angle_min, angle_increment, range_min, range_max, center, half_width):
    vals = []
    for i, d in enumerate(ranges):
        if not math.isfinite(d) or d < max(range_min, 0.05) or d > range_max:
            continue
        a = angle_min + i * angle_increment
        delta = math.atan2(math.sin(a-center), math.cos(a-center))
        if abs(delta) <= half_width:
            vals.append(d)
    return min(vals, default=math.inf)


def safe_velocity(vx, vy, wz, scan, *, max_vx=.12, max_vy=.08, max_wz=.45,
                  stop_distance=.38, slow_distance=.72, turn_stop_distance=.30,
                  scan_forward_angle=0.0):
    clamp = lambda v, limit: max(-limit, min(limit, float(v)))
    vx, vy, wz = clamp(vx, max_vx), clamp(vy, max_vy), clamp(wz, max_wz)
    # 速度方向在 base_link 坐标系；LaserScan 角度在雷达坐标系。部分 JetRover
    # 的 lidar_frame 相对 base_link 绕 Z 旋转 180°，必须加这个静态偏角。
    get_min = lambda center, width: sector_min(
        scan.ranges, scan.angle_min, scan.angle_increment, scan.range_min, scan.range_max,
        center + scan_forward_angle, width)

    speed = math.hypot(vx, vy)
    if speed > .005:
        nearest = get_min(math.atan2(vy, vx), math.radians(38))
        if nearest <= stop_distance:
            vx = vy = 0.0
            wz = clamp(wz, .18)
            return vx, vy, wz, '前进方向近障，平移已急停'
        if nearest < slow_distance:
            scale = max(0.0, (nearest-stop_distance)/(slow_distance-stop_distance))
            vx *= scale; vy *= scale

    if abs(wz) > .01 and get_min(0.0, math.pi) <= turn_stop_distance:
        wz = 0.0
        return vx, vy, wz, '车身附近有障碍，旋转已急停'
    return vx, vy, wz, '速度受安全闸门控制'


def degraded_manual_velocity(vx, vy, wz, *, max_vx=.05, max_vy=.05, max_wz=.20):
    """无雷达人工挪车的硬限速；只负责限幅，授权与死手保护由 guard 执行。"""
    clamp = lambda v, limit: max(-limit, min(limit, float(v)))
    return (clamp(vx, max_vx), clamp(vy, max_vy), clamp(wz, max_wz),
            '无雷达降级驾驶：仅硬限速与指令心跳保护')
