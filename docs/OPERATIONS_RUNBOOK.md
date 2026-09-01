# 机器人运维手册

本手册用于日常排障。先观察、记录，再进行最小范围的恢复；**机器人正在移动、机械臂正在执行时，禁止重启 ROS、相机或导航服务**。需要重启时，先停止任务并确认安全闸门锁定。

## 0. 排障原则

1. 先在「运行日志」查看服务状态、最近日志和重启次数，再登录机器人。
2. 一次只处理一个服务；重启后至少观察 30 秒，确认现象是否消失。
3. `start_app_node.service` 是底层 ROS/传感器启动器，重启影响雷达、相机、底盘和导航；它不是常规的“刷新相机”按钮。
4. 不要连续反复重启。若两次最小恢复无效，保留日志并转向硬件、供电、USB 或配置排查。

## 1. 快速健康检查

在 Mac 终端执行（将 `<机器人IP>` 换为实际地址）：

```bash
ssh ubuntu@<机器人IP> 'systemctl --no-pager --full status webctl snack-butler explorer-agent exploration-nav nav-safety lidar-watchdog jetson-agent webrtc-agent'
curl -I http://<机器人IP>:8000/
curl http://<机器人IP>:8091/health
```

重点关注：服务是否 `active (running)`、`NRestarts` 是否持续增加、底盘电压是否足够、ROS 是否已连接。`llm-agent` 未配置密钥时不运行是正常的。

## 2. 运行日志空白

### 表现

「运行日志」显示服务正常，但终端区域没有任何日志。

### 处理顺序

1. 刷新网页，等待最多 15 秒；页面会展示服务启动快照，机器人端也会补发服务启动与心跳事件。
2. 检查遥测代理：

```bash
ssh ubuntu@<机器人IP> 'sudo systemctl status jetson-agent --no-pager; sudo journalctl -u jetson-agent -n 100 --no-pager'
```

3. 仅在 `jetson-agent` 异常时重启它：

```bash
ssh ubuntu@<机器人IP> 'sudo systemctl restart jetson-agent'
```

4. 若网页其他 ROS 数据也离线，再检查 `rosbridge` 的 9090 端口；不要因此重启全部 ROS。

## 3. 抓取页相机无画面

### 区分故障层

| 检查结果 | 含义 | 下一步 |
|---|---|---|
| `snack-butler` 未运行 | 视觉处理服务故障 | 仅重启 `snack-butler` |
| `/snack_butler/image_result` 无帧 | 原始 RGB 相机或 ROS 图像链路故障 | 检查 RGB 话题和相机驱动 |
| 原始图像有帧、页面无画面 | 网页/MJPEG/WebRTC 链路故障 | 检查 `web_video_server`、浏览器网络与 `webrtc-agent` |
| 相机驱动已识别设备但长期无帧 | 常见为 USB 带宽、供电、线材或相机固件问题 | 停止任务，做物理检查；不要循环重启 |

### 安全检查命令

```bash
ssh ubuntu@<机器人IP> 'source ~/.zshrc; ros2 topic list | grep -E "depth_cam/rgb/image_raw|snack_butler/image_result"'
ssh ubuntu@<机器人IP> 'source ~/.zshrc; timeout 8 ros2 topic hz /depth_cam/rgb/image_raw --qos-reliability best_effort'
ssh ubuntu@<机器人IP> 'curl -I "http://127.0.0.1:8080/stream?topic=/snack_butler/image_result&type=mjpeg"'
ssh ubuntu@<机器人IP> 'sudo journalctl -u snack-butler -n 120 --no-pager'
```

相机图像通常采用 best-effort QoS，未带 `--qos-reliability best_effort` 的 `ros2 topic hz` 结果不能作为“无帧”的结论。

### 恢复边界

- 仅 `snack-butler` 异常：确认任务停止后重启 `sudo systemctl restart snack-butler`。
- 相机驱动本身无帧：先确认底盘静止、探索已停止、安全闸门锁定；最多一次重启 `start_app_node.service`，随后观察。
- 若仍无帧，检查 USB 线缆、接口、供电与 USB 速率。两台 Orbbec 相机降到 USB 2.0（`480`）时，同时开启 RGB、深度、IR 容易带宽不足；应优先恢复 USB 3.x 连接，而不是继续重启软件。

查看 USB 链路：

```bash
ssh ubuntu@<机器人IP> 'for f in /sys/bus/usb/devices/*/speed; do printf "%s " "$f"; cat "$f"; done'
ssh ubuntu@<机器人IP> 'sudo dmesg | tail -n 160 | grep -iE "orbbec|uvc|usb"'
```

## 4. 服务异常、反复重启

```bash
ssh ubuntu@<机器人IP> 'sudo systemctl show snack-butler -p ActiveState -p SubState -p NRestarts -p ExecMainStatus'
ssh ubuntu@<机器人IP> 'sudo journalctl -u snack-butler -n 150 --no-pager'
```

先处理日志中的第一条明确错误（依赖、ROS 环境、端口、配置），不要只看最后一次重启。单服务恢复命令：

```bash
ssh ubuntu@<机器人IP> 'sudo systemctl restart <服务名>'
```

推荐的最小影响顺序：`webctl` → `jetson-agent` / `webrtc-agent` → `snack-butler` / `explorer-agent`。`exploration-nav` 与 `start_app_node` 会影响移动能力，必须在停止任务后操作。

## 5. 探索不能走、返航无反应

1. 先看页面是否提示安全闸门、Nav2、雷达、地图和返航原点状态。
2. 查看 `explorer-agent`、`exploration-nav`、`nav-safety` 的最近日志。
3. 近障急停连续发生时，不应连续点击探索；先清理车身周围障碍，检查机械臂是否处于收纳/观察位。
4. 没有返航原点时，先在安全开阔区域重新开始一次探索，让系统记录原点；紧急情况优先手动接管。

```bash
ssh ubuntu@<机器人IP> 'sudo journalctl -u explorer-agent -u exploration-nav -u nav-safety -n 160 --no-pager'
```

## 6. 部署后自检与回滚

部署完成后先验证网页、服务和相机，不要立即下发抓取或探索任务。

```bash
curl -I http://<机器人IP>:8000/
ssh ubuntu@<机器人IP> 'systemctl is-active webctl snack-butler explorer-agent exploration-nav nav-safety jetson-agent webrtc-agent'
```

需要回滚时，开发机切换到已知 Git 提交，重新部署；`snack_butler_config.json` 是独立标定数据，代码回滚不会回退它。详见 [部署与运维](DEPLOYMENT.md)。
