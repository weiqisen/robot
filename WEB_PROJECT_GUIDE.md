# JetRover Web 项目完整入门指南

这份文档面向第一次接触本项目的开发者。读完后，你应该能够回答：网页如何启动、数据从哪里来、
按钮最终控制了谁、主要业务如何闭环、哪些代码涉及安全、增加功能应该改哪里，以及怎样验证和部署。

> 项目不是普通的“网页 + REST 后端 + 数据库”。浏览器会通过 rosbridge 直接订阅和发布 ROS 2
> 话题；机器人上的 Python agents 负责业务状态机、安全控制、系统采集和少量 HTTP 服务。

## 1. 项目解决什么问题

这是运行在 JetRover + Jetson Orin Nano 上的一套机器人工作台，主要能力包括：

- 浏览器查看电池、CPU/GPU、内存、温度、IMU、里程计、雷达、相机和 ROS 状态。
- 键盘、虚拟摇杆或按钮手动驾驶底盘。
- 控制机械臂关节、夹爪、蜂鸣器、OLED 和 LED。
- 查看三维数字孪生、关节姿态、雷达点云、识别物体和计划动作轨迹。
- 使用 RGB-D + YOLO/轮廓检测完成视觉引导抓取、投放和结果复核。
- 使用 Nav2 + Frontier 算法自主探索、避障、返航和故障恢复。
- 查看 systemd/ROS 日志、服务状态、硬件清单和 ROS 图谱。
- 通过远程桌面操作 Jetson 图形界面。
- 通过自然语言代理把用户意图转换成受限机器人命令。

项目的核心原则是：**网页负责交互和展示，机器人端负责真实决策与安全约束。**

## 2. 一张图理解整体架构

```text
用户浏览器
│
├─ HTTP :8000 ───────────── webctl_server.py
│                         ├─ Vue 静态文件
│                         ├─ 动作组/录像/数字孪生配置 API
│                         ├─ 服务重启与视觉链路检查
│                         └─ VNC WebSocket 桥
│
├─ WebSocket :9090 ─────── rosbridge / rosapi
│                         ├─ 订阅遥测、地图、雷达、日志和业务状态
│                         └─ 发布驾驶、机械臂、抓取、探索和安全命令
│
├─ MJPEG :8080 ─────────── web_video_server
├─ WebRTC :8091 ────────── webrtc_agent.py
└─ HTTP :8092 ──────────── llm_agent.py
                              │
                              ▼
                    ROS 2 Humble + Python agents
                    │
                    ├─ 硬件驱动/相机/雷达/Nav2
                    ├─ nav_safety_guard.py
                    ├─ snack_butler.py
                    ├─ explorer_agent.py
                    └─ jetson_agent.py
```

### 三条数据通道

1. **ROS 数据通道**：绝大多数实时数据和控制命令走 `:9090` rosbridge。
2. **视频通道**：大图像不塞进普通页面状态，主要走 `:8080` MJPEG 或 `:8091` WebRTC。
3. **HTTP 辅助通道**：文件、录像、动作组、VNC 和服务管理走 `:8000/api/*`。

## 3. 仓库目录

```text
robot/
├─ studio-vue/                 Vue 3 前端
│  ├─ src/App.vue              页面注册、hash 导航、全局外壳
│  ├─ src/views/               页面级组件
│  ├─ src/components/          可复用 UI 组件
│  ├─ src/composables/         ROS、视频、主题等共享逻辑
│  ├─ src/styles/tokens.css    全局设计变量
│  └─ public/model/            URDF、三维模型和静态资源
├─ agents/                     部署到 Jetson /home/ubuntu 的独立程序
│  ├─ webctl_server.py         网页与辅助 HTTP API
│  ├─ jetson_agent.py          系统、硬件、服务和日志遥测
│  ├─ snack_butler.py          视觉抓取业务状态机
│  ├─ snack_detector.py        YOLO/HSV/深度物体检测
│  ├─ vision_geometry.py       RGB-D 反投影与坐标变换
│  ├─ arm_kinematics.py        机械臂 FK/IK
│  ├─ nav_safety_guard.py      所有底盘速度的安全闸门
│  ├─ explorer_agent.py        自主探索任务调度
│  ├─ llm_agent.py             自然语言到受限命令
│  ├─ webrtc_agent.py          WebRTC 视频桥
│  ├─ web_bringup.launch.py    网页工作台精简 ROS bringup
│  ├─ deploy_snack.sh          正式部署入口
│  └─ test_*.py                离线测试
├─ tools/sim_robot.py          无真机时的本地 ROS 兼容模拟器
├─ docs/                       专题设计与运维文档
├─ README.md                   最短入口
└─ AGENTS.md                   项目事实和修改约束
```

机器人端 agents 是直接由 systemd 启动的脚本，不是 colcon 包。厂商 ROS 驱动仍来自
`/home/ubuntu/ros2_ws` 和 `/home/ubuntu/third_party_ros2`。

## 4. 前端技术与启动过程

### 技术栈

- Vue 3 Composition API 和 `<script setup>`
- Vite 5
- Ant Design Vue 4
- roslib：浏览器连接 rosbridge
- Three.js + URDF Loader：数字孪生
- noVNC：远程桌面
- 原生 Canvas：雷达、地图、姿态和轻量图表

入口是 `studio-vue/src/main.js`，全局外壳是 `studio-vue/src/App.vue`。

### 页面切换为什么没有 vue-router

项目没有安装 vue-router。`App.vue` 的 `MENU` 数组就是页面注册表，URL hash 是页面地址：

```text
http://192.168.3.63:8000/#bigscreen
http://192.168.3.63:8000/#snack
http://192.168.3.63:8000/#control
```

刷新后仍停留在当前页面，也便于保存书签。普通页面挂在后台管理外壳中；`bigscreen` 是无侧栏的专注
工作台。页面使用 `v-show` 保留实例，切换时不会频繁重建 ROS 状态和 Three.js 场景。

### 机器人地址如何决定

统一入口在 `studio-vue/src/composables/useRos.js`：

1. 查询参数 `?robot=IP` 优先。
2. `?sim=1` 使用本机模拟器。
3. 从机器人 `:8000` 打开时，使用当前网页 hostname。
4. 本地 Vite 开发时回退到 `192.168.3.63`。

不要在单个页面里再写一套机器人 IP 判断。

## 5. 前端状态模型

`useRos.js` 是全局单例。第一次调用 `useRos()` 时建立连接，所有页面共享同一份 Vue reactive 状态。

主要状态分组：

| 状态 | 来源 | 用途 |
|---|---|---|
| `connected` | rosbridge 连接事件 | 全局在线状态 |
| `batt` | `/ros_robot_controller/battery` | 电池电压和百分比 |
| `imu`、`imuRaw` | `/imu`、原始 IMU | 姿态与传感器诊断 |
| `odom`、`cmd` | `/odom`、速度话题 | 位姿和运动状态 |
| `servos`、`joints` | 控制器状态话题 | 机械臂回显和孪生姿态 |
| `scan` | `/scan` | 雷达与导航安全 |
| `map`、`plan`、`costmap` | Nav2/SLAM | 地图、路径和代价地图 |
| `jetson` | `/jetson/stats` | CPU/GPU、内存、温度、功耗 |
| `snack` | `/snack_butler/state` | 抓取状态、检测结果和决策轨迹 |
| `explorer` | `/explorer/state` | 探索任务状态 |
| `navSafety` | `/nav_safety/state` | 驱动锁、净空、限速和急停原因 |
| `logs` | `/system/log` + `/rosout` | 合并后的运行日志环形缓冲 |
| `nodes/topics/services` | rosapi | ROS 自省列表 |

连接断开后每 2 秒自动重连。带 `*At` 的时间戳用于判断数据是否新鲜；“有旧对象”不等于“节点在线”。

### 前端 actions

`useRos.js` 的 `actions` 统一封装命令发布：

- `cmdVel()`：发布 `/manual_cmd_vel`，不能直发底盘。
- `setServosCtl()`：通过 `/servo_controller` 控制舵机并保持关节状态同步。
- `snackCmd()`：向抓取状态机发送 JSON。
- `explorerCmd()`：向探索状态机发送 JSON。
- `navSafetyCmd()`：选择控制源、解锁或锁定安全闸门。
- `goalPose()` / `initialPose()`：导航目标与初始位姿。
- `emergencyStop()`：发零速度、锁定闸门并取消 Nav2 目标。
- `once()` / `subscribe()`：页面临时读取通用 ROS 话题。

## 6. 页面地图

### 默认工作台

| 页面 | 文件 | 作用 |
|---|---|---|
| 工作台 | `views/BigScreen.vue` | 默认专注界面；驾驶、机械臂、位置组、健康状态、三维态势和弹层入口 |
| 数字孪生 | `views/Twin.vue` | 被工作台嵌入；加载 URDF/网格并融合关节、雷达、检测物体和动作轨迹 |

### 监控页面

| 页面 | 文件 | 作用 |
|---|---|---|
| 概览 | `Overview.vue` | 电源、姿态、系统健康和趋势摘要 |
| 遥测数据 | `Telemetry.vue` | IMU、里程计、速度指令和按键原始值 |
| 机械臂舵机 | `Arm.vue` | 舵机脉冲、关节角和基础夹爪控制 |
| 传感器 | `Sensors.vue` | 雷达 Canvas 与全部图像话题 |
| Jetson | `Jetson.vue` | CPU/GPU、内存、温度、功耗、CUDA 与系统信息 |
| GPU 压测 | `GpuBench.vue` | 调用 webctl API 运行受控 torch 基准 |
| 扩展板 | `Board.vue` | STM32 电池、IMU、Joy、SBUS、LED、OLED、蜂鸣器 |
| BOM | `Bom.vue` | 机器人硬件与 USB 枚举信息 |

### 感知与导航页面

| 页面 | 文件 | 作用 |
|---|---|---|
| 导航建图 | `NavMap.vue` | 地图、代价地图、雷达、路径、定位和目标点 |
| 自主探索 | `Explore.vue` | 启动检查、任务状态、前方画面、决策日志、返航和恢复 |
| 目标检测 | `Detect.vue` | 自动发现并展示检测/识别类图像话题 |
| 视觉引导抓取 | `Snack.vue` | 目标选择、抓取、投放、标定、参数、录像和决策轨迹 |

### ROS、调试与操作页面

| 页面 | 文件 | 作用 |
|---|---|---|
| 节点·服务 | `SystemView.vue` | ROS 节点与服务列表 |
| 话题总览 | `Topics.vue` | 话题名和消息类型 |
| 话题浏览器 | `Explorer.vue` | 临时订阅任意话题并查看 JSON |
| 运行日志 | `Logs.vue` | systemd + ROS 日志查询、筛选与服务重启 |
| 实时控制 | `Control.vue` | WebRTC/MJPEG、键盘/摇杆驾驶、机械臂和外设 |
| 动作组编辑器 | `ArmStudio.vue` | 编辑和播放厂商 `.d6a` 动作组 |
| 远程桌面 | `Remote.vue` | noVNC 连接 Jetson 桌面 |

## 7. 可复用组件和视觉设计

`src/components/` 放跨页面共享的小组件：仪表环、迷你趋势图、姿态 Canvas、服务面板、速度限制、
CUDA 推理卡等。页面内部独有且强耦合的视图通常保留在页面文件中。

设计变量集中在 `src/styles/tokens.css`：背景、表面层级、文字、边框、强调色、成功/警告/危险色和
等宽字体。深浅主题由 `useTheme.js` 管理。新增样式应优先使用 token，而不是散落固定颜色。

当前交互设计有两种层级：

- **工作台模式**：默认入口，突出驾驶、机械臂、相机和三维态势，次要指标进入顶部弹层。
- **完整总览模式**：后台侧栏提供开发、标定、诊断和运维页面。

响应式边界主要在 992px 和 600px；移动端侧栏变成遮罩抽屉，顶部负载指标会收缩。

## 8. 机器人端服务职责

| systemd 服务 | 代码/来源 | 职责 |
|---|---|---|
| `start_app_node` | `web_bringup.launch.py` | 启动核心控制器、IMU、相机、雷达、rosbridge 和视频服务 |
| `webctl` | `webctl_server.py` | 静态网页与辅助 HTTP API |
| `jetson-agent` | `jetson_agent.py` | Jetson、硬件、日志与服务状态遥测 |
| `snack-butler` | `snack_butler.py` | 视觉抓取和机械臂业务状态机 |
| `nav-safety` | `nav_safety_guard.py` | 底盘速度唯一安全出口 |
| `exploration-nav` | Nav2/SLAM launch | 地图、规划、控制和定位 |
| `explorer-agent` | `explorer_agent.py` | Frontier 任务规划、返航和恢复 |
| `lidar-watchdog` | `lidar_watchdog.py` | 雷达数据中断后的受限恢复 |
| `vision-video` | `vision_stream_server.py` | 独立标注画面桥；当前主路径仍可使用 8080 |
| `webrtc-agent` | `webrtc_agent.py` | 浏览器低延迟视频协商 |
| `llm-agent` | `llm_agent.py` | 自然语言 tool use；有密钥时启用 |
| `x11vnc` | `run_x11vnc.sh` | Jetson 桌面 VNC |

已停掉的厂商演示节点及恢复方法见 `VENDOR_APPS_STATUS.md`。

## 9. HTTP API

`webctl_server.py` 使用 `ThreadingHTTPServer`，同时提供生产静态文件和辅助 API：

| 路径 | 方法 | 用途 |
|---|---|---|
| `/api/vision/health` | GET | 检查视觉链路每一环并给出建议重启项 |
| `/api/services/<name>/restart` | POST | 重启白名单内的项目服务 |
| `/api/actions` | GET | 列出机械臂动作组 |
| `/api/actions/<name>` | GET/POST | 读取或写入 `.d6a` 动作组 |
| `/api/recordings` | GET | 列出抓取录像与回放元数据 |
| `/api/recordings/<file>` | GET | 读取 MP4 或 JSON 回放文件 |
| `/api/look` | GET/POST | 数字孪生外观配置 |
| `/api/twin/view` | GET/POST | 数字孪生默认相机视角 |
| `/api/gpu_bench` | GET | GPU 压测状态 |
| `/api/gpu_bench/start` | POST | 启动受限压测 |
| `/api/gpu_bench/stop` | POST | 停止压测 |
| `/api/camera.jpg` | GET | 相机快照代理 |
| `/api/desktop.jpg` | GET | 桌面快照代理 |
| `/api/vnc` | WebSocket | 到本机 `x11vnc:5900` 的桥 |

这些 API 主要面向受信任局域网，没有设计成公网多租户系统。不要把 `:8000`、`:8092`、`:9090`
直接暴露到互联网。

## 10. 核心业务逻辑

### 10.1 手动驾驶

```text
用户按键/摇杆
  → Control.vue 或 BigScreen.vue 计算 vx/vy/wz
  → /manual_cmd_vel
  → nav_safety_guard 选择 manual 控制源
  → 限速、死手、雷达方向净空、视觉防撞、低压/旧入口检查
  → /controller/cmd_vel
  → 底盘驱动
```

页面按住控制时持续发指令；松开、页面失焦、组件停用或连接断开时发送零速度。手动接管在雷达故障时
可以进入严格限速、限时的降级模式，但不能绕过死手保护。

### 10.2 机械臂控制

网页关节滑块优先发到 `/servo_controller`，驱动换算并同步发布 joint states。数字孪生以真实关节状态
为主，并在用户拖动后的短窗口内显示本地预览，避免旧遥测把模型瞬间拉回去。

视觉抓取的“观察位、行驶位、高位”等安全位置组不直接在前端拼舵机角度，而是给
`snack_butler` 发语义命令，由机器人端状态机执行。

### 10.3 视觉引导抓取

```text
命令 pick / pick_at
  → 回固定观察位
  → 冻结 RGB、深度、内参、关节与相机外参快照
  → 独立 vision worker 执行 YOLO/HSV/深度轮廓
  → 像素和深度反投影到 base_link
  → 工作区过滤 + 垂直夹爪 IK
  → 选目标
  → 安全点 → 预抓 → 下探 → 合爪 → 抬起
  → 回观察位复核原位置
  → 投放或保持 HOLDING
```

YOLO 在当前 Jetson 上使用 CUDA；OpenCV 解码、深度反投影、轮廓、NMS 和 JSON/图像发布仍会使用
CPU。视觉 worker 与 ROS 控制线程分离，推理不能阻塞舵机、安全回调和低压保护。

状态中的 `decision_log` 是事实型决策轨迹；`scene_objects` 是用于三维显示的稳定追踪结果；真实抓取
仍使用当次检测的原始 `detections.xyz`，不能用显示平滑后的坐标替代安全决策。

详细几何、标定、工作区和抓取参数见 `docs/SNACK_BUTLER.md`。

### 10.4 自主探索

```text
用户开始探索
  → explorer_agent 做地图/雷达/Nav2/电池/机械臂/安全闸门检查
  → 收回机械臂并记录 home
  → 从 /map 提取自由区与未知区交界的 Frontier
  → 聚类、过滤、排序并选择短距离目标
  → NavigateToPose action
  → Nav2 输出 /nav_cmd_vel
  → nav_safety_guard
  → /controller/cmd_vel
```

遇到持续安全急停时短暂复核，然后取消当前目标、临时降权并请求 Nav2 做受限脱困；超时、低电压或
探索完成后返航。前向起步净空与原地旋转净空分开判断，侧后近点不会误报成前路堵死。

详细状态、Frontier 算法和恢复机制见 `docs/AUTONOMOUS_EXPLORATION.md`。

### 10.5 数字孪生

`Twin.vue` 是前端最大的页面模块，主要做四件事：

1. 加载 URDF/网格并按关节状态驱动机械臂。
2. 把里程计、雷达和检测物体投射到三维场景。
3. 根据物体类别显示语义模型；未知物体使用深度轮廓拉伸体。
4. 显示抓取计划轨迹、目标标签卡和设备细节模型。

孪生是**态势展示和交互辅助**，不是安全控制器。视觉卡片随相机缩放做屏幕空间补偿，模型外观和默认
视角通过 webctl API 持久化。

### 10.6 自然语言控制

`Snack.vue` 将文本 POST 到 `llm_agent.py :8092/ask`。代理通过明确工具把意图转换成抓取、驾驶、
机械臂、OLED 或蜂鸣器命令。速度和持续时间在机器人端再次限幅；底盘命令仍必须走安全闸门。

API key 只存在机器人 `~/.llm_agent.env`，不能写进前端、仓库或日志。

## 11. 安全边界

以下规则比页面样式和交互便利性优先级更高：

- `/controller/cmd_vel` 是底盘最终入口，Nav2、网页驾驶和抓取补位必须先经过 `nav_safety_guard.py`。
- 不要恢复网页或厂商节点直发 `/cmd_vel` 的旧路径。
- 页面“按钮不可点”不是安全机制；断线、脚本或其他 ROS 节点都可能绕过页面。
- 雷达和视觉判定按运动方向检查；旋转需要检查车身周围净空。
- 手动无雷达降级驾驶必须保持低速、限时和死手。
- 机械臂相机是 eye-in-hand，像素坐标必须结合拍摄时的关节姿态。
- `table_z`、`tool_len`、相机外参和舵机映射是安全关键配置。
- 修改运动学或标定后先跑测试，再开“空跑”，最后才允许真实抓取。
- 中断抓取会写动作日志，服务重启后进入 RECOVERY，不能自动继续危险动作。
- 紧急停止应同时归零速度、锁安全闸门并取消 Nav2 目标。

## 12. 持久化数据

项目没有数据库服务，少量状态直接保存在机器人用户目录：

| 文件 | 内容 | 部署是否覆盖 |
|---|---|---|
| `~/snack_butler_config.json` | 抓取、标定和视觉配置 | 不覆盖 |
| `~/snack_butler_profiles.json` | 抓取参数方案 | 不覆盖 |
| `~/snack_butler_action.json` | 中断动作恢复日志 | 不覆盖 |
| `~/explorer_session.json` | 探索任务恢复状态 | 不覆盖 |
| `~/nav_safety_config.json` | 安全闸门配置 | 不覆盖 |
| `~/twin_look.json` | 孪生外观 | 不覆盖 |
| `~/twin_view.json` | 孪生默认视角 | 不覆盖 |
| `~/recordings/` | 抓取 MP4 和事件 JSON | 不覆盖 |
| `~/software/arm_pc/ActionGroups/*.d6a` | 厂商动作组 | 网页与桌面软件共用 |
| `~/.llm_agent.env` | 密钥和模型环境变量 | 不创建、不覆盖 |

配置写入应使用临时文件 + `os.replace()` 原子替换，避免掉电留下半截 JSON。

## 13. 本地开发

### 只有网页

```bash
cd studio-vue
npm ci
npm run dev
```

打开 `http://localhost:5273`。默认连接真机 `192.168.3.63`；也可以使用：

```text
http://localhost:5273/?robot=192.168.3.99
```

### 没有机器人

根据 `docs/LOCAL_SIMULATOR.md` 启动 `tools/sim_robot.py`，然后访问：

```text
http://localhost:5273/?sim=1
```

模拟器适合测试页面、掉线、状态变化和任务恢复，不代表真实运动安全已经验证。

## 14. 构建、测试和部署

最小验证：

```bash
npm --prefix studio-vue run build
python3 agents/test_kinematics.py
python3 agents/test_vision.py
python3 agents/test_nav_safety.py
python3 agents/test_webctl_bridge.py
```

正式部署：

```bash
./agents/deploy_snack.sh
```

脚本会构建 `studio-vue/dist`、复制网页和 agents、安装/更新 systemd 单元并重启服务。不要直接修改
`dist`，它是构建产物。机器人地址和密码可放入被 Git 忽略的 `.robot.env`。

部署后至少检查：

```bash
curl -I http://192.168.3.63:8000/
ssh ubuntu@192.168.3.63 \
  'systemctl is-active start_app_node webctl snack-butler nav-safety exploration-nav explorer-agent'
```

涉及底盘移动时还要确认雷达、安全闸门和低压保护；涉及机械臂时先空跑。

## 15. 新增功能应该从哪里改

### 新增页面

1. 在 `studio-vue/src/views/` 新建 `.vue` 文件。
2. 在 `App.vue` 导入并加入 `MENU`。
3. 公共状态优先复用 `useRos()`；避免建立第二条 rosbridge 连接。
4. 通用 UI 再抽到 `components/`。
5. 运行前端构建并检查桌面、平板和窄屏。

### 新增 ROS 实时数据

1. 确认话题名、消息类型、频率和 QoS。
2. 多页面使用时在 `useRos.js` 增加状态与订阅。
3. 高频数据设置 `throttle_rate`，不要让浏览器跟着传感器满频刷新。
4. 增加时间戳并判断新鲜度，避免显示陈旧数据为“在线”。

### 新增控制命令

1. 先在机器人 agent 定义命令、参数校验、状态反馈和失败原因。
2. 再在 `useRos.js` 或页面发布命令。
3. 运动命令必须考虑断线、松手、页面切换、超时和紧急停止。
4. 底盘命令必须接入安全闸门，不允许页面直连驱动。

### 新增 HTTP 功能

在 `webctl_server.py` 增加路由。必须限制目标路径、请求体大小、允许的服务名和子进程参数；不要把任意
shell、任意文件读写或任意 systemd 控制暴露给网页。

### 修改三维模型

- 机器人结构、材质和交互主要在 `Twin.vue`。
- URDF 与网格在 `studio-vue/public/model/`。
- 区分“真实关节状态”“本地拖动预览”“计划轨迹”，不要互相覆盖。
- 2D HTML 标签和 3D 模型缩放属于不同坐标系，需要单独做缩放补偿。
- 修改后从默认视角、放大视角、窄屏和完整总览分别检查。

## 16. 常见误区

- **以为 `torch.cuda.is_available()` 为真就没有 CPU 开销**：YOLO 前后处理、JPEG、深度和 ROS 序列化仍用 CPU。
- **直接改 `dist`**：下次 Vite 构建会全部覆盖。
- **页面自己连接新的 rosbridge**：会产生重复订阅、状态不一致和额外负载。
- **用旧消息判断在线**：必须结合 `state.now - xxxAt`。
- **直发舵机总线**：可能导致 joint states 不更新，孪生和 eye-in-hand 外参错误。
- **把孪生坐标用于真实抓取**：孪生对象经过滤波，只用于显示。
- **只在前端做安全检查**：机器人端仍必须拒绝非法或危险命令。
- **恢复所有厂商 demo**：巡线、手势、AR、跟踪会同时消耗相机、CPU 和内存，详见
  `VENDOR_APPS_STATUS.md`。
- **把网页端口暴露公网**：当前系统按受信任局域网设计，没有完整公网认证边界。

## 17. 新人推荐阅读顺序

1. `README.md`：先跑起来。
2. 本文：建立全局心智模型。
3. `studio-vue/src/App.vue`：理解页面组织。
4. `studio-vue/src/composables/useRos.js`：理解所有实时数据和控制入口。
5. 选择一个小页面，例如 `Telemetry.vue` 或 `Board.vue`，观察状态如何变成 UI。
6. `agents/nav_safety_guard.py`：理解底盘安全边界。
7. 根据方向阅读 `docs/SNACK_BUTLER.md` 或 `docs/AUTONOMOUS_EXPLORATION.md`。
8. `agents/deploy_snack.sh` 和 `docs/DEPLOYMENT.md`：理解代码怎样真正上车。

第一次贡献建议从只读状态卡片或日志字段开始，不要把机械臂标定、相机外参、底盘速度入口作为练手项。

## 18. 排障入口

| 现象 | 第一检查点 |
|---|---|
| 整站打不开 | `webctl.service` 与 `:8000` |
| 页面开了但全离线 | rosbridge `:9090` 与 `start_app_node.service` |
| 只有视频黑屏 | `:8080`、`:8091`、图像话题和 `/api/vision/health` |
| 控制按钮无效 | `state.connected`、目标话题订阅者、agent 日志 |
| 车不走 | `/nav_safety/state` 的 armed/source/reason、雷达和电池 |
| 机械臂模型回弹 | `/controller_manager/joint_states` 是否更新、是否绕过 `/servo_controller` |
| YOLO 慢 | detector device、infer_ms、GPU 负载，以及深度/OpenCV CPU 开销 |
| 抓取偏移 | `table_z`、`tool_len`、相机外参、拍摄时关节姿态 |
| 探索原地停顿 | explorer step/events、Nav2 action、安全急停原因和净空方向 |
| 日志页空白 | `jetson-agent.service`、`/system/log` 与 `/rosout` |

日常排障命令与安全重启顺序见 `docs/OPERATIONS_RUNBOOK.md`。

---

如果只记住三句话：**所有实时状态先看 `useRos.js`；所有真实业务决策看机器人 agent；所有底盘运动
必须经过 `nav_safety_guard.py`。**
