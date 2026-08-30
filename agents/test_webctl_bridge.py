"""本地自测 webctl_server 的 VNC WebSocket 桥：
起一个假 VNC(TCP) + 真的 webctl_server，用最小 WebSocket 客户端跑一遍握手和双向收发。"""
import base64, hashlib, os, socket, struct, subprocess, sys, threading, time

SC = os.path.dirname(os.path.abspath(__file__))   # webctl_server.py 就在同目录
VNC_PORT, WEB_PORT = 59001, 58001
GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
got_from_client = []

def fake_vnc():
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', VNC_PORT)); srv.listen(1)
    c, _ = srv.accept()
    c.sendall(b'RFB 003.008\n')          # 真实 VNC 一连上就发版本串
    while True:
        d = c.recv(4096)
        if not d: break
        got_from_client.append(d)
        c.sendall(b'ECHO:' + d)          # 回一个可辨认的响应

threading.Thread(target=fake_vnc, daemon=True).start()

env = dict(os.environ, WEBCTL_PORT=str(WEB_PORT), VNC_PORT=str(VNC_PORT),
           WEBCTL_ROOT=SC, WEBCTL_LOOK=os.path.join(SC, 'look_test.json'))
srv = subprocess.Popen([sys.executable, os.path.join(SC, 'webctl_server.py')],
                       env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(1.2)

def ws_frame(payload, opcode=0x2):
    mask = b'\xaa\xbb\xcc\xdd'
    n = len(payload)
    head = struct.pack('!BB', 0x80 | opcode, 0x80 | n) if n < 126 else \
           struct.pack('!BBH', 0x80 | opcode, 0x80 | 126, n)
    return head + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(payload))

def ws_read(sock):
    h = sock.recv(2)
    if len(h) < 2: return None, None
    op = h[0] & 0x0F; n = h[1] & 0x7F
    if n == 126: n = struct.unpack('!H', sock.recv(2))[0]
    elif n == 127: n = struct.unpack('!Q', sock.recv(8))[0]
    buf = b''
    while len(buf) < n:
        c = sock.recv(n - len(buf))
        if not c: break
        buf += c
    return op, buf

fails = []
try:
    key = base64.b64encode(os.urandom(16)).decode()
    s = socket.create_connection(('127.0.0.1', WEB_PORT), timeout=5)
    s.sendall((f'GET /api/vnc HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n'
               f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n'
               f'Sec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: binary\r\n\r\n').encode())
    time.sleep(0.6)
    resp = s.recv(4096).decode('latin1')
    head, _, rest = resp.partition('\r\n\r\n')
    want = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()

    print('1) 握手状态行:', head.split('\r\n')[0])
    if '101' not in head: fails.append('没有返回 101')
    if want not in head: fails.append('Sec-WebSocket-Accept 不对')
    else: print('   Accept 校验通过')
    if 'Sec-WebSocket-Protocol: binary' not in head: fails.append('没回 binary 子协议')
    else: print('   binary 子协议已回')

    s.settimeout(3)
    # 握手响应可能和第一帧粘在一起
    if rest:
        data = rest.encode('latin1')
        op, n = data[0] & 0x0F, data[1] & 0x7F
        banner = data[2:2 + n]
    else:
        op, banner = ws_read(s)
    print('2) VNC 版本串:', banner, ' opcode=', hex(op))
    if banner != b'RFB 003.008\n': fails.append(f'版本串不对: {banner!r}')
    if op != 0x2: fails.append(f'应为二进制帧 0x2，实际 {hex(op)}')

    s.sendall(ws_frame(b'HELLO-FROM-BROWSER'))
    time.sleep(0.6)
    print('3) 假 VNC 收到:', got_from_client)
    if b'HELLO-FROM-BROWSER' not in b''.join(got_from_client): fails.append('上行没送到 VNC')
    op2, echo = ws_read(s)
    print('4) 回程:', echo, ' opcode=', hex(op2))
    if echo != b'ECHO:HELLO-FROM-BROWSER': fails.append(f'下行不对: {echo!r}')

    s.sendall(ws_frame(b'', 0x8))     # 关闭帧
    time.sleep(0.4)
    print('5) 关闭帧已发，桥应已收尾')
finally:
    srv.terminate()
    out, errout = srv.communicate(timeout=5)
    if errout.strip(): print('服务端 stderr:', errout.decode()[:400])

print()
print('全部通过 ✓' if not fails else '失败:\n  ' + '\n  '.join(fails))
sys.exit(1 if fails else 0)
