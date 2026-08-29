import { reactive, readonly } from 'vue'
import ROSLIB from 'roslib'

// 机器人主机：从机器人 8000 打开时取其 IP，本地开发回退
export const ROBOT_HOST =
  location.hostname && !['localhost', '127.0.0.1'].includes(location.hostname)
    ? location.hostname
    : '192.168.3.63'
export const ROSBRIDGE_PORT = 9090
export const VIDEO_PORT = 8080
export const WEBRTC_PORT = 8091
export const BATT_MIN = 9.0, BATT_MAX = 12.6, BATT_WARN = 10.0

// ---- 全局单例状态 ----
const state = reactive({
  connected: false,
  batt: null,            // mV
  imu: null, imuRaw: null, imuSrc: null, odom: null, cmd: null, button: null,
  servos: [], joints: null, scan: null,
  jetson: null, map: null, plan: null, localPlan: null, costmap: null,
  snack: null,           // 零食管家节点状态（/snack_butler/state 的 JSON）
  logs: [],              // 运行日志环形缓冲（systemd journal + /rosout 合并）
  button: null, joy: null, sbus: null, motors: null,   // 扩展板(ros_robot_controller)外设
  units: null,           // Jetson 上的 systemd 服务状态（/system/services）
                         // 注意别叫 services —— 下面 rosapi 自省已经占了这个名字
  counts: { nodes: 0, topics: 0, services: 0 },
  nodes: [], services: [], topics: [], // topics: [[name,type],...]
})

let ros = null
const subs = {}
const pubs = {}
let started = false

function topic(name, messageType) {
  if (!pubs[name]) pubs[name] = new ROSLIB.Topic({ ros, name, messageType })
  return pubs[name]
}
function sub(name, messageType, cb, throttle_rate = 0) {
  const t = new ROSLIB.Topic({ ros, name, messageType, throttle_rate })
  t.subscribe(cb); subs[name] = t; return t
}
function callSvc(service, args, cb) {
  new ROSLIB.Service({ ros, name: service, serviceType: 'rosapi/' + service.split('/').pop() })
    .callService(new ROSLIB.ServiceRequest(args || {}), cb, () => {})
}

function subscribeAll() {
  sub('/ros_robot_controller/battery', 'std_msgs/msg/UInt16', m => { state.batt = m.data }, 500)
  // /ros_robot_controller/imu_raw 的四元数真机实测全是 0（驱动不做姿态解算），
  // 只有 /imu 有融合后的姿态。imu_raw 仅作兜底。
  sub('/imu', 'sensor_msgs/msg/Imu', m => { state.imu = m; state.imuSrc = '/imu' }, 100)
  sub('/ros_robot_controller/imu_raw', 'sensor_msgs/msg/Imu', m => {
    state.imuRaw = m
    if (!state.imu) { state.imu = m; state.imuSrc = '/ros_robot_controller/imu_raw' }
  }, 100)
  sub('/odom', 'nav_msgs/msg/Odometry', m => { state.odom = m }, 120)
  sub('/cmd_vel', 'geometry_msgs/msg/Twist', m => { state.cmd = m }, 150)
  // ---- 扩展板 ros_robot_controller 的各路外设 ----
  sub('/ros_robot_controller/button', 'ros_robot_controller_msgs/msg/ButtonState',
      m => { state.button = { ...m, at: Date.now() } })
  sub('/ros_robot_controller/joy', 'sensor_msgs/msg/Joy', m => { state.joy = m }, 200)
  sub('/ros_robot_controller/sbus', 'ros_robot_controller_msgs/msg/Sbus', m => { state.sbus = m }, 200)
  sub('/ros_robot_controller/set_motor', 'ros_robot_controller_msgs/msg/MotorsState',
      m => { state.motors = m }, 200)
  sub('/controller_manager/servo_states', 'servo_controller_msgs/msg/ServoStateList', m => { state.servos = m.servo_state || [] }, 300)
  sub('/controller_manager/joint_states', 'sensor_msgs/msg/JointState', m => { state.joints = m }, 200)
  sub('/scan', 'sensor_msgs/msg/LaserScan', m => { state.scan = m }, 200)
  sub('/jetson/stats', 'std_msgs/msg/String', m => { try { state.jetson = JSON.parse(m.data) } catch (e) {} })
  sub('/snack_butler/state', 'std_msgs/msg/String', m => { try { state.snack = JSON.parse(m.data) } catch (e) {} }, 200)

  // ---- 运行日志：两路合并成一条流 ----
  // 常驻订阅（不是打开日志页才订），这样一进页面就有最近的历史，排障时不用干等。
  const LOG_MAX = 800
  const pushLog = e => {
    state.logs.push(e)
    if (state.logs.length > LOG_MAX) state.logs.splice(0, state.logs.length - LOG_MAX)
  }
  sub('/system/services', 'std_msgs/msg/String', m => {
    // 空列表不覆盖上一次的结果，否则卡片会一闪一闪（采集端偶尔 systemctl 超时）
    try { const d = JSON.parse(m.data); if (d.services?.length) state.units = d } catch (e) {}
  })
  sub('/system/log', 'std_msgs/msg/String', m => {
    try { const d = JSON.parse(m.data); pushLog({ ...d, from: 'sys' }) } catch (e) {}
  })
  const ROS_LVL = { 10: 'debug', 20: 'info', 30: 'warn', 40: 'error', 50: 'error' }
  sub('/rosout', 'rcl_interfaces/msg/Log', m => pushLog({
    from: 'ros', lvl: ROS_LVL[m.level] || 'info', src: m.name, msg: m.msg,
    t: new Date((m.stamp?.sec || 0) * 1000).toISOString().replace('T', ' ').slice(0, 19),
  }))
  sub('/map', 'nav_msgs/msg/OccupancyGrid', m => { state.map = m })
  sub('/plan', 'nav_msgs/msg/Path', m => { state.plan = m }, 300)
  sub('/local_plan', 'nav_msgs/msg/Path', m => { state.localPlan = m }, 300)
  sub('/global_costmap/costmap', 'nav_msgs/msg/OccupancyGrid', m => { state.costmap = m })
  refreshIntrospection()
  if (!refreshTimer) refreshTimer = setInterval(() => { if (state.connected) refreshIntrospection() }, 8000)
}
let refreshTimer = null
function refreshIntrospection() {
  callSvc('/rosapi/nodes', {}, r => { state.nodes = (r.nodes || []).sort(); state.counts.nodes = state.nodes.length })
  callSvc('/rosapi/services', {}, r => { state.services = (r.services || []).sort(); state.counts.services = state.services.length })
  callSvc('/rosapi/topics', {}, r => {
    const names = r.topics || [], types = r.types || []
    state.topics = names.map((n, i) => [n, types[i] || '']).sort((a, b) => (a[0] < b[0] ? -1 : 1))
    state.counts.topics = names.length
  })
}

function connect() {
  ros = new ROSLIB.Ros({ url: `ws://${ROBOT_HOST}:${ROSBRIDGE_PORT}` })
  ros.on('connection', () => { state.connected = true; subscribeAll() })
  ros.on('error', () => { state.connected = false })
  ros.on('close', () => { state.connected = false; setTimeout(connect, 2000) })
}

// ---- 发布/控制方法 ----
const actions = {
  cmdVel(vx, vy, wz) {
    if (!state.connected) return
    topic('/cmd_vel', 'geometry_msgs/msg/Twist').publish(new ROSLIB.Message({
      linear: { x: vx, y: vy, z: 0 }, angular: { x: 0, y: 0, z: wz } }))
  },
  setServos(position, duration = 1.0) {
    if (!state.connected) return
    topic('/ros_robot_controller/bus_servo/set_position', 'ros_robot_controller_msgs/msg/ServosPosition')
      .publish(new ROSLIB.Message({ duration, position }))
  },
  buzzer(freq, on_time, off_time, repeat) {
    if (!state.connected) return
    topic('/ros_robot_controller/set_buzzer', 'ros_robot_controller_msgs/msg/BuzzerState')
      .publish(new ROSLIB.Message({ freq, on_time, off_time, repeat }))
  },
  oled(index, text) {
    if (!state.connected) return
    topic('/ros_robot_controller/set_oled', 'ros_robot_controller_msgs/msg/OLEDState')
      .publish(new ROSLIB.Message({ index, text: String(text) }))
  },
  led(id, on_time, off_time, repeat) {
    if (!state.connected) return
    topic('/ros_robot_controller/set_led', 'ros_robot_controller_msgs/msg/LedState')
      .publish(new ROSLIB.Message({ id, on_time, off_time, repeat }))
  },
  goalPose(x, y, yaw = 0) {
    if (!state.connected) return
    const qz = Math.sin(yaw / 2), qw = Math.cos(yaw / 2)
    topic('/goal_pose', 'geometry_msgs/msg/PoseStamped').publish(new ROSLIB.Message({
      header: { frame_id: 'map' }, pose: { position: { x, y, z: 0 }, orientation: { x: 0, y: 0, z: qz, w: qw } } }))
  },
  initialPose(x, y, yaw = 0) {
    if (!state.connected) return
    const qz = Math.sin(yaw / 2), qw = Math.cos(yaw / 2)
    const cov = new Array(36).fill(0); cov[0] = 0.25; cov[7] = 0.25; cov[35] = 0.0685
    topic('/initialpose', 'geometry_msgs/msg/PoseWithCovarianceStamped').publish(new ROSLIB.Message({
      header: { frame_id: 'map' },
      pose: { pose: { position: { x, y, z: 0 }, orientation: { x: 0, y: 0, z: qz, w: qw } }, covariance: cov } }))
  },
  // 零食管家：命令走 /snack_butler/cmd (std_msgs/String, JSON)
  snackCmd(obj) {
    if (!state.connected) return false
    topic('/snack_butler/cmd', 'std_msgs/msg/String').publish(new ROSLIB.Message({ data: JSON.stringify(obj) }))
    return true
  },
  navCancel() {
    if (!state.connected) return
    // 取消所有导航目标（Nav2 BT navigator）
    new ROSLIB.Service({ ros, name: '/navigate_to_pose/_action/cancel_goal', serviceType: 'action_msgs/srv/CancelGoal' })
      .callService(new ROSLIB.ServiceRequest({ goal_info: { goal_id: { uuid: [] }, stamp: { sec: 0, nanosec: 0 } } }), () => {}, () => {})
  },
  // 临时订阅一次（读取姿态等）
  once(name, messageType, cb, timeout = 2500) {
    const t = new ROSLIB.Topic({ ros, name, messageType })
    let done = false
    t.subscribe(m => { if (!done) { done = true; cb(m); try { t.unsubscribe() } catch (e) {} } })
    setTimeout(() => { if (!done) { try { t.unsubscribe() } catch (e) {} } }, timeout)
  },
  // 通用订阅（话题浏览器用），返回取消函数
  subscribe(name, messageType, cb, throttle_rate = 100) {
    const t = new ROSLIB.Topic({ ros, name, messageType, throttle_rate })
    t.subscribe(cb)
    return () => { try { t.unsubscribe() } catch (e) {} }
  },
}

export function useRos() {
  if (!started) { started = true; connect() }
  return { state: readonly(state), rawState: state, actions,
    HOST: ROBOT_HOST, VIDEO_PORT, WEBRTC_PORT, BATT_MIN, BATT_MAX, BATT_WARN }
}

// 工具
// IMU 是倒装的：URDF 里 imu_joint 的 origin 是 rpy(pi, 0, -pi/2)，
// 所以 /imu 报的是 imu_link 的姿态，直接显示会看到 roll≈178°。
// 右乘安装四元数的共轭换算到 base_link —— 真机实测 178.58° → -0.18°，机器平放，对得上。
const Q_MOUNT_CONJ = { x: -Math.SQRT1_2, y: Math.SQRT1_2, z: 0, w: 0 }
function qmul(a, b) {
  return {
    x: a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
    y: a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
    z: a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
    w: a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
  }
}
// 四元数是不是有效（全零 = 驱动没做解算）
export function hasOrientation(q) {
  return !!q && (Math.abs(q.x) + Math.abs(q.y) + Math.abs(q.z) + Math.abs(q.w)) > 1e-6
}
// IMU 消息 -> base_link 系的欧拉角；无解算返回 null
export function imuEuler(msg) {
  if (!msg || !hasOrientation(msg.orientation)) return null
  return quatToEuler(qmul(msg.orientation, Q_MOUNT_CONJ))
}

export function quatToEuler(q) {
  const { x, y, z, w } = q
  const roll = Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
  const sp = 2 * (w * y - z * x)
  const pitch = Math.abs(sp) >= 1 ? Math.sign(sp) * Math.PI / 2 : Math.asin(sp)
  const yaw = Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
  return { roll, pitch, yaw }
}
export const deg = r => r * 180 / Math.PI
// web_video_server 不认 %2F —— topic 里的斜杠必须原样传，
// 否则请求直接挂住，<img> 只剩黑框。其余字符仍要转义。
export const videoUrl = (host, port, topic, t) =>
  `http://${host}:${port}/stream?topic=${encodeURIComponent(topic).replace(/%2F/g, '/')}&type=mjpeg&t=${t}`

export function battPct(mv) {
  if (mv == null) return null
  const v = mv / 1000
  return Math.max(0, Math.min(100, Math.round((v - BATT_MIN) / (BATT_MAX - BATT_MIN) * 100)))
}
