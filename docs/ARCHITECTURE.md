# 架构与代码地图

## 总体结构

```text
浏览器
  ├─ :8000  webctl_server.py（静态页面 + 同源 API/VNC 桥）
  ├─ :9090  rosbridge（ROS topic/service WebSocket）
  ├─ :8080  web_video_server（MJPEG，WebRTC 失败时回退）
  ├─ :8091  webrtc_agent.py（视频信令）
  └─ :8092  llm_agent.py（自然语言请求）
                    │
                    ▼
             JetRover ROS 2 / systemd
```

前端直接连接机器人服务，没有独立的应用后端或数据库。少量持久化配置保存在机器人用户目录中。

## 目录职责

| 路径 | 职责 |
|---|---|
| `studio-vue/src/App.vue` | 页面注册、hash 导航、全局外壳 |
| `studio-vue/src/views/` | 各功能页面；一个页面通常对应一个机器人能力 |
| `studio-vue/src/composables/useRos.js` | rosbridge 单例、公共订阅/发布、机器人地址和端口 |
| `studio-vue/src/composables/useMjpeg.js` | MJPEG 视频连接 |
| `studio-vue/src/composables/useStreamWatch.js` | 视频流健康状态 |
| `studio-vue/public/model/` | URDF 和三维网格，构建时原样复制 |
| `agents/webctl_server.py` | 生产静态服务、缓存策略、VNC 桥、动作组/孪生/GPU API |
| `agents/jetson_agent.py` | tegrastats、硬件、systemd 服务与日志采集，经 ROS 发布 |
| `agents/webrtc_agent.py` | 从 `:8080` MJPEG 取帧并通过 WebRTC 推给浏览器 |
| `agents/snack_butler.py` | ROS 视觉抓取状态机和配置落盘 |
| `agents/explorer_agent.py` | Frontier 自主探索、Nav2 目标调度与返航 |
| `agents/nav_safety_guard.py` | Nav2/手动速度限幅、雷达心跳、方向近障急停和驱动锁 |
| `agents/lidar_watchdog.py` | 雷达 USB 重枚举后的受限自动恢复 |
| `agents/arm_kinematics.py` | 机械臂 FK/IK 和舵机映射，纯 Python |
| `agents/vision_geometry.py` | eye-in-hand 相机到 `base_link` 的几何变换 |
| `agents/snack_detector.py` | OpenCV HSV 检测和三维定位 |
| `agents/llm_agent.py` | Claude tool use 到 ROS 命令的适配层 |
| `agents/deploy_snack.sh` | 构建、复制和 systemd 部署入口 |
| `tools/sim_robot.py` | Mac 本地最小 rosbridge 兼容模拟器，供网页与任务恢复联调 |
| `design/` | 设计稿/预览，不参与生产构建 |

## 端口与依赖

| 端口 | 进程 | 用途 | 仓库是否负责安装 |
|---:|---|---|---|
| 8000 | `webctl.service` | 网页、`/api/*`、VNC WebSocket 桥 | 是 |
| 8080 | `web_video_server` | ROS 图像转 MJPEG | 否，机器人原系统提供 |
| 8091 | `webrtc-agent.service` | WebRTC `/offer`、`/health` | 脚本会更新，首次服务需手装 |
| 8092 | `llm-agent.service` | `/ask`、`/health` | 是，有环境文件才启用 |
| 9090 | `rosbridge` | ROS WebSocket 和 rosapi | 否，机器人原系统提供 |
| 5900 | `x11vnc` | 本机 VNC TCP，`:8000/api/vnc` 转发 | 否，可选 |

## 主要数据流

### 遥测与系统信息

`jetson_agent.py` 解析 `tegrastats`、`journalctl`、`systemctl` 和硬件信息，向 `/jetson/stats`、`/system/log`、`/system/services`、`/system/hardware` 发布 JSON 字符串。`useRos.js` 常驻订阅并维护全局响应式状态，各页面只消费状态。

### 视觉抓取

相机 RGB/深度和关节状态进入 `snack_butler.py`，依次经过颜色检测、像素反投影、工作区裁剪和 IK。网页向 `/snack_butler/cmd` 发布 JSON，节点向 `/snack_butler/state` 和 `/snack_butler/image_result` 发布结果。细节见 [SNACK_BUTLER.md](SNACK_BUTLER.md)。

### 自主探索

`explorer_agent.py` 从 `/map` 提取 Frontier 聚类，向 Nav2 `NavigateToPose` action 逐个下发目标。Nav2 负责路径规划和避障；agent 负责任务生命周期、不可达目标跳过、低电压/超时返航。网页通过 `/explorer/cmd` 和 `/explorer/state` 控制及展示。细节见 [AUTONOMOUS_EXPLORATION.md](AUTONOMOUS_EXPLORATION.md)。

Nav2 输出被隔离到 `/nav_cmd_vel`，网页手动控制输出到 `/manual_cmd_vel`。二者都必须经过 `nav_safety_guard.py` 显式选择控制源并解锁，最终才发布 `/controller/cmd_vel`。

### 网页辅助 API

`webctl_server.py` 同时提供静态文件及以下能力：

- `/api/vnc`：WebSocket 到本机 `x11vnc:5900` 的桥。
- `/api/camera.jpg`、`/api/desktop.jpg`：同源快照代理。
- `/api/look`：数字孪生外观参数，默认持久化到 `~/twin_look.json`。
- `/api/actions/*`：读写幻尔 `.d6a` SQLite 动作组。
- `/api/gpu_bench/*`：GPU 压测的启动、停止和状态。

### 持久化文件

| 文件 | 含义 | 部署行为 |
|---|---|---|
| `~/snack_butler_config.json` | 标定与抓取配置 | 已存在时不覆盖 |
| `~/.llm_agent.env` | API key/模型环境变量 | 不由仓库创建 |
| `~/twin_look.json` | 数字孪生外观 | 网页 API 写入 |
| `~/software/arm_pc/ActionGroups/*.d6a` | 动作组 | 网页与桌面软件共用 |

## 常见改动落点

- 新增控制台页面：在 `src/views/` 新建组件，再在 `App.vue` 导入并加入 `MENU`。
- 新增通用 ROS 数据：在 `useRos.js` 增加 state 字段和订阅；仅单页使用的数据可在页面局部订阅。
- 新增非 ROS HTTP 功能：在 `webctl_server.py` 添加路由，同时考虑请求大小、路径校验和同源访问。
- 修改机器人地址/公共端口：先改 `useRos.js`；对应 agent 或 systemd 配置也必须同步。
- 修改抓取算法或标定：先读专项文档并运行 `test_kinematics.py`、`test_vision.py`、`test_pipeline.py`。
