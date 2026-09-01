#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JetRover Jetson 硬件遥测采集 agent
解析 tegrastats 并通过 rosbridge 发布为 /jetson/stats (std_msgs/String, 内容为JSON)
无需 rclpy / jetson-stats，仅依赖 tegrastats(Jetson原生) 与 websocket-client。
作为 systemd 服务常驻。
"""
import subprocess, re, json, time, os, sys, threading

WS_URL = "ws://127.0.0.1:9090"
TOPIC = "/jetson/stats"
LOG_TOPIC = "/system/log"
SVC_TOPIC = "/system/services"
HW_TOPIC = "/system/hardware"
# 只列我们自己部署上车的那几个 py 服务，系统自带的（ssh / nvargus / x11vnc 等）不管。
# 第三列是对应的脚本路径 —— 一起报它的修改时间，就能一眼看出刚推的版本有没有真的落地。
# 列表里不存在的服务会标成「未安装」而不是报错。
SVC_UNITS = [
    ("webctl",        "网页服务 :8000",        "/home/ubuntu/web_control/index.html"),
    ("jetson-agent",  "遥测 / 日志 / 服务监控", "/home/ubuntu/jetson_agent.py"),
    ("snack-butler",  "视觉引导抓取",          "/home/ubuntu/snack_butler.py"),
    ("explorer-agent", "自主避障探索 / 返航",   "/home/ubuntu/explorer_agent.py"),
    ("exploration-nav", "在线 SLAM + Nav2",      "/home/ubuntu/exploration_bringup.launch.py"),
    ("nav-safety",     "导航速度安全闸门",       "/home/ubuntu/nav_safety_guard.py"),
    ("lidar-watchdog", "雷达断连自动恢复",       "/home/ubuntu/lidar_watchdog.py"),
    ("webrtc-agent",  "WebRTC 信令 :8091",     "/home/ubuntu/webrtc_agent.py"),
    ("llm-agent",     "自然语言指令 :8092",     "/home/ubuntu/llm_agent.py"),
]
# 网页「运行日志」要看的服务。跟着 journalctl -f 走，不用轮询。
# 自建服务必须全部进入日志流；start_app_node / wifi 作为关键依赖一并保留。
LOG_UNITS = [u for u, _, _ in SVC_UNITS] + ["start_app_node", "wifi"]

_WS = None
_WS_LOCK = threading.Lock()


def ws_send(obj):
    """两个线程共用一条 websocket，发送要串行"""
    with _WS_LOCK:
        if _WS is None:
            return False
        try:
            _WS.send(json.dumps(obj))
            return True
        except Exception:
            return False


def _uvc_profiles(usb_id):
    """从 USB 视频描述符里读这颗摄像头真正支持的分辨率/帧率。
    RGB 那颗是标准 UVC，描述符是权威来源，比查规格书靠谱。
    深度那颗是私有接口，没有 UVC 描述符，读不到——如实留空。"""
    out = {}
    fmt = cur = None
    for ln in _run(["sudo", "-n", "lsusb", "-v", "-d", usb_id], timeout=15).splitlines():
        t = ln.strip()
        m = re.match(r"bDescriptorSubtype\s+\d+ \((FORMAT_\w+)\)", t)
        if m:
            fmt = m.group(1).replace("FORMAT_", ""); continue
        m = re.match(r"wWidth\s+(\d+)", t)
        if m:
            cur = [int(m.group(1))]; continue
        m = re.match(r"wHeight\s+(\d+)", t)
        if m and cur:
            cur.append(int(m.group(1))); continue
        m = re.match(r"dwFrameInterval\(\s*0\)\s+(\d+)", t)
        if m and cur and len(cur) == 2:
            iv = int(m.group(1))
            out.setdefault(fmt or "?", set()).add((cur[0], cur[1], round(1e7 / iv) if iv else 0))
            cur = None
    return {k: sorted(v, reverse=True) for k, v in out.items()}


_HW_CACHE = {}


def hardware_snapshot():
    """整车硬件清单。绝大部分是静态的，算一次缓存住；只有网络/串口会变。"""
    hw = {}

    if "usb" not in _HW_CACHE:
        usb = []
        for ln in _run(["lsusb"]).splitlines():
            m = re.match(r"Bus (\d+) Device (\d+): ID (\w{4}:\w{4})\s*(.*)", ln.strip())
            if m and "root hub" not in m.group(4).lower():
                usb.append({"id": m.group(3), "name": m.group(4).strip() or "(未命名设备)"})
        _HW_CACHE["usb"] = usb
        _HW_CACHE["rgb_profiles"] = _uvc_profiles("2bc5:0559")

        # 相机 / 雷达的型号固件在 app 启动日志里，抓一次就够
        log = _run(["journalctl", "-u", "start_app_node", "-n", "4000", "--no-pager"], timeout=20)
        cam = {}
        for k, pat in (("model", r"Device (.+?) connected"), ("serial", r"Serial number: (\S+)"),
                       ("fw", r"Firmware version: (\S+)")):
            m = re.findall(pat, log)
            if m:
                cam[k] = m[-1]
        for st in ("depth", "ir", "color"):
            m = re.findall(r"Stream %s width: (\d+) height: (\d+) fps: (\d+) format: (\S+)" % st, log)
            if m:
                w, h, f, fmt = m[-1]
                cam[st] = {"w": int(w), "h": int(h), "fps": int(f), "fmt": fmt}
        _HW_CACHE["camera"] = cam

        lidar = {}
        for k, pat in (("serial", r"SLLidar S/N: (\S+)"), ("fw", r"Firmware Ver: (\S+)"),
                       ("hw", r"Hardware Rev: (\S+)"), ("mode", r"current scan mode: (.+?),")):
            m = re.findall(pat, log)
            if m:
                lidar[k] = m[-1].strip()
        m = re.findall(r"sample rate: (\d+) Khz, max_distance: ([\d.]+) m, scan frequency:([\d.]+) Hz", log)
        if m:
            lidar["sample_khz"], lidar["max_m"], lidar["hz"] = m[-1]
        _HW_CACHE["lidar"] = lidar

    hw.update({k: _HW_CACHE[k] for k in ("usb", "rgb_profiles", "camera", "lidar")})

    # 存储
    disks = []
    for ln in _run(["lsblk", "-dn", "-o", "NAME,SIZE,MODEL,TRAN"]).splitlines():
        f = ln.split(None, 3)
        if f and not f[0].startswith(("loop", "zram")):
            disks.append({"name": f[0], "size": f[1] if len(f) > 1 else "",
                          "model": (f[2] if len(f) > 2 else "").strip(),
                          "tran": (f[3] if len(f) > 3 else "").strip()})
    hw["disks"] = disks

    # 网络接口
    nets = []
    for ln in _run(["ip", "-br", "addr"]).splitlines():
        f = ln.split()
        if f and f[0] != "lo" and not f[0].startswith(("docker", "veth", "l4tbr")):
            nets.append({"name": f[0], "state": f[1] if len(f) > 1 else "",
                         "addr": " ".join(a for a in f[2:] if "." in a)})
    hw["nets"] = nets

    # 串口（雷达和扩展板都挂在这上面，掉线时最先看这里）
    ser = []
    for name in sorted(os.listdir("/dev")):
        if not (name.startswith(("ttyCH341USB", "ttyACM", "ttyUSB")) or name == "lidar"):
            continue
        path = "/dev/" + name
        try:
            tgt = os.readlink(path) if os.path.islink(path) else ""
        except OSError:
            tgt = ""
        ser.append({"dev": path, "link": tgt})
    hw["serial"] = ser
    return hw


def hardware_thread():
    while True:
        try:
            hw = hardware_snapshot()
            if hw.get("usb"):
                ws_send({"op": "publish", "topic": HW_TOPIC,
                         "msg": {"data": json.dumps(hw, ensure_ascii=False)}})
        except Exception:
            pass
        time.sleep(60)


def services_snapshot():
    """一次 systemctl show 拿全部服务的状态，比每个服务 shell 一次便宜得多。"""
    names = [u for u, _, _ in SVC_UNITS]
    props = ("Id,ActiveState,SubState,UnitFileState,MainPID,NRestarts,"
             "MemoryCurrent,ExecMainStartTimestampMonotonic,LoadState")
    out = _run(["systemctl", "show", "-p", props] + [n + ".service" for n in names], timeout=12)
    if not out.strip():
        return []          # 超时/失败：宁可这一轮不发，也别发个空列表把界面刷没
    blocks, cur = [], {}
    for line in out.splitlines():
        if not line.strip():
            if cur:
                blocks.append(cur); cur = {}
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            cur[k] = v
    if cur:
        blocks.append(cur)

    now_mono = 0.0
    try:
        now_mono = float(_read("/proc/uptime").split()[0])
    except Exception:
        pass

    desc = {u: d for u, d, _ in SVC_UNITS}
    paths = {u: p for u, _, p in SVC_UNITS}
    svcs = []
    for i, b in enumerate(blocks):
        name = (b.get("Id", "") or (names[i] + ".service")).replace(".service", "")
        load = b.get("LoadState", "")
        st = b.get("ActiveState", "unknown")
        mem = b.get("MemoryCurrent", "")
        start_mono = b.get("ExecMainStartTimestampMonotonic", "0")
        up = None
        try:
            if st == "active" and start_mono.isdigit() and int(start_mono) > 0:
                up = max(0, int(now_mono - int(start_mono) / 1e6))
        except Exception:
            pass
        svcs.append({
            "name": name,
            "desc": desc.get(name, ""),
            # 服务文件根本不存在时 systemctl 会报 LoadState=not-found
            "state": "notfound" if load == "not-found" else st,
            "sub": b.get("SubState", ""),
            "enabled": b.get("UnitFileState", ""),
            "pid": int(b["MainPID"]) if b.get("MainPID", "0").isdigit() else 0,
            "restarts": int(b["NRestarts"]) if b.get("NRestarts", "0").isdigit() else 0,
            "mem_mb": round(int(mem) / 1048576, 1) if mem.isdigit() else None,
            "uptime": up,
            "file": paths.get(name, ""),
            "mtime": (int(os.path.getmtime(paths[name]))
                      if name in paths and os.path.exists(paths[name]) else None),
        })
    return svcs


def services_thread():
    """推服务状态，并产生低频心跳/状态变化事件，避免安静服务长期没有可学习日志。"""
    previous = {}
    last_heartbeat = 0.0
    initial_pending = True
    while True:
        try:
            svcs = services_snapshot()
            if svcs:      # 拿不到就跳过这一轮，网页保持上一次的显示
                ws_send({"op": "publish", "topic": SVC_TOPIC,
                         "msg": {"data": json.dumps({"ts": time.time(), "services": svcs},
                                                    ensure_ascii=False)}})
                now = time.time()
                lines = []
                for s in svcs:
                    old = previous.get(s["name"])
                    cur = (s["state"], s["sub"], s["pid"], s["restarts"])
                    if initial_pending:
                        lines.append({"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                      "unit": s["name"], "src": "service-monitor",
                                      "lvl": "info" if s["state"] == "active" else "warn",
                                      "msg": "[startup] %s/%s pid=%s uptime=%ss mem=%sMB restarts=%s" %
                                             (cur[0], cur[1], cur[2], s["uptime"], s["mem_mb"], cur[3])})
                    elif old is not None and old != cur:
                        lines.append({"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                      "unit": s["name"], "src": "service-monitor", "lvl": "warn",
                                      "msg": "[state] %s/%s pid=%s restarts=%s (此前 %s/%s pid=%s restarts=%s)" %
                                             (cur[0], cur[1], cur[2], cur[3], old[0], old[1], old[2], old[3])})
                    previous[s["name"]] = cur
                if now - last_heartbeat >= 60:
                    for s in svcs:
                        lines.append({"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                      "unit": s["name"], "src": "service-monitor",
                                      "lvl": "info" if s["state"] == "active" else "warn",
                                      "msg": "[heartbeat] %s/%s pid=%s uptime=%ss mem=%sMB restarts=%s" %
                                             (s["state"], s["sub"], s["pid"], s["uptime"],
                                              s["mem_mb"], s["restarts"])})
                    last_heartbeat = now
                if lines:
                    sent = ws_send({"op": "publish", "topic": LOG_TOPIC,
                                    "msg": {"data": json.dumps({"lines": lines}, ensure_ascii=False)}})
                    # 链路未连通时不能把首批状态丢掉；下一轮连接成功后再补发。
                    if sent:
                        initial_pending = False
        except Exception:
            pass
        time.sleep(15)


def journal_thread():
    """tail systemd 日志并推到 /system/log。断了就重来，别把主循环拖下水。"""
    args = ["journalctl", "-f", "-n", "120", "-o", "json", "--no-pager"]
    for u in LOG_UNITS:
        args += ["-u", u]
    while True:
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, text=True,
                                    stderr=subprocess.DEVNULL, bufsize=1)
            buf, last_flush = [], time.time()
            for line in proc.stdout:
                line = line.rstrip("\n")
                if not line or line.startswith("-- "):
                    continue
                try:
                    j = json.loads(line)
                    unit = (j.get("_SYSTEMD_UNIT") or j.get("UNIT") or "").replace(".service", "")
                    pri = int(j.get("PRIORITY", 6))
                    d = {"t": time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                             time.localtime(int(j.get("__REALTIME_TIMESTAMP", "0")) / 1e6)),
                         "unit": unit, "src": j.get("SYSLOG_IDENTIFIER") or unit,
                         "msg": str(j.get("MESSAGE", "")),
                         "lvl": "error" if pri <= 3 else "warn" if pri == 4 else "info"}
                except Exception:
                    d = {"t": "", "unit": "", "src": "journal", "msg": line, "lvl": "info"}
                low = d["msg"].lower()
                if d["lvl"] == "info" and any(x in low for x in ("error", "traceback", "failed", "exception")):
                    d["lvl"] = "error"
                elif d["lvl"] == "info" and any(x in low for x in ("warn", "died")):
                    d["lvl"] = "warn"
                # 攒批：日志一忙起来一秒能有几十行，一行一条 websocket 消息会把
                # rosbridge 的序列化压满（实测它一个人吃掉 50% 的核）。0.5 秒合并发一次。
                buf.append(d)
                if time.time() - last_flush >= 0.5 or len(buf) >= 40:
                    ws_send({"op": "publish", "topic": LOG_TOPIC,
                             "msg": {"data": json.dumps({"lines": buf}, ensure_ascii=False)}})
                    buf = []
                    last_flush = time.time()
        except Exception:
            pass
        time.sleep(5)


def _read(path, default=''):
    try:
        with open(path) as f:
            return f.read().strip('\x00').strip()
    except Exception:
        return default


def _run(cmd, timeout=6):
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=timeout)
    except Exception:
        return ''


# L4T 大版本 -> JetPack 版本。官方只发 L4T 号，JetPack 号得自己查表。
JETPACK = {'36.3': '6.0', '36.2': '6.0 DP', '35.4': '5.1.2', '35.3': '5.1.1',
           '35.2': '5.1', '35.1': '5.0.2', '32.7': '4.6.x'}


def static_info():
    """开机只读一次的东西：板子型号、固件/驱动版本、CPU、网络。"""
    info = {}
    info['model'] = _read('/proc/device-tree/model')
    info['serial'] = _read('/proc/device-tree/serial-number')
    info['hostname'] = _run(['hostname']).strip()
    info['kernel'] = _run(['uname', '-r']).strip()
    info['arch'] = _run(['uname', '-m']).strip()
    info['ros_distro'] = os.environ.get('ROS_DISTRO', 'humble')
    info['py'] = '%d.%d.%d' % sys.version_info[:3]

    r = _read('/etc/nv_tegra_release')
    m = re.search(r'# R(\d+).*REVISION:\s*([\d.]+)', r)
    if m:
        rel = '%s.%s' % (m.group(1), m.group(2))
        info['l4t'] = 'L4T R' + rel
        key = rel.rsplit('.', 1)[0] if rel.count('.') > 1 else rel
        if key in JETPACK:
            info['jetpack'] = 'JetPack ' + JETPACK[key]
    m = re.search(r'GCID:\s*(\d+)', r)
    if m:
        info['gcid'] = m.group(1)
    m = re.search(r'DATE:\s*(.+)$', r.split('\n')[0])
    if m:
        info['bsp_date'] = m.group(1).strip()

    try:
        info['cuda'] = json.loads(_read('/usr/local/cuda/version.json') or '{}')['cuda']['version']
    except Exception:
        pass
    pkgs = _run(['dpkg-query', '-W', '-f=${Package} ${Version}\n',
                 'libcudnn8', 'libnvinfer8', 'nvidia-l4t-core'])
    for line in pkgs.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        name, ver = parts
        if name == 'libcudnn8':
            info['cudnn'] = ver.split('-')[0]
        elif name == 'libnvinfer8':
            info['tensorrt'] = ver.split('-')[0]
        elif name == 'nvidia-l4t-core':
            info['l4t_pkg'] = ver
    try:
        import cv2
        info['opencv'] = cv2.__version__
    except Exception:
        pass

    info['cpu_cores'] = os.cpu_count()
    khz = _read('/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq')
    if khz.isdigit():
        info['cpu_max_mhz'] = int(khz) // 1000

    out = _run(['nvpmodel', '-q'])
    m = re.search(r'NV Power Mode:\s*(\S+)', out)
    if m:
        info['power_mode'] = m.group(1)
    m = re.search(r'^\s*(\d+)\s*$', out, re.M)
    if m:
        info['power_mode_id'] = int(m.group(1))

    for line in _run(['nmcli', '-t', '-f', 'ACTIVE,SSID,SIGNAL,RATE', 'dev', 'wifi']).splitlines():
        if line.startswith('yes:'):
            f = line.split(':')
            info['wifi_ssid'] = f[1]
            if len(f) > 2 and f[2].isdigit():
                info['wifi_signal'] = int(f[2])
            if len(f) > 3:
                info['wifi_rate'] = f[3]
            break
    ips = [a for a in _run(['hostname', '-I']).split()
           if '.' in a and not a.startswith(('127.', '172.17.', '192.168.55.'))]
    if ips:
        info['ip'] = ips[0]
    return info


_NET_PREV = {}


def dynamic_info():
    """每秒都在变的：负载、磁盘、风扇、网络速率、进程数、降频保护。"""
    d = {}
    up = _read('/proc/uptime').split()
    if up:
        d['uptime'] = int(float(up[0]))
    try:
        s = os.statvfs('/')
        d['disk_total'] = round(s.f_blocks * s.f_frsize / 1e9, 1)
        d['disk_used'] = round((s.f_blocks - s.f_bfree) * s.f_frsize / 1e9, 1)
    except Exception:
        pass
    la = _read('/proc/loadavg').split()
    if len(la) >= 3:
        d['load'] = [float(v) for v in la[:3]]
        if '/' in la[3]:
            d['procs'] = int(la[3].split('/')[1])
    # 风扇：不同 L4T 路径不一样，挨个试
    for path in ('/sys/devices/pwm-fan/target_pwm',
                 '/sys/class/hwmon/hwmon0/pwm1', '/sys/class/hwmon/hwmon1/pwm1',
                 '/sys/class/hwmon/hwmon2/pwm1', '/sys/class/hwmon/hwmon3/pwm1'):
        v = _read(path)
        if v.isdigit():
            d['fan_pwm'] = int(v)
            d['fan_pct'] = round(int(v) / 255.0 * 100)
            break
    # 网卡速率：两次采样差
    try:
        now = time.time()
        for line in open('/proc/net/dev').read().splitlines()[2:]:
            name, rest = line.split(':', 1)
            name = name.strip()
            if name in ('lo',) or name.startswith(('docker', 'veth', 'l4tbr')):
                continue
            f = rest.split()
            rx, tx = int(f[0]), int(f[8])
            prev = _NET_PREV.get(name)
            _NET_PREV[name] = (now, rx, tx)
            if prev and now > prev[0]:
                dt = now - prev[0]
                if rx > prev[1] or tx > prev[2]:
                    d.setdefault('net', {})[name] = {
                        'rx_kbs': round((rx - prev[1]) / dt / 1024, 1),
                        'tx_kbs': round((tx - prev[2]) / dt / 1024, 1),
                        'rx_mb': round(rx / 1e6, 1), 'tx_mb': round(tx / 1e6, 1)}
    except Exception:
        pass
    return d


def parse(line):
    d = {}
    m = re.search(r'RAM (\d+)/(\d+)MB', line)
    if m: d['ram_used'], d['ram_total'] = int(m.group(1)), int(m.group(2))
    m = re.search(r'SWAP (\d+)/(\d+)MB', line)
    if m: d['swap_used'], d['swap_total'] = int(m.group(1)), int(m.group(2))
    m = re.search(r'CPU \[([^\]]+)\]', line)
    if m:
        cores = []
        for c in m.group(1).split(','):
            mm = re.match(r'(\d+)%@(\d+)', c)
            if mm: cores.append({'load': int(mm.group(1)), 'freq': int(mm.group(2))})
            else:  cores.append({'load': 0, 'freq': 0, 'off': True})
        d['cpu'] = cores
    m = re.search(r'GR3D_FREQ (\d+)%(?:@(\d+))?', line)
    if m:
        d['gpu'] = int(m.group(1))
        if m.group(2):
            d['gpu_freq'] = '%s MHz' % m.group(2)
    m = re.search(r'EMC_FREQ (\d+)%', line)
    if m: d['emc'] = int(m.group(1))
    # 温度  形如 CPU@44.5C GPU@43C tj@45C
    d['temps'] = {k: float(v) for k, v in re.findall(r'(\w+)@([\d.]+)C', line)}
    # 功耗  形如 VDD_IN 4321mW/4321mW  POM_5V_GPU ...
    d['power'] = {k: {'now': int(a), 'avg': int(b)}
                  for k, a, b in re.findall(r'(VDD\w+|POM\w+|VIN\w+|VDDQ\w+) (\d+)mW/(\d+)mW', line)}
    return d

def main():
    try:
        from websocket import create_connection
    except Exception:
        print("需要 websocket-client: pip3 install websocket-client"); return
    global _WS
    si = static_info()
    threading.Thread(target=journal_thread, daemon=True).start()
    threading.Thread(target=services_thread, daemon=True).start()
    threading.Thread(target=hardware_thread, daemon=True).start()
    while True:
        proc = None
        try:
            ws = create_connection(WS_URL, timeout=8)
            with _WS_LOCK:
                _WS = ws
            ws_send({"op": "advertise", "topic": TOPIC, "type": "std_msgs/msg/String"})
            ws_send({"op": "advertise", "topic": LOG_TOPIC, "type": "std_msgs/msg/String"})
            ws_send({"op": "advertise", "topic": SVC_TOPIC, "type": "std_msgs/msg/String"})
            ws_send({"op": "advertise", "topic": HW_TOPIC, "type": "std_msgs/msg/String"})
            proc = subprocess.Popen(['tegrastats', '--interval', '1000'],
                                    stdout=subprocess.PIPE, text=True)
            for line in proc.stdout:
                d = parse(line)
                d.update(si)
                d.update(dynamic_info())
                d['ts'] = time.time()
                if not ws_send({"op": "publish", "topic": TOPIC,
                                "msg": {"data": json.dumps(d)}}):
                    raise IOError('websocket 断了')
        except Exception:
            with _WS_LOCK:
                _WS = None
            try: proc.kill()
            except Exception: pass
            time.sleep(3)  # 断线重连

if __name__ == '__main__':
    main()
