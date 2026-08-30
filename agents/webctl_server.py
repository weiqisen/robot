#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web_control 的静态文件服务，替代 python3 -m http.server。

只为解决一件事：http.server 一个 Cache-Control 头都不发，浏览器就按启发式
缓存自己拿主意，把 index.html 连同旧的 assets 一起缓存住。于是新包推上车了，
刷新看到的还是上一版界面，还不报错 —— 「部署了怎么没变化」就是这么来的。

规则：
  /assets/*  文件名里带内容 hash，内容一变文件名就变，可以放心长缓存；
  其余(index.html / favicon / model / fonts) 每次回源校验。
  配合 Last-Modified，没改动时走 304，并不会真的重传。

顺带换成 ThreadingHTTPServer：单线程版一个连接卡住(比如浏览器开着长连接)
就会把所有人挡在外面。
"""
import base64
import hashlib
import json
import os
import re
import select
import socket
import sqlite3
import struct
import subprocess
import tempfile
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# 都可用环境变量覆盖，方便本地起一份做联调/自测
ROOT = os.environ.get('WEBCTL_ROOT') or os.path.expanduser('~/web_control')
PORT = int(os.environ.get('WEBCTL_PORT') or 8000)

# 数字孪生的材质/光照参数。放在 web_control 外面 —— 部署时那个目录会被
# rm -rf assets + 解包覆盖，配置放里面迟早被抹掉。
LOOK = os.environ.get('WEBCTL_LOOK') or os.path.expanduser('~/twin_look.json')
MAX_BODY = 64 * 1024        # 这份配置只有几百字节，给足余量后直接拒绝

# 桌面抓屏：给数字孪生模型的屏幕当画面用。实测一帧 300~440ms、约 33KB，
# 对这台已经满载的 Jetson 不便宜，所以做最小间隔节流 + 结果缓存，
# 多个页面同时看也只抓一次。只在前端真的选了「桌面」时才会有人来拉。
DESKTOP_MIN_INTERVAL = 0.9
_desk = {'ts': 0.0, 'jpg': None}
_desk_lock = threading.Lock()

# 相机快照代理。web_video_server 在 :8080，和控制台的 :8000 不同源，
# 而它 GET 时并不发 Access-Control-Allow-Origin（HEAD 时发，很有迷惑性）。
# 前端要把画面画进 canvas 再当 WebGL 纹理，跨源图片会污染画布、上传纹理时抛
# SecurityError。所以从这里同源转发一道。width/quality 它是支持的
# （实测 width=800 约 126KB，不带参数 745KB），不用自己转码。
CAM_TOPIC = '/depth_cam/rgb/image_raw'
CAM_URL = ('http://127.0.0.1:8080/snapshot?topic=%s&width=800&quality=60' % CAM_TOPIC)
CAM_MIN_INTERVAL = 0.25

# --- VNC 桥：浏览器只能走 WebSocket，x11vnc 是裸 TCP(5900) ---
# 不依赖 x11vnc 自己有没有编进 libvncserver 的 ws 支持，也不用在车上装 websockify，
# 这里直接做一层 RFC6455 <-> TCP 转发。顺带同源(:8000)，省掉跨源那堆事。
VNC_ADDR = (os.environ.get('VNC_HOST') or '127.0.0.1', int(os.environ.get('VNC_PORT') or 5900))

# 动作组。幻尔桌面端 arm_pc 的 .d6a 其实就是 SQLite：
#   ActionGroup(Index INTEGER PK, Time INT, Servo1..Servo6 INT)
#   Servo1..5 -> 舵机 ID 1..5，Servo6 -> ID 10(夹爪)
# 直接读写这批文件，网页和桌面程序就共用同一份动作组，不用另立一套格式。
ACT_DIR = os.environ.get('ACTION_DIR') or os.path.expanduser('~/software/arm_pc/ActionGroups')
ACT_NAME = re.compile(r'^[A-Za-z0-9_\-]{1,48}$')      # 文件名白名单，挡目录穿越
ACT_COLS = ['Servo%d' % i for i in range(1, 7)]


def act_path(name):
    if not ACT_NAME.match(name or ''):
        return None
    return os.path.join(ACT_DIR, name + '.d6a')


def act_list():
    try:
        return sorted(f[:-4] for f in os.listdir(ACT_DIR) if f.endswith('.d6a'))
    except OSError:
        return []


def act_read(name):
    p = act_path(name)
    if not p or not os.path.exists(p):
        return None
    con = sqlite3.connect(p)
    try:
        # 各文件的舵机列数并不一致（有的只有 Servo1..Servo5），
        # 所以按实际表结构取列，不能写死 6 个。少的补 500(中位)。
        cols = [r[1] for r in con.execute('PRAGMA table_info(ActionGroup)')]
        sv = [c for c in cols if c.lower().startswith('servo')]
        rows = con.execute('SELECT [Index], Time%s FROM ActionGroup ORDER BY [Index]'
                           % (''.join(', ' + c for c in sv))).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        vals = [500 if v is None else int(v) for v in r[2:]]
        out.append({'index': r[0], 'time': r[1], 'servos': (vals + [500] * 6)[:6]})
    return out


def act_write(name, rows):
    p = act_path(name)
    if not p:
        return 'bad name'
    os.makedirs(ACT_DIR, exist_ok=True)
    # 整表重建：动作组通常只有几十行，比逐行 diff 简单可靠得多。
    # 先写临时库再 rename，中途出错不会毁掉原文件。
    tmp = p + '.tmp'
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    try:
        con.execute('CREATE TABLE ActionGroup([Index] INTEGER PRIMARY KEY AUTOINCREMENT '
                    'NOT NULL ON CONFLICT FAIL UNIQUE ON CONFLICT ABORT, Time INT, '
                    + ', '.join('%s INT' % c for c in ACT_COLS) + ')')
        for r in rows:
            sv = (list(r.get('servos') or [])[:6] + [500] * 6)[:6]
            con.execute('INSERT INTO ActionGroup (Time, %s) VALUES (?,?,?,?,?,?,?)' % ','.join(ACT_COLS),
                        [int(r.get('time') or 1000)] + [int(v) for v in sv])
        con.commit()
    finally:
        con.close()
    os.replace(tmp, p)
    return None
WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
_cam = {'ts': 0.0, 'jpg': None}
_cam_lock = threading.Lock()


def grab_camera():
    with _cam_lock:
        if _cam['jpg'] is not None and time.time() - _cam['ts'] < CAM_MIN_INTERVAL:
            return _cam['jpg']
        try:
            with urllib.request.urlopen(CAM_URL, timeout=5) as r:
                jpg = r.read()
            if jpg:
                _cam['jpg'] = jpg
                _cam['ts'] = time.time()
        except Exception:
            pass            # 相机没起来：保留上一帧，前端显示"无信号"
        return _cam['jpg']


def grab_desktop():
    with _desk_lock:
        if _desk['jpg'] is not None and time.time() - _desk['ts'] < DESKTOP_MIN_INTERVAL:
            return _desk['jpg']
        env = dict(os.environ, DISPLAY=':0',
                   XAUTHORITY='/run/user/%d/gdm/Xauthority' % os.getuid())
        cmd = ['ffmpeg', '-loglevel', 'error', '-f', 'x11grab', '-i', ':0',
               '-frames:v', '1', '-vf', 'scale=800:-1', '-q:v', '6', '-f', 'image2', '-']
        try:
            r = subprocess.run(cmd, capture_output=True, env=env, timeout=6)
            if r.returncode == 0 and r.stdout:
                _desk['jpg'] = r.stdout
                _desk['ts'] = time.time()
        except Exception:
            pass            # 桌面没起来 / ffmpeg 出错：保留上一帧，前端自己会显示"无信号"
        return _desk['jpg']


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    # ---- /api/look：数字孪生外观参数，存在车上，所有设备共用一份 ----
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _jpeg(self, jpg, what):
        if not jpg:
            return self._json(503, {'error': f'{what} unavailable'})
        self.send_response(200)
        self.send_header('Content-Type', 'image/jpeg')
        self.send_header('Content-Length', str(len(jpg)))
        self.end_headers()
        return self.wfile.write(jpg)

    # ---- WebSocket 帧 ----
    @staticmethod
    def _ws_frame(payload, opcode=0x2):
        """服务端发的帧不掩码。只用到二进制(0x2)和关闭(0x8)。"""
        n = len(payload)
        if n < 126:
            head = struct.pack('!BB', 0x80 | opcode, n)
        elif n < 65536:
            head = struct.pack('!BBH', 0x80 | opcode, 126, n)
        else:
            head = struct.pack('!BBQ', 0x80 | opcode, 127, n)
        return head + payload

    def _ws_read_exact(self, sock, n):
        buf = b''
        while len(buf) < n:
            c = sock.recv(n - len(buf))
            if not c:
                return None
            buf += c
        return buf

    def _ws_recv(self, sock):
        """读一帧，返回 (opcode, payload)；连接断了返回 (None, None)。"""
        h = self._ws_read_exact(sock, 2)
        if not h:
            return None, None
        b0, b1 = h[0], h[1]
        opcode = b0 & 0x0F
        masked = b1 & 0x80
        n = b1 & 0x7F
        if n == 126:
            e = self._ws_read_exact(sock, 2)
            if not e:
                return None, None
            n = struct.unpack('!H', e)[0]
        elif n == 127:
            e = self._ws_read_exact(sock, 8)
            if not e:
                return None, None
            n = struct.unpack('!Q', e)[0]
        mask = self._ws_read_exact(sock, 4) if masked else None
        if masked and mask is None:
            return None, None
        data = self._ws_read_exact(sock, n) if n else b''
        if data is None:
            return None, None
        if mask:
            data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
        return opcode, data

    def _vnc_bridge(self):
        """握手后把这条连接变成 VNC 的双向管道。"""
        key = self.headers.get('Sec-WebSocket-Key')
        if not key or 'websocket' not in (self.headers.get('Upgrade') or '').lower():
            return self._json(400, {'error': 'expected websocket upgrade'})
        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        try:
            vnc = socket.create_connection(VNC_ADDR, timeout=5)
        except Exception as e:
            return self._json(502, {'error': f'cannot reach vnc: {e}'})

        proto = (self.headers.get('Sec-WebSocket-Protocol') or '').split(',')
        proto = [p.strip() for p in proto if p.strip()]
        lines = ['HTTP/1.1 101 Switching Protocols', 'Upgrade: websocket',
                 'Connection: Upgrade', f'Sec-WebSocket-Accept: {accept}']
        if 'binary' in proto:
            lines.append('Sec-WebSocket-Protocol: binary')
        self.wfile.write(('\r\n'.join(lines) + '\r\n\r\n').encode())
        self.wfile.flush()
        self.close_connection = True      # 之后这条连接归我们，别再当 HTTP 用

        ws = self.connection
        vnc.setblocking(False)
        ws.setblocking(True)
        try:
            while True:
                r, _, _ = select.select([ws, vnc], [], [], 0.2)
                if ws in r:
                    op, data = self._ws_recv(ws)
                    if op is None or op == 0x8:
                        break
                    if op in (0x1, 0x2) and data:
                        vnc.sendall(data)
                if vnc in r:
                    try:
                        chunk = vnc.recv(65536)
                    except BlockingIOError:
                        chunk = b''
                    if chunk == b'':
                        try:
                            vnc.getpeername()
                        except OSError:
                            break
                    if chunk:
                        ws.sendall(self._ws_frame(chunk))
        except Exception:
            pass          # 掉线是常态，不值得刷日志
        finally:
            try:
                vnc.close()
            except Exception:
                pass

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/actions':
            return self._json(200, {'groups': act_list()})
        if path.startswith('/api/actions/'):
            try:
                rows = act_read(path[len('/api/actions/'):])
            except Exception as e:
                # 单个坏文件不该把整条连接打断（会表现成前端的 HTTP 000）
                return self._json(500, {'error': f'{type(e).__name__}: {e}'})
            if rows is None:
                return self._json(404, {'error': 'no such action group'})
            return self._json(200, {'rows': rows})
        if self.path.split('?', 1)[0] == '/api/vnc':
            return self._vnc_bridge()
        if self.path.split('?', 1)[0] == '/api/camera.jpg':
            return self._jpeg(grab_camera(), 'camera')
        if self.path.split('?', 1)[0] == '/api/desktop.jpg':
            return self._jpeg(grab_desktop(), 'desktop capture')
        if self.path.split('?', 1)[0] == '/api/look':
            try:
                with open(LOOK, encoding='utf-8') as f:
                    return self._json(200, json.load(f))
            except FileNotFoundError:
                return self._json(404, {'error': 'not saved yet'})
            except Exception as e:
                return self._json(500, {'error': str(e)})
        return super().do_GET()

    def do_PUT(self):
        path = self.path.split('?', 1)[0]
        if path.startswith('/api/actions/'):
            try:
                n = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(n).decode('utf-8')) if n else None
            except Exception as e:
                return self._json(400, {'error': f'bad json: {e}'})
            if not isinstance(body, dict) or not isinstance(body.get('rows'), list):
                return self._json(400, {'error': 'expected {rows: [...]}'})
            err = act_write(path[len('/api/actions/'):], body['rows'])
            return self._json(400 if err else 200, {'error': err} if err else {'ok': True})
        if path != '/api/look':
            return self._json(405, {'error': 'method not allowed'})
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY:
            return self._json(413, {'error': f'body must be 1..{MAX_BODY} bytes'})
        try:
            data = json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception as e:
            return self._json(400, {'error': f'bad json: {e}'})
        if not isinstance(data, dict):
            return self._json(400, {'error': 'expected a json object'})
        try:
            # 先写临时文件再 rename：写到一半掉电也不会留下半截坏文件
            d = os.path.dirname(LOOK) or '.'
            fd, tmp = tempfile.mkstemp(dir=d, prefix='.twin_look.')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, LOOK)
        except Exception as e:
            return self._json(500, {'error': str(e)})
        return self._json(200, {'ok': True})

    def end_headers(self):
        path = self.path.split('?', 1)[0]
        if path.startswith('/api/'):
            self.send_header('Cache-Control', 'no-store')
            # 从 Mac 的 vite dev server 打开时这些是跨源请求，没这个头
            # 图片画进 canvas 会污染画布
            self.send_header('Access-Control-Allow-Origin', '*')
        elif path.startswith('/assets/'):
            self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
        else:
            self.send_header('Cache-Control', 'no-cache, must-revalidate')
        super().end_headers()


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
