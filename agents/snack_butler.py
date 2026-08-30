#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JetRover「零食管家」——识别零食 -> 算坐标 -> 机械臂抓到指定区域 的最小闭环。

设计取舍（都是为了「能长期稳定跑 Demo」）：
  * 独立脚本，不做成 colcon 包：机器人上 need_compile=False 的环境编译新包很麻烦，
    这里只用已装好的 rclpy + 现成消息类型，和 jetson_agent/webrtc_agent 一样丢进 ~/ 跑 systemd。
  * 闭式 IK（arm_kinematics），不迭代、不会抽风，超出工作空间直接报「够不着」而不是乱动。
  * 相机是 eye-in-hand（挂在 link4），所以**只在固定观察位做识别与定位**，
    一旦开始下探就不再用视觉——手眼耦合下边动边看会自激。
  * 深度无效（黑色包装/反光/太近）时自动退化成「射线 x 已知桌面高度」求交，只用 RGB 也能抓。
  * 舵机脉冲<->弧度的方向和零位不写死，用驱动自己发的 servo_states/joint_states 现场拟合。

命令接口： std_msgs/String JSON 发到 /snack_butler/cmd
    {"action":"observe"}                     回观察位
    {"action":"detect"}                      只识别不抓
    {"action":"pick","label":"red"}          抓某个颜色
    {"action":"pick_at","u":320,"v":240}     抓画面上点的那个（网页点一下）
    {"action":"auto","on":true}              自动循环整理，直到桌面清空
    {"action":"stop"}                        停止（松开当前动作，保持姿态）
    {"action":"gripper","open":true}
    {"action":"calibrate"}                   标定舵机脉冲<->弧度
    {"action":"teach_bin","name":"A"}        把当前末端位置记成投放区
    {"action":"set_config","patch":{...}}    改参数并落盘
状态输出： /snack_butler/state (std_msgs/String, JSON)，标注图 /snack_butler/image_result
"""
import os, sys, json, math, time, threading, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import cv2
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image, CameraInfo, JointState, CompressedImage
from std_msgs.msg import String, UInt16

from arm_kinematics import (ik_best, ik_auto_pitch, fk, fk_wrist, ServoMap, TOOL_LEN,
                            SERVO_IDS, GRIPPER_ID, JOINT_NAMES, clamp)
import vision_geometry as vg
from snack_detector import ColorDetector, COLOR_BGR, locate as locate_3d

# 这些是机器人自带的自定义消息；缺任何一个都没法动，直接报清楚
from ros_robot_controller_msgs.msg import ServosPosition, ServoPosition, BuzzerState
try:
    from servo_controller_msgs.msg import ServoStateList
except Exception:
    ServoStateList = None
# 幻尔自带的 controller_manager 入口。**必须走这条**，原因见 send_arm 的注释。
try:
    from servo_controller_msgs.msg import (ServosPosition as CmServosPosition,
                                           ServoPosition as CmServoPosition)
except Exception:
    CmServosPosition = CmServoPosition = None

def ascii_only(t):
    """cv2.putText 只认 ASCII，中文会画成 '?'——画之前先滤掉"""
    return ''.join(c if 32 <= ord(c) < 127 else '' for c in (t or '')).strip()


CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'snack_butler_config.json')

DEFAULT_CONFIG = {
    # --- 姿态 ---
    # 观察位：搜索目标 = 「机械臂够得到 ∧ 相机看得见 ∧ 没被自己底盘挡住」的地面点最多。
    # 早先那版只算视场覆盖、没算自身遮挡，所以号称全覆盖，实际近处一大片被底盘挡着。
    # 加上遮挡重搜后：旧位 134/190，这个 170/190；可见地面 x 0.18~0.30 → 0.16~0.34。
    # 相机抬高到 base_link 上方 0.24（离地 0.36），越高越能越过自己的车身看近处。
    # **改了这个必须重做地面标定**（cam_fix 是在观察位上拟合的，换姿态就不成立了）。
    "observe_deg": [0.0, 27.0, 30.0, 115.0, 0.0],
    "home_deg": [0.0, -60.0, 90.0, 60.0, 0.0],

    # --- 桌面与抓取 ---
    # base_link 在 base_footprint（轮子接地面）上方 0.11609 m，所以机器人自己所站的
    # 那个台面在 base_link 系里是 **-0.116**，不是 0。这个填错是抓不到的头号原因。
    "table_z": -0.116,
    "assume_object_h": 0.028,  # 深度失效时假设的零食高度（只影响兜底路径的精度）
    # URDF 的 end_effector_link 落在手指根部，真实指尖还要往外 0.0368 m。
    # 所有 IK/FK 都按「指尖」算，少了这一截就是竖直扎地 37 mm + 斜抓横偏（见 arm_kinematics.TOOL_LEN）。
    "tool_len": TOOL_LEN,
    "grasp_z_offset": -0.015,  # 从视觉得到的「物体顶面」往下探这么多再合爪
    "grasp_clearance": 0.005,  # 合爪点最低离桌面这么高，防止怼到桌子
    "approach_h": 0.07,        # 预抓取悬停在目标上方多高
    "lift_h": 0.10,            # 抓起来先抬到多高再搬运

    # --- 工作区裁剪：投影落在这个盒子外的检测结果直接丢掉（挡住误检最有效的一招）---
    # 相对桌面来写：[下界, 上界] 都是「离 table_z 多高」，换桌子高度不用重调
    # x 下界不能小于底盘前沿(≈0.17)——比这更近就是车身底下，既放不了东西也看不见。
    # 上界按新观察位能看到的范围放宽。
    "workspace_rel": {"x": [0.17, 0.32], "y": [-0.20, 0.20], "z": [-0.03, 0.12]},

    # --- 夹爪 ---
    "gripper_open": 200,
    "gripper_close": 620,
    "gripper_time": 0.6,

    # --- 投放区（base_link 坐标）---
    "bins": {
        "A": {"xyz": [0.20, 0.155, -0.03], "label": "零食筐 A"},
        "B": {"xyz": [0.20, -0.155, -0.03], "label": "零食筐 B"}
    },
    "route": {"red": "A", "yellow": "A", "orange": "A", "green": "B", "blue": "B", "purple": "B"},
    "default_bin": "A",

    # --- 识别（HSV）---
    "min_area_px": 400,
    "max_area_px": 60000,
    "colors": {
        "red":    [[[0, 110, 80], [8, 255, 255]], [[170, 110, 80], [180, 255, 255]]],
        "orange": [[[9, 130, 90], [22, 255, 255]]],
        "yellow": [[[23, 110, 90], [35, 255, 255]]],
        "green":  [[[36, 80, 60], [85, 255, 255]]],
        "blue":   [[[86, 90, 60], [125, 255, 255]]],
        "purple": [[[126, 70, 60], [160, 255, 255]]]
    },
    "enabled_colors": ["red", "orange", "green", "blue", "yellow"],
    # 观察位下相机会看到自己的底盘（绿色顶板 + 麦轮），HSV 一抓一个准。
    # 它在 base_link 里位置固定，跟臂怎么动无关，所以直接用 base_link 盒子排除。
    # 地面上的零食 z≈-0.09（桌面 -0.116 + 物高），底盘顶板 z≈0，不会误伤。
    "self_body_boxes": [[0.05, 0.21, -0.17, 0.17, -0.045, 0.08]],

    # 点画面抓：光标离已识别目标超过这么多像素，就不吸附了，直接抓你点的那个位置
    "pick_radius_px": 70,
    "click_box_px": 44,        # 直接抓点击处时，取这么大的方块做深度中位数

    # --- 运动 ---
    "move_time": 1.2,
    "settle": 0.35,
    "detect_frames": 5,        # 观察位上取几帧做中值，抗噪
    # 真机 rosbridge 实测（脉冲 vs 驱动发的 joint_states 弧度）拟合出来的初值：
    #   joint2 (765, -1.110) joint3 (15, +2.032) joint4 (150, +1.466) → k 全是 -238.7
    #   与 URDF 推的 PULSE_PER_RAD=238.732 吻合到 1.0000 / 0.9998 / 1.0001
    #   joint1 / joint5 当时都在零位，方向测不出来 —— 仍需跑一次 calibrate
    "servo_map": {"dirs": [1, -1, -1, -1, 1], "centers": [500, 500, 500, 500, 500]},
    "servo_map_calibrated": False,
    "require_calibration": True,   # 未标定就不许下探抓取——方向反了会直接把臂怼到桌上
    # 真机上 /depth_cam/rgb/camera_info 的 frame_id 是 depth_cam_color_optical_frame，
    # 不是 URDF 里那个 depth_cam_frame —— 写错的话 tf 查不到，会悄悄退回静态外参
    # 地面标定修正：把实测地面摆平到 table_z 的 4x4（见 calib_floor）。
    # 需要它是因为 joint_states 是开环回显（驱动不读总线），真实关节角有零位/下垂误差，
    # 相机位姿因此会带几度俯仰和几厘米高度偏差——实测地面被算高了 3 cm 且远近还差 1.5 cm。
    "cam_fix": None,
    # --- 低压保护 ---
    # 断电时机械臂会直接砸下来，所以要在电池真正撑不住之前主动收臂。
    # 舵机/电机一动电压就瞬间塌（实测能掉 0.5 V 以上），所以必须"连续 N 次低于阈值"
    # 才动作，否则一抓东西就误触发。恢复用更高的阈值做迟滞，免得在阈值附近反复横跳。
    "low_volt_enabled": True,
    "low_volt_park": 10.6,     # V，连续低于它就收臂并禁止抓取
    "low_volt_clear": 11.0,    # V，回到它以上才解除
    "low_volt_hold": 5,        # 连续多少个采样（电池约 1 Hz）才算数
    # 视觉管线固定在这个宽度上工作，与相机实际分辨率解耦。
    # 相机开到 1080p 是为了让人在网页上看清楚；HSV 检测/反投影完全不需要那么多像素，
    # 在 1080p 上跑一遍 CPU 直接飙到 117%，而所有像素阈值和标定都是按 640 调的。
    # 降采样后 K 会按同样比例缩放，所以 3D 坐标不受影响。
    "proc_width": 640,
    # 解码限速：相机 12~15 fps，但识别只在"到观察位之后拍几帧"时用，
    # 标注图也只发 5 Hz。每来一帧就解一次纯属白烧 CPU。
    "proc_fps": 6,
    "camera_frame": "depth_cam_color_optical_frame",
    "base_frame": "base_link",
    "use_tf": True,
    "dry_run": False           # True = 只算不发舵机指令，用来空跑验证
}

def deep_update(base, patch):
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v
    return base


# =====================================================================
#  主节点
# =====================================================================
class SnackButler(Node):
    def __init__(self):
        super().__init__('snack_butler')
        self.cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        self.load_config()
        self.smap = ServoMap(**{k: self.cfg['servo_map'][k] for k in ('dirs', 'centers')})
        self.detector = ColorDetector(self.cfg)

        self.lock = threading.Lock()
        self.rgb = None
        self.depth = None
        self.K = None
        self.servo_pulses = {}
        self.joint_rad = {}
        self.q_cmd = [math.radians(a) for a in self.cfg['observe_deg']]   # 我们下发的最新关节角

        self.state = 'INIT'
        self.step = ''
        self.last_error = ''
        self.detections = []
        self.target = None
        self.auto = False
        self.stats = {'picked': 0, 'failed': 0, 'started': time.time()}
        self.calib_samples = []
        self.cam_w = 0              # 相机原始宽度（用来算降采样比例）
        self._last_dec = 0.0        # 上次解码时刻，用于限速
        self.batt_v = None          # 最近一次电池电压（V）
        self._low_n = 0             # 连续低压计数
        self.low_volt = False       # 已触发低压保护（latch，回到 clear 阈值才解除）

        self._task = None
        self._wait_until = 0.0

        sensor_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                                history=HistoryPolicy.KEEP_LAST)
        # 订压缩流而不是原始流：相机开到 1080p 后，原始图每帧 6.2 MB，12 fps 就是 75 MB/s，
        # 光是 DDS 传输 + rclpy 反序列化就能把一个核吃满，而我们只需要 640 宽。
        # 压缩流每帧一两百 KB，而且 cv2.imdecode 支持 IMREAD_REDUCED_*，
        # 直接在 JPEG 的 DCT 阶段降采样解出小图，比「整解再 resize」便宜得多。
        self.create_subscription(CompressedImage, '/depth_cam/rgb/image_raw/compressed',
                                 self.on_rgb_compressed, sensor_qos)
        self.create_subscription(Image, '/depth_cam/depth/image_raw', self.on_depth, sensor_qos)
        self.create_subscription(CameraInfo, '/depth_cam/rgb/camera_info', self.on_info, sensor_qos)
        self.create_subscription(JointState, '/controller_manager/joint_states', self.on_joints, 10)
        if ServoStateList:
            self.create_subscription(ServoStateList, '/controller_manager/servo_states',
                                     self.on_servos, 10)
        self.create_subscription(String, '/snack_butler/cmd', self.on_cmd, 10)
        self.create_subscription(UInt16, '/ros_robot_controller/battery', self.on_batt, 10)

        self.pub_servo = self.create_publisher(
            ServosPosition, '/ros_robot_controller/bus_servo/set_position', 10)
        # 优先走 /servo_controller（幻尔 controller_manager 的入口）
        self.pub_cm = (self.create_publisher(CmServosPosition, '/servo_controller', 10)
                       if CmServosPosition is not None else None)
        if self.pub_cm is None:
            self.get_logger().warn('没有 servo_controller_msgs，退回直发总线；'
                                   'joint_states 将不会跟随，视觉定位会不准')
        self.pub_state = self.create_publisher(String, '/snack_butler/state', 10)
        self.pub_img = self.create_publisher(Image, '/snack_butler/image_result', 1)
        self.pub_buzz = self.create_publisher(BuzzerState, '/ros_robot_controller/set_buzzer', 1)

        # tf2 可选：有就用官方 tf（最准），没有就用 URDF 静态链自己算
        self.tfbuf = None
        if self.cfg['use_tf']:
            try:
                import tf2_ros
                self.tfbuf = tf2_ros.Buffer()
                self.tflistener = tf2_ros.TransformListener(self.tfbuf, self)
            except Exception as e:
                self.get_logger().warn(f'tf2 不可用，改用 URDF 静态外参: {e}')

        self._tx = []
        self.create_timer(0.05, self._tx_drain)     # 下发队列 20Hz，见 _tx_push
        self.create_timer(0.05, self.tick)          # 状态机 20Hz
        self.create_timer(0.2, self.publish_state)  # 状态播报 5Hz
        self.create_timer(0.2, self.publish_image)  # 标注图 5Hz
        self.get_logger().info('零食管家已启动。发 /snack_butler/cmd 开工。')
        self.start(self.seq_goto_observe())

    # ---------------- 配置 ----------------
    def load_config(self):
        try:
            if os.path.exists(CONFIG_PATH):
                deep_update(self.cfg, json.load(open(CONFIG_PATH)))
        except Exception as e:
            print('配置读取失败，用默认值:', e)

    def save_config(self):
        try:
            self.cfg['servo_map'] = self.smap.as_dict()
            tmp = CONFIG_PATH + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(self.cfg, f, indent=2, ensure_ascii=False)
            os.replace(tmp, CONFIG_PATH)
        except Exception as e:
            self.get_logger().error(f'配置保存失败: {e}')

    # ---------------- 订阅回调 ----------------
    def on_rgb_compressed(self, msg):
        # 限速：超过 proc_fps 的帧直接丢，连解码都不做。
        # 这是这个节点最省 CPU 的一刀 —— JPEG 解码本身比后面的 HSV 贵得多。
        now = time.time()
        fps = float(self.cfg.get('proc_fps') or 0)
        if fps > 0 and now - self._last_dec < 1.0 / fps:
            return
        self._last_dec = now
        try:
            buf = np.frombuffer(msg.data, dtype=np.uint8)
            pw = int(self.cfg.get('proc_width') or 640)
            # 先按相机宽度挑一个 2 的幂做 DCT 降采样，剩下的零头再 resize
            flag = cv2.IMREAD_COLOR
            if self.cam_w >= pw * 8:
                flag = cv2.IMREAD_REDUCED_COLOR_8
            elif self.cam_w >= pw * 4:
                flag = cv2.IMREAD_REDUCED_COLOR_4
            elif self.cam_w >= pw * 2:
                flag = cv2.IMREAD_REDUCED_COLOR_2
            img = cv2.imdecode(buf, flag)
            if img is None:
                return
            img = self.shrink(img)
            with self.lock:
                self.rgb = img
        except Exception:
            pass

    def on_depth(self, msg):
        d = self.imgmsg_to_cv(msg, depth=True)
        if d is not None:
            with self.lock:
                self.depth = d

    def on_info(self, msg):
        """内参要跟着降采样一起缩放，否则反投影会整体错位。
        fx/fy/cx/cy 都是像素单位，等比缩放即可（畸变系数与尺度无关）。"""
        k = list(msg.k)
        w = int(getattr(msg, 'width', 0) or 0)
        pw = int(self.cfg.get('proc_width') or 0)
        if w and pw and w > pw:
            sc = pw / float(w)
            for i in (0, 2, 4, 5):
                k[i] *= sc
        self.K = k
        self.cam_w = w

    def on_batt(self, msg):
        """电池 UInt16 是毫伏。这里只记录，判定放 tick 里做，避免在回调里跑状态机。"""
        try:
            self.batt_v = float(msg.data) / 1000.0
        except Exception:
            return
        c = self.cfg
        if not c.get('low_volt_enabled', True) or self.batt_v <= 0.1:
            return
        if self.low_volt:
            # 迟滞：要回到更高的 clear 阈值才解除，不然会在阈值附近反复横跳
            if self.batt_v >= c['low_volt_clear']:
                self.low_volt = False
                self._low_n = 0
                self.last_error = ''
                self.step = f'电压已回到 {self.batt_v:.2f} V，低压保护解除'
                self.get_logger().info(self.step)
            return
        if self.batt_v < c['low_volt_park']:
            self._low_n += 1
            if self._low_n >= int(c['low_volt_hold']):
                self.trip_low_volt()
        else:
            self._low_n = 0

    def trip_low_volt(self):
        """收臂 + 停自动 + 拒绝新的抓取。夹爪保持原样——万一正夹着东西，松开就是直接摔。"""
        self.low_volt = True
        self.auto = False
        self._task = None
        self.last_error = (f'电池 {self.batt_v:.2f} V 低于 {self.cfg["low_volt_park"]} V：'
                           f'已收臂并停止抓取。断电时机械臂会砸下来，请尽快充电。')
        self.get_logger().warn(self.last_error)
        self.beep(400)
        self.start(self.seq_home())

    def on_joints(self, msg):
        for n, p in zip(msg.name, msg.position):
            self.joint_rad[n] = p

    def on_servos(self, msg):
        for s in getattr(msg, 'servo_state', []):
            self.servo_pulses[int(s.id)] = float(s.position)

    def shrink(self, img):
        """把 RGB 降到 proc_width。深度图不动——它本来就是 640，而且插值会毁掉深度值。"""
        pw = int(self.cfg.get('proc_width') or 0)
        if not pw or img is None or img.shape[1] <= pw:
            return img
        h = int(round(img.shape[0] * pw / float(img.shape[1])))
        return cv2.resize(img, (pw, h), interpolation=cv2.INTER_AREA)

    @staticmethod
    def imgmsg_to_cv(msg, depth=False):
        """自己转，避免依赖 cv_bridge 的 ABI"""
        try:
            enc = msg.encoding.lower()
            buf = np.frombuffer(msg.data, dtype=np.uint8)
            if depth:
                if enc in ('16uc1', 'mono16'):
                    return np.frombuffer(msg.data, dtype=np.uint16).reshape(msg.height, msg.width)
                if enc == '32fc1':
                    return np.frombuffer(msg.data, dtype=np.float32).reshape(msg.height, msg.width)
                return None
            if enc == 'bgr8':
                return buf.reshape(msg.height, msg.width, 3)
            if enc == 'rgb8':
                return buf.reshape(msg.height, msg.width, 3)[:, :, ::-1].copy()
            if enc in ('mono8', '8uc1'):
                return cv2.cvtColor(buf.reshape(msg.height, msg.width), cv2.COLOR_GRAY2BGR)
        except Exception:
            pass
        return None

    # ---------------- 运动原语 ----------------
    @staticmethod
    def _pulse(p):
        """ServoPosition.position 是 uint16——传 float 会被 rclpy 断言挡下
        (AssertionError: The 'position' field must be of type 'int')，
        numpy 的整型同样不算 int，所以这里统一 round + 转原生 int + 限幅。"""
        return int(clamp(round(float(p)), 0, 1000))

    def _tx_push(self, msg):
        """/servo_controller 的订阅队列深度只有 1（controller_manager.py 里写死的），
        同一瞬间连发两条（比如「臂到位」+「张爪」）后一条会把前一条直接挤掉，
        表现就是夹爪动了、臂没动。所以这里排队，由定时器每 50ms 放一条出去。"""
        self._tx.append(msg)

    def _tx_drain(self):
        if not self._tx:
            return
        msg = self._tx.pop(0)
        pub = self.pub_cm if (self.pub_cm is not None and type(msg) is CmServosPosition) else self.pub_servo
        pub.publish(msg)

    def send_arm(self, q, duration):
        """下发 5 个臂关节（弧度）。返回下发后驱动实际会用的脉冲（仅供显示）。

        **必须发 /servo_controller，不能直接发 /ros_robot_controller/bus_servo/set_position。**
        幻尔的 servo_manager.get_position() 返回的是「它自己最后一次下发的值」，
        根本不读总线（servo_controller.py: ServoState.position 初值 500，只在 set_position 里写）。
        所以绕过它直发总线：臂会动，但 /controller_manager/{servo_states,joint_states} 永远不变 ——
        我们再用这个不动的 joint_states 去算 eye-in-hand 相机位姿，物体 xyz 就全错，
        于是画面里的东西一律「够不着」。走 /servo_controller 还顺带白拿了驱动自己的
        弧度↔脉冲标定（实测 joint5 方向就和我们默认猜的相反），不用再自己标。
        """
        pulses = self.smap.to_pulse(q)
        if not self.cfg['dry_run']:
            if self.pub_cm is not None:
                m = CmServosPosition()
                m.duration = float(duration)
                m.position_unit = 'rad'
                m.position = [CmServoPosition(id=int(i), position=float(v))
                              for i, v in zip(SERVO_IDS, q)]
                self._tx_push(m)
            else:
                m = ServosPosition()
                m.duration = float(duration)
                m.position = [ServoPosition(id=int(i), position=self._pulse(p))
                              for i, p in zip(SERVO_IDS, pulses)]
                self._tx_push(m)
        self.q_cmd = list(q)
        return pulses

    def send_pulses(self, id_pulse, duration):
        """按脉冲下发（夹爪、标定用）。同样优先走 /servo_controller，保证状态跟随。"""
        if self.cfg['dry_run']:
            return
        if self.pub_cm is not None:
            m = CmServosPosition()
            m.duration = float(duration)
            m.position_unit = 'pulse'
            m.position = [CmServoPosition(id=int(i), position=float(self._pulse(p)))
                          for i, p in id_pulse]
            self._tx_push(m)
            return
        m = ServosPosition()
        m.duration = float(duration)
        m.position = [ServoPosition(id=int(i), position=self._pulse(p)) for i, p in id_pulse]
        self._tx_push(m)

    def gripper(self, opened, duration=None):
        d = self.cfg['gripper_time'] if duration is None else duration
        self.send_pulses([(GRIPPER_ID,
                           self.cfg['gripper_open'] if opened else self.cfg['gripper_close'])], d)
        return d + 0.15

    def beep(self, ms=80):
        try:
            b = BuzzerState()
            b.freq = 1900
            b.on_time = ms / 1000.0
            b.off_time = 0.05
            b.repeat = 1
            self.pub_buzz.publish(b)
        except Exception:
            pass

    # ---------------- 视觉定位 ----------------
    def optical_to_base_mat(self, raw=False):
        """优先 tf2（考虑了真实标定与驱动实际发布的坐标系），否则用 URDF 静态链 + 当前关节角。
        raw=True 拿未修正的原始变换（地面标定要用它，否则会在修正上再叠修正）。"""
        T, src = None, 'urdf'
        if self.tfbuf is not None:
            try:
                tr = self.tfbuf.lookup_transform(self.cfg['base_frame'], self.cfg['camera_frame'],
                                                 rclpy.time.Time())
                t, r = tr.transform.translation, tr.transform.rotation
                T, src = vg.tf_to_mat((t.x, t.y, t.z), (r.x, r.y, r.z, r.w)), 'tf2'
            except Exception:
                T = None
        if T is None:
            T = vg.T_base_optical(self.current_q())
        fix = None if raw else self.cfg.get('cam_fix')
        if fix:
            T = vg.mat_mul([list(row) for row in fix], T)
            src += '+fix'
        return T, src

    def current_q(self):
        """当前关节角：优先驱动反馈的 joint_states，没有就用我们下发的目标"""
        q = []
        for i, n in enumerate(JOINT_NAMES):
            v = self.joint_rad.get(n)
            q.append(v if v is not None else self.q_cmd[i])
        return q

    def locate(self, det, T_bo):
        """检测框 -> base_link 坐标。定位算法在 snack_detector.locate（离线可测）。"""
        if not self.K:
            return None, 'no_intrinsics'
        with self.lock:
            rgb = self.rgb
            depth = None if self.depth is None else self.depth
            shape = None if rgb is None else rgb.shape
        if shape is None:
            return None, 'no_rgb'
        p, how = locate_3d(det, depth, shape, self.K, T_bo,
                           self.cfg['table_z'], self.cfg['assume_object_h'])
        # 深度算出来的点掉到桌面以下 = 明显噪声，退回平面法
        if p is not None and how == 'depth' and p[2] < self.cfg['table_z'] - 0.03:
            p, how = locate_3d(det, None, shape, self.K, T_bo,
                               self.cfg['table_z'], self.cfg['assume_object_h'])
            how = 'plane(深度异常)'
        return p, how

    def grasp_z(self, top_z):
        """视觉给的是物体顶面高度；往下探一点合爪，但绝不低于桌面 + 安全余量"""
        return max(top_z + self.cfg['grasp_z_offset'],
                   self.cfg['table_z'] + self.cfg['grasp_clearance'])

    def in_self_body(self, p):
        """落在机器人自己身上（底盘顶板/轮子）的检测结果，见 self_body_boxes"""
        for b in self.cfg.get('self_body_boxes') or []:
            if b[0] <= p[0] <= b[1] and b[2] <= p[1] <= b[3] and b[4] <= p[2] <= b[5]:
                return True
        return False

    def in_workspace(self, p):
        if self.in_self_body(p):
            return False
        ws = self.cfg['workspace_rel']
        dz = p[2] - self.cfg['table_z']
        return (ws['x'][0] <= p[0] <= ws['x'][1] and ws['y'][0] <= p[1] <= ws['y'][1]
                and ws['z'][0] <= dz <= ws['z'][1])

    def scan_once(self):
        """在观察位跑一次识别 + 定位，写入 self.detections"""
        with self.lock:
            rgb = None if self.rgb is None else self.rgb.copy()
        if rgb is None:
            self.last_error = '没收到 RGB 图像'
            self.detections = []
            return []
        T_bo, src = self.optical_to_base_mat()
        dets = self.detector.detect(rgb)
        out = []
        for d in dets:
            p, how = self.locate(d, T_bo)
            d['xyz'] = None if p is None else [round(v, 4) for v in p]
            d['depth_src'] = how
            d['reachable'] = False
            if p is not None and self.in_workspace(p):
                q, pitch = ik_auto_pitch(p[0], p[1], self.grasp_z(p[2]), tool=self.cfg['tool_len'])
                d['reachable'] = q is not None
                d['pitch_deg'] = None if pitch is None else round(math.degrees(pitch), 1)
            d['extrinsic'] = src
            out.append(d)
        self.detections = out
        return out

    # ---------------- 状态机：每个 yield 返回「等待秒数」 ----------------
    def start(self, gen, name=None):
        self._task = gen
        self._wait_until = 0.0
        if name:
            self.state = name

    def tick(self):
        if not rclpy.ok():
            return
        if self._task is None:
            return
        now = time.time()
        if now < self._wait_until:
            return
        try:
            wait = next(self._task)
            self._wait_until = now + float(wait or 0.0)
        except StopIteration:
            self._task = None
            if self.auto:
                self.start(self.seq_auto())
            else:
                self.state = 'IDLE'
                self.step = ''
        except Exception as e:
            self._task = None
            self.state = 'ERROR'
            self.last_error = f'{type(e).__name__}: {e}'
            self.get_logger().error(traceback.format_exc())

    def seq_goto_observe(self):
        self.state = 'OBSERVE'
        self.step = '回观察位'
        q = [math.radians(a) for a in self.cfg['observe_deg']]
        self.send_arm(q, self.cfg['move_time'])
        self.gripper(True)
        yield self.cfg['move_time'] + self.cfg['settle']
        self.step = '就位'

    def seq_home(self):
        self.state = 'HOME'
        self.step = '收臂'
        self.send_arm([math.radians(a) for a in self.cfg['home_deg']], self.cfg['move_time'])
        yield self.cfg['move_time'] + self.cfg['settle']

    def seq_detect(self):
        yield from self.seq_goto_observe()
        self.state = 'DETECT'
        self.step = '识别中'
        best = []
        for _ in range(max(1, self.cfg['detect_frames'])):
            best = self.scan_once()
            yield 0.12
        self.step = f'识别到 {len(best)} 个目标'

    def pick_target(self, label=None, uv=None):
        """从最近一次识别结果里挑一个可抓的目标"""
        cands = [d for d in self.detections if d.get('reachable')]
        if not cands:
            return None
        if uv:
            # 吸附要有半径。以前是「无条件吸到最近的一个」，于是你点空地/点没被识别的
            # 物体（比如橙色没开时的口香糖罐）时，它会跑去抓画面另一头的误检——
            # 表现就是「还没到就夹了」。够不着就交给调用方走 target_from_uv。
            d = min(cands, key=lambda c: (c['u'] - uv[0]) ** 2 + (c['v'] - uv[1]) ** 2)
            r = self.cfg['pick_radius_px']
            return d if (d['u'] - uv[0]) ** 2 + (d['v'] - uv[1]) ** 2 <= r * r else None
        if label:
            cands = [d for d in cands if d['label'] == label]
            if not cands:
                return None
        # 默认挑离机器人最近的（先近后远，手臂更稳）
        return min(cands, key=lambda d: d['xyz'][0] ** 2 + d['xyz'][1] ** 2)

    def target_from_uv(self, u, v):
        """「点哪抓哪」：不依赖颜色识别，直接把点击处那一小块反投影成 3D 点。
        颜色阈值覆盖不到的东西（换个包装、换个光照）也能抓。"""
        with self.lock:
            shape = None if self.rgb is None else self.rgb.shape
        if shape is None:
            return None, '没有 RGB 图像'
        h = max(6, int(self.cfg['click_box_px']) // 2)
        u = int(clamp(u, h, shape[1] - h - 1))
        v = int(clamp(v, h, shape[0] - h - 1))
        cnt = np.array([[[u - h, v - h]], [[u + h, v - h]],
                        [[u + h, v + h]], [[u - h, v + h]]], dtype=np.int32)
        det = {'label': 'click', 'u': float(u), 'v': float(v), '_cnt': cnt,
               'bbox': [u - h, v - h, 2 * h, 2 * h], 'angle_px': 0.0, 'area': float(4 * h * h)}
        T_bo, src = self.optical_to_base_mat()
        p, how = self.locate(det, T_bo)
        if p is None:
            return None, f'点击处反投影失败 (u={u}, v={v})'
        det['xyz'] = [round(x, 4) for x in p]
        det['depth_src'] = how
        det['extrinsic'] = src
        if not self.in_workspace(p):
            return None, (f'点击处 {det["xyz"]} 不在工作区内 '
                          f'(x{self.cfg["workspace_rel"]["x"]} y{self.cfg["workspace_rel"]["y"]} '
                          f'离桌面 z{self.cfg["workspace_rel"]["z"]})')
        q, pitch = ik_auto_pitch(p[0], p[1], self.grasp_z(p[2]), tool=self.cfg['tool_len'])
        if q is None:
            return None, f'点击处 {det["xyz"]} IK 无解'
        det['reachable'] = True
        det['pitch_deg'] = round(math.degrees(pitch), 1)
        return det, ''

    def seq_pick(self, label=None, uv=None):
        yield from self.seq_detect()
        tgt = self.pick_target(label, uv)
        why = ''
        if not tgt and uv:
            tgt, why = self.target_from_uv(uv[0], uv[1])
            if tgt:
                self.detections = self.detections + [tgt]
        if not tgt:
            self.state = 'IDLE'
            self.step = '没有可抓的目标'
            self.last_error = why or f'未找到可抓目标 (label={label}, uv={uv})'
            self.auto = False
            return
        self.target = tgt
        yield from self.seq_grasp(tgt)

    def _blocked_lowvolt(self):
        if self.low_volt:
            self.state = 'IDLE'
            self.step = '低压保护中，拒绝抓取'
            self.auto = False
            return True
        return False

    def _blocked_uncalibrated(self):
        # 走 /servo_controller 时角度是驱动自己换算的，我们的 ServoMap 不参与下发，
        # 也就没有「方向标反把臂怼桌上」这个风险，不用拦。
        if self.pub_cm is not None:
            return False
        if self.cfg['require_calibration'] and not self.cfg['servo_map_calibrated']:
            self.state = 'IDLE'
            self.step = '未标定，拒绝抓取'
            self.last_error = ('舵机脉冲↔弧度还没标定。方向标反了，下探时手臂会直接怼到桌面。'
                               '先发 {"action":"calibrate"}（网页上「自动标定舵机」按钮）。')
            self.auto = False
            return True
        return False

    def seq_grasp(self, tgt):
        if self._blocked_lowvolt() or self._blocked_uncalibrated():
            return
        cfg = self.cfg
        x, y, zs = tgt['xyz']
        gz = self.grasp_z(zs)
        # 腕部自转对齐物体长边：画面右 = base -Y，所以像素角度取负
        roll = clamp(math.radians(-tgt.get('angle_px', 0.0)), -1.5, 1.5)

        tool = cfg['tool_len']
        q_grasp, pitch = ik_auto_pitch(x, y, gz, wrist_roll=roll, tool=tool)
        if q_grasp is None:
            self.state = 'IDLE'
            self.step = '够不着'
            self.last_error = f'IK 无解 ({x:.3f},{y:.3f},{gz:.3f})'
            self.stats['failed'] += 1
            self.auto = False
            return
        q_pre = (ik_best(x, y, gz + cfg['approach_h'], pitch, seed=q_grasp, wrist_roll=roll, tool=tool)
                 or ik_auto_pitch(x, y, gz + cfg['approach_h'], seed=q_grasp,
                                  wrist_roll=roll, tool=tool)[0]
                 or q_grasp)          # 悬停点算不出来就直接从当前位姿下探
        q_lift = (ik_best(x, y, gz + cfg['lift_h'], pitch, seed=q_grasp, wrist_roll=roll, tool=tool)
                  or q_pre)

        self.state = 'GRASP'
        self.step = f"预抓取 ({x:.3f}, {y:.3f}, {gz:.3f}) pitch={math.degrees(pitch):.0f}°"
        self.gripper(True)
        self.send_arm(q_pre, cfg['move_time'])
        yield cfg['move_time'] + cfg['settle']

        self.step = '下探'
        self.send_arm(q_grasp, 0.9)
        yield 0.9 + cfg['settle']

        self.step = '合爪'
        yield self.gripper(False)

        self.step = '抬起'
        self.send_arm(q_lift, 0.9)
        yield 0.9 + 0.2

        binname = cfg['route'].get(tgt['label'], cfg['default_bin'])
        yield from self.seq_place(binname)
        self.stats['picked'] += 1
        self.target = None
        self.beep()

    def seq_place(self, binname):
        cfg = self.cfg
        b = cfg['bins'].get(binname) or list(cfg['bins'].values())[0]
        bx, by, bz = b['xyz']
        self.state = 'PLACE'
        self.step = f'搬运到 {b.get("label", binname)}'
        q_over, pitch = ik_auto_pitch(bx, by, bz + 0.05, tool=cfg['tool_len'])
        q_drop = (ik_best(bx, by, bz, pitch, seed=q_over, tool=cfg['tool_len'])
                  if q_over else None)
        if q_over is None:
            self.last_error = f'投放区 {binname} 够不着，就地放下'
            q_over = q_drop = self.q_cmd
        self.send_arm(q_over, cfg['move_time'])
        yield cfg['move_time'] + cfg['settle']
        if q_drop:
            self.send_arm(q_drop, 0.7)
            yield 0.7 + 0.2
        self.step = '松爪'
        yield self.gripper(True)
        self.send_arm(q_over, 0.7)
        yield 0.8

    def seq_auto(self):
        """自动循环：一直抓到桌面上没有可抓目标为止"""
        yield from self.seq_detect()
        tgt = self.pick_target()
        if not tgt:
            self.auto = False
            self.state = 'IDLE'
            self.step = '桌面已清空 ✓'
            yield from self.seq_goto_observe()
            return
        self.target = tgt
        yield from self.seq_grasp(tgt)

    def seq_calibrate(self):
        """现场拟合 舵机脉冲 <-> 关节弧度。
        我们发脉冲、读驱动自己算出来的 joint_states 弧度，做最小二乘 —— 
        方向装反/零位偏移这类最容易翻车的事就不用靠人肉试了。"""
        self.state = 'CALIB'
        self.calib_samples = []
        base = self.smap.to_pulse([math.radians(a) for a in self.cfg['observe_deg']])
        for k, off in enumerate((-110, 0, 110, -55, 55)):
            self.step = f'标定 {k + 1}/5'
            pulses = [int(clamp(p + off, 60, 940)) for p in base]
            self.send_pulses(list(zip(SERVO_IDS, pulses)), 1.0)
            yield 1.4
            angs = [self.joint_rad.get(n) for n in JOINT_NAMES]
            real = [self.servo_pulses.get(i) for i in SERVO_IDS]
            if all(a is not None for a in angs):
                self.calib_samples.append(
                    ([r if r is not None else p for r, p in zip(real, pulses)], angs))
        done = self.smap.calibrate_from_samples(self.calib_samples)
        if len(done) == 5:
            self.cfg['servo_map_calibrated'] = True
            self.save_config()
            self.step = f'标定完成 dirs={self.smap.dirs} centers={[round(c) for c in self.smap.centers]}'
            self.beep(200)
        else:
            self.last_error = (f'只标定出关节 {done}；确认 joint_states/servo_states 有数据、'
                               f'且机械臂能自由活动')
            self.step = '标定失败'
        yield from self.seq_goto_observe()

    def seq_calib_floor(self):
        """地面标定：在观察位看一眼空地，把实测地面摆平到 table_z。

        修的是「相机位姿有误差」这件事本身——因为 joint_states 是开环回显，
        真实关节角和它对不上，算出来的相机俯仰和高度就都带偏。用一整片地面去拟合，
        比对着单个物体调偏置稳得多，而且远近一起对上（只对一个点会留下斜率）。
        """
        self.state = 'CALIB'
        self.step = '地面标定：回观察位'
        yield from self.seq_goto_observe()
        self.step = '地面标定：拍地面'
        yield 0.6
        with self.lock:
            depth = None if self.depth is None else self.depth.copy()
            shape = None if self.rgb is None else self.rgb.shape
        if depth is None or shape is None or not self.K:
            self.last_error = '地面标定失败：没有深度图/RGB/内参'
            self.step = '地面标定失败'
            return
        T_raw, src = self.optical_to_base_mat(raw=True)
        dh, dw = depth.shape[:2]
        d = depth.astype(np.float32) / (1000.0 if depth.dtype == np.uint16 else 1.0)
        pts = []
        for vv in range(8, dh - 8, 6):
            for uu in range(8, dw - 8, 6):
                dd = float(d[vv, uu])
                if not (0.08 < dd < 1.5):
                    continue
                p = vg.pixel_to_base(uu * shape[1] / float(dw), vv * shape[0] / float(dh),
                                     dd, self.K, None, T_bo=T_raw)
                if self.in_self_body(p):      # 别把自己的顶板当地面
                    continue
                pts.append(p)
        if len(pts) < 200:
            self.last_error = f'地面标定失败：可用地面点只有 {len(pts)} 个，清空机器人前方再试'
            self.step = '地面标定失败'
            return
        # 两轮：先粗拟合，剔掉离平面 >1.5cm 的（物体、噪声），再精拟合
        pl = vg.fit_plane(pts)
        for _ in range(2):
            if pl is None:
                break
            a, b, c = pl
            keep = [p for p in pts if abs(p[2] - (a * p[0] + b * p[1] + c)) <= 0.015]
            if len(keep) < 200:
                break
            pts = keep
            pl = vg.fit_plane(pts)
        if pl is None:
            self.last_error = '地面标定失败：平面拟合退化'
            self.step = '地面标定失败'
            return
        a, b, c = pl
        cam = (T_raw[0][3], T_raw[1][3], T_raw[2][3])
        before = [p[2] for p in pts]
        C = vg.plane_correction(a, b, c, cam, self.cfg['table_z'])
        after = [vg.mat_apply(C, p)[2] - self.cfg['table_z'] for p in pts]
        rms = math.sqrt(sum(v * v for v in after) / len(after))
        self.cfg['cam_fix'] = [list(row) for row in C]
        self.save_config()
        tilt = math.degrees(math.atan(math.hypot(a, b)))
        dzs = sum(before) / len(before) - self.cfg['table_z']
        self.step = (f'地面标定完成：{len(pts)} 点，原地面偏高 {dzs * 1000:.0f} mm、'
                     f'倾斜 {tilt:.1f}°，修正后残差 {rms * 1000:.1f} mm')
        self.get_logger().info(self.step)
        self.beep(200)

    # ---------------- 命令 ----------------
    def on_cmd(self, msg):
        try:
            c = json.loads(msg.data)
        except Exception as e:
            self.last_error = f'命令不是合法 JSON: {e}'
            return
        a = c.get('action')
        self.last_error = ''      # 新命令进来就清掉上一条的报错，别一直挂在界面上
        try:
            if a == 'stop':
                self.auto = False
                self._task = None
                self.state = 'IDLE'
                self.step = '已停止'
            elif a == 'observe':
                self.auto = False
                self.start(self.seq_goto_observe())
            elif a == 'home':
                self.auto = False
                self.start(self.seq_home())
            elif a == 'detect':
                self.auto = False
                self.start(self.seq_detect())
            elif a == 'pick':
                self.auto = False
                self.start(self.seq_pick(label=c.get('label')))
            elif a == 'pick_at':
                self.auto = False
                self.start(self.seq_pick(uv=(float(c['u']), float(c['v']))))
            elif a == 'auto':
                self.auto = bool(c.get('on', True))
                if self.auto:
                    self.start(self.seq_auto())
                else:
                    self.step = '自动模式已关闭'
            elif a == 'gripper':
                self.gripper(bool(c.get('open', True)))
            elif a == 'calibrate':
                self.auto = False
                self.start(self.seq_calibrate())
            elif a == 'teach_bin':
                p = fk(self.current_q(), tool=self.cfg['tool_len'])[:3]
                name = c.get('name', 'A')
                self.cfg['bins'].setdefault(name, {})['xyz'] = [round(v, 4) for v in p]
                self.cfg['bins'][name].setdefault('label', f'零食筐 {name}')
                self.save_config()
                self.step = f'投放区 {name} 已记为 ({p[0]:.3f},{p[1]:.3f},{p[2]:.3f})'
            elif a == 'set_config':
                deep_update(self.cfg, c.get('patch') or {})
                if 'servo_map' in (c.get('patch') or {}):
                    self.smap = ServoMap(**{k: self.cfg['servo_map'][k] for k in ('dirs', 'centers')})
                self.detector.cfg = self.cfg
                self.save_config()
                self.step = '参数已更新'
            elif a == 'calib_floor':
                self.auto = False
                self.start(self.seq_calib_floor())
            elif a == 'clear_cam_fix':
                self.cfg['cam_fix'] = None
                self.save_config()
                self.step = '已清除地面标定'
            elif a == 'probe':
                # 「只算不抓」：把点击处反投影成 base_link 坐标并报出来，臂一动不动。
                # 拿它和卷尺量的真实位置对比，就能把「视觉算错」和「臂走不准」分开。
                tgt, why = self.target_from_uv(float(c['u']), float(c['v']))
                self.target = tgt
                if tgt:
                    x, y, z = tgt['xyz']
                    self.step = (f"探针 ({x:.3f}, {y:.3f}, {z:.3f}) 抓取高度 "
                                 f"{self.grasp_z(z):.3f} pitch={tgt['pitch_deg']}° "
                                 f"来源={tgt['depth_src']}/{tgt['extrinsic']}")
                else:
                    self.step = '探针：算不出来'
                    self.last_error = why
            elif a == 'goto':
                self.auto = False
                q, _ = ik_auto_pitch(float(c['x']), float(c['y']), float(c['z']),
                                     tool=self.cfg['tool_len'])
                if q:
                    self.send_arm(q, self.cfg['move_time'])
                    self.step = f"手动到位 ({c['x']},{c['y']},{c['z']})"
                else:
                    self.last_error = '该点够不着'
            else:
                self.last_error = f'未知命令 {a}'
        except Exception as e:
            self.last_error = f'{a} 执行失败: {type(e).__name__}: {e}'
            self.get_logger().error(traceback.format_exc())

    # ---------------- 输出 ----------------
    def publish_state(self):
        if not rclpy.ok():
            return
        q = self.current_q()
        ee = fk(q, tool=self.cfg['tool_len'])   # 报指尖，和抓取目标同一口径
        m = String()
        m.data = json.dumps({
            'state': self.state, 'step': self.step, 'auto': self.auto,
            'error': self.last_error,
            'target': None if not self.target else
                      {k: v for k, v in self.target.items() if not k.startswith('_')},
            'detections': [{k: v for k, v in d.items() if not k.startswith('_')}
                           for d in self.detections],
            'ee': {'x': round(ee[0], 4), 'y': round(ee[1], 4), 'z': round(ee[2], 4),
                   'pitch_deg': round(math.degrees(ee[3]), 1)},
            'q_deg': [round(math.degrees(v), 1) for v in q],
            'has_rgb': self.rgb is not None, 'has_depth': self.depth is not None,
            'has_K': self.K is not None,
            'calibrated': self.cfg['servo_map_calibrated'],
            # True = 走 /servo_controller，角度由驱动换算，不需要我们自己标定
            'cm': self.pub_cm is not None,
            'cam_fix': self.cfg.get('cam_fix') is not None,
            'batt_v': None if self.batt_v is None else round(self.batt_v, 2),
            'low_volt': self.low_volt,
            'servo_map': self.smap.as_dict(),
            'cfg': {k: self.cfg[k] for k in
                    ('table_z', 'assume_object_h', 'grasp_z_offset', 'tool_len', 'approach_h',
                     'lift_h', 'gripper_open',
                     'gripper_close', 'bins', 'route', 'enabled_colors', 'workspace_rel',
                     'pick_radius_px', 'self_body_boxes',
                     'low_volt_enabled', 'low_volt_park', 'low_volt_clear', 'low_volt_hold',
                     'observe_deg', 'dry_run', 'min_area_px', 'require_calibration')},
            'stats': dict(self.stats, uptime=round(time.time() - self.stats['started'])),
        }, ensure_ascii=False)
        self.pub_state.publish(m)

    def publish_image(self):
        if not rclpy.ok():
            return
        # 没人订阅就别画也别发。标注图是 640x360 BGR，raw 一帧 1.1 MB，5 Hz 就是 5.5 MB/s，
        # 白白占 DDS 带宽和 rosbridge 的序列化时间。web_video_server 只在有人看时才订。
        if self.pub_img.get_subscription_count() == 0:
            return
        with self.lock:
            img = None if self.rgb is None else self.rgb.copy()
        if img is None:
            return
        for d in self.detections:
            x, y, w, h = d['bbox']
            col = COLOR_BGR.get(d['label'], (200, 200, 200))
            ok = d.get('reachable')
            cv2.rectangle(img, (x, y), (x + w, y + h), col, 2 if ok else 1)
            tag = d['label']
            if d.get('xyz'):
                tag += ' %.2f,%.2f,%.2f' % tuple(d['xyz'])
            if not ok:
                tag += ' [FAR]'      # 图上不能画中文，见 ascii_only
            cv2.putText(img, tag, (x, max(14, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        col if ok else (120, 120, 120), 1, cv2.LINE_AA)
            cv2.circle(img, (int(d['u']), int(d['v'])), 4, (255, 255, 255), -1)
        t = self.target
        if t and t.get('bbox'):
            x, y, w, h = t['bbox']
            cv2.rectangle(img, (x - 4, y - 4), (x + w + 4, y + h + 4), (0, 255, 255), 2)
        # OpenCV 的 Hershey 字体没有中文字形，直接画会变成一排 '?'。
        # 图上只画能画的部分：状态用英文，步骤里的非 ASCII 去掉，中文完整版在网页上看。
        hud = f'{self.state} | {ascii_only(self.step)}'.rstrip(' |')
        cv2.rectangle(img, (0, 0), (img.shape[1], 22), (0, 0, 0), -1)
        cv2.putText(img, hud, (6, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 200), 1, cv2.LINE_AA)
        if self.last_error:
            cv2.putText(img, ascii_only(self.last_error)[:70], (6, img.shape[0] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (80, 80, 255), 1, cv2.LINE_AA)
        msg = Image()
        msg.header.frame_id = self.cfg['camera_frame']
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.height, msg.width = img.shape[0], img.shape[1]
        msg.encoding = 'bgr8'
        msg.is_bigendian = 0
        msg.step = img.shape[1] * 3
        msg.data = img.tobytes()
        self.pub_img.publish(msg)


def main():
    rclpy.init()
    node = SnackButler()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        # systemd 停服务发 SIGTERM，spin 可能带着已失效的 context 抛出来；
        # 这不是故障，别让退出码看起来像崩溃
        if 'context is invalid' not in str(e) and 'shutdown' not in str(e).lower():
            raise
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
