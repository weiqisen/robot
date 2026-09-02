#!/usr/bin/env python3
"""只守护独立视觉视频桥；连续无 JPEG 帧才重启该桥。"""
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
    while True:
        if has_jpeg_frame():
            failures = 0
        else:
            failures += 1
            print('vision bridge frame check failed (%d/%d)' % (failures, FAILURES_BEFORE_RESTART), flush=True)
            if failures >= FAILURES_BEFORE_RESTART and time.monotonic() - last_restart >= RESTART_COOLDOWN:
                print('restarting isolated vision-video.service only', flush=True)
                subprocess.run(['/usr/bin/systemctl', 'restart', 'vision-video.service'], check=False)
                last_restart = time.monotonic()
                failures = 0
                time.sleep(STARTUP_GRACE)
        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    main()
