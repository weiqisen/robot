# 零食管家 —— 识别 → 算坐标 → 抓到指定区域

最小闭环：**在固定观察位识别桌上的零食 → 反投影出 base_link 坐标 → 闭式 IK → 下探合爪 → 搬到分类筐**。
桌面清空之前可以一直循环跑，适合当长期展示的 Demo。

## 组成

| 文件 | 跑在哪 | 干什么 |
|---|---|---|
| `agents/arm_kinematics.py` | 机器人 | 5 轴臂闭式 FK/IK + 舵机脉冲映射。纯 `math`，无依赖 |
| `agents/vision_geometry.py` | 机器人 | 像素+深度 → base_link。含 URDF 静态外参链（tf2 不可用时兜底） |
| `agents/snack_detector.py` | 机器人 | HSV 色块识别 + 3D 定位。不依赖 rclpy，可离线测 |
| `agents/snack_butler.py` | 机器人 | ROS2 节点：状态机、命令接口、标注图输出 |
| `agents/llm_agent.py` | 机器人 | 自然语言 → 命令（Claude tool use），HTTP :8092 |
| `studio-vue/src/views/Snack.vue` | 网页 | 控制台：画面点选抓取、参数、标定、对话 |
| `agents/test_*.py` | Mac | 离线自测，不需要机器人 |

节点是**独立脚本**，不是 colcon 包 —— 机器人上 `need_compile=False` 的环境里加新包很麻烦，
而这套只用已装好的 `rclpy` 和现成消息类型，跟 `jetson_agent.py` 一样丢进 `~/` 用 systemd 跑。

## 机器结构里几个要命的点

**相机挂在 `link4` 上，是 eye-in-hand。** 不是装在车身上的。所以：
- 像素→世界必须带上当前关节角；
- **只在固定观察位做识别和定位**，一旦开始下探就不再用视觉（边动边看会自激）。

**`base_link` 不在地面上，在轮子接地面上方 0.11609 m。** 所以机器人自己所站的那个台面，
在 `base_link` 系里是 **z = -0.116**，不是 0。`table_z` 填错是抓不到的头号原因。

**观察位是搜出来的，不是拍脑袋定的。** 关节角 `[0, 8.0, 75.6, 101.4, 0]°`，
相机悬在 `(0.217, 0, 0.185)`、**近乎垂直俯视**（视线与竖直只差 5°）。
169 个可抓格点全部在视野内，夹爪完全不进画面，可抓区四角都在画面里。
正俯视比斜视好：视差小，而且深度失效走平面兜底时，桌面高度估错的横向放大系数
≈ tan(视线与竖直的夹角)，几乎为 0 —— 换成斜 45° 看，同样估错 2 cm 会放大成 15 mm 偏差，
正俯视只有 3 mm。（搜索方法见 `test_vision.py` 第 2 节注释，改结构或换相机后重搜。）

**工作空间**（`test_kinematics.py` 实测，台面 z=-0.116）：
- 纯垂直下抓（pitch=180°）：base_link 前方 `x ∈ [0.120, 0.265] m`
- 放开 pitch（近处后仰、远处前倾）：`x ∈ [0.050, 0.340] m`
- `x=0.20` 处侧向 `|y| ≤ 0.265 m`

投影落在 `workspace_rel` 盒子外的检测结果直接丢掉 —— 挡误检最有效的一招。
这个盒子的 z 是**相对 `table_z`** 写的，换个高度的桌子不用重调。

## 定位精度（合成场景实测）

| 路径 | 水平误差 | 说明 |
|---|---|---|
| 深度可用 | **~1.4 mm** | 掩膜内像素各自反投影取 3D 中位数 |
| 深度全废（质心整块打掉 + 35% 空洞） | ~2 mm | 中位数扛得住，单点/小窗口这时直接取不到值 |
| 无深度，射线 × 「桌面 + 假设物体高」 | **≤ 3 mm** | `assume_object_h` 估错 1 cm ≈ 抓偏 1.5 mm |
| 无深度，射线 × 桌面（**错误做法**） | 4~9 mm | 看到的是物体顶面，不是桌面 |

注意这套数字用的是同一套相机模型渲染的场景，**只能证明代码链路是通的，证明不了外参标定对** —— 那必须真机验。

## 上真机的顺序（别跳）

```bash
# 0. 机器人上装依赖（llm_agent 才需要）
pip3 install anthropic websocket-client

# 1. 从 Mac 部署（会蹲守到机器人上线）
./agents/deploy_snack.sh

# 2. 打开 http://<机器人IP>:8000/#snack
```

3. **先开「空跑」开关**（画面下方那个 switch）。这时识别、算坐标、算 IK 全跑，但一个舵机指令都不发。
   确认「识别结果」表里坐标合理（零食在 x 0.15~0.30、y ±0.15 这个量级）、`能抓到` 是绿的。

4. **标定舵机**。点「自动标定舵机」，**先把机械臂周围清空**。
   节点会小幅活动 5 次，拿驱动自己发的 `joint_states`(弧度) 对 `servo_states`(脉冲) 做最小二乘，
   拟合出每个关节的**方向**和**零位**。这一步不做，IK 算得再准，下发的脉冲方向可能是反的 ——
   所以 `require_calibration` 默认拦着，没标定不许下探。

5. **确认桌面高度**。默认 `-0.116`，对应「零食和机器人放在同一个平面上」。
   要是零食放在比机器人高/低的台子上，按实际差值加减。填错是抓不到的头号原因；
   空跑时看识别结果里的 z 值合不合理最容易发现。

6. **调夹爪**。点「张爪/合爪」看实际开合，调 `夹爪张开/闭合` 两个滑块，合适了「保存到机器人」。

7. 关掉空跑，先点单个零食「抓这个」。稳了再上「自动整理桌面」。

8. 教投放区：手动（数字孪生页的关节滑块，或 `goto` 命令）把末端摆到筐口上方，点「当前位置记为 A 筐」。

## 命令接口

发 `std_msgs/String`（JSON）到 `/snack_butler/cmd`：

```jsonc
{"action":"observe"}                      // 回观察位
{"action":"detect"}                       // 只识别
{"action":"pick","label":"red"}           // 抓某个颜色
{"action":"pick_at","u":320,"v":240}      // 抓画面上这一点的（网页点击就是这个）
{"action":"auto","on":true}               // 自动循环整理
{"action":"stop"}
{"action":"gripper","open":true}
{"action":"calibrate"}
{"action":"teach_bin","name":"A"}
{"action":"goto","x":0.22,"y":0.0,"z":0.05}
{"action":"set_config","patch":{"table_z":0.02}}   // 改参数并落盘
```

状态在 `/snack_butler/state`（JSON），标注图在 `/snack_butler/image_result`
（web_video_server: `http://IP:8080/stream?topic=/snack_butler/image_result&type=mjpeg`）。

## 自然语言

`llm_agent.py` 用 Claude（`claude-opus-5`，adaptive thinking）做 tool use，工具就是上面那套命令：
`get_status / look / pick / tidy_all / stop / move_arm / gripper / set_route / drive / say`。
底盘 `drive` 的速度和时长被硬夹在 ±0.15 m/s、≤2 s，模型手滑也开不走。

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > ~/.llm_agent.env && chmod 600 ~/.llm_agent.env
sudo systemctl enable --now llm-agent
```

网页「自然语言指令」框直接 POST 到 `:8092/ask`，返回里带模型实际下发了哪些命令，便于核对它没瞎编。

## 离线自测（不需要机器人）

```bash
python3 agents/test_kinematics.py     # 纯标准库
python3 agents/test_vision.py         # 纯标准库
python3 -m venv .venv && .venv/bin/pip install numpy opencv-python-headless
.venv/bin/python agents/test_pipeline.py   # 合成场景跑通识别→坐标→IK
```

## 排查

| 现象 | 多半是 |
|---|---|
| 网页说「节点未运行」 | `sudo journalctl -u snack-butler -n 50`。多半是 zsh 环境没 source 到 |
| 识别得到但全是「够不着」 | `table_z` 填错，或零食放得太远/太偏，超出 `workspace` |
| 来源一直显示「平面」 | 深度图没数据或包装太黑/反光。先看数据源那排 `深度` 标签是不是绿的 |
| 抓的位置总是偏一个固定量 | 外参：`camera_frame` 对不对（tf2 用的哪个光学系），或 `assume_object_h` |
| 手臂往奇怪方向走 | 没标定，或标定时关节没动够（`joint_states` 有没有数） |
| 机器人反复掉线 | **先量电池**。3S 电压低到 ~9V 会反复欠压重启，别误判成代码问题 |
