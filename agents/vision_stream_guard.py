#!/usr/bin/env python3
"""守护视觉流：先重启桥，仍无帧才恢复上游相机 bringup。"""
import subprocess
import time
import urllib.request

URL = 'http://127.0.0.1:8082/stream'
CHECK_INTERVAL = 10
FAILURES_BEFORE_RESTART = 2
RESTART_COOLDOWN = 45
STARTUP_GRACE = 45


def has_jpeg_frame():
    try:
        with urllib.request.urlopen(URL, timeout=5) as response:
            deadline = time.monotonic() + 4
            data = b''
            while time.monotonic() < deadline:
                data += response.read(4096)
                if b'\xff\xd8' in data:
                    return True
        return False
    except Exception:
        return False


def main():
    # source ~/.zshrc + importing ROS/OpenCV is slow on Jetson.  Do not mistake
    # that cold start for an outage and restart the bridge before it can bind.
    time.sleep(STARTUP_GRACE)
    failures = 0
    last_restart = 0.0
    bridge_restarts_since_frame = 0
    while True:
        if has_jpeg_frame():
            failures = 0
            bridge_restarts_since_frame = 0
        else:
            failures += 1
            print('vision bridge frame check failed (%d/%d)' % (failures, FAILURES_BEFORE_RESTART), flush=True)
            if failures >= FAILURES_BEFORE_RESTART and time.monotonic() - last_restart >= RESTART_COOLDOWN:
                if bridge_restarts_since_frame:
                    # 视频桥重启后仍持续无 JPEG，根因通常是相机容器虽在但没有发布帧。
                    # 这个固定 sudo 权限仅允许重启 bringup；不会发送机械臂或底盘命令。
                    print('vision bridge still has no frames; restarting upstream start_app_node.service', flush=True)
                    subprocess.run(['sudo', '-n', '/usr/bin/systemctl', 'restart', 'start_app_node.service'], check=False)
                    bridge_restarts_since_frame = 0
                else:
                    print('restarting isolated vision-video.service', flush=True)
                    subprocess.run(['/usr/bin/systemctl', 'restart', 'vision-video.service'], check=False)
                    bridge_restarts_since_frame = 1
                last_restart = time.monotonic()
                failures = 0
                time.sleep(STARTUP_GRACE)
        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    main()
