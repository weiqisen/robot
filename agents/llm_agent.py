#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
零食管家的自然语言指挥官。

把「把红色的零食收到 A 筐」这种话翻译成 snack_butler 的命令，并把执行结果讲回来。
跑在机器人上，网页 (studio-vue 的「零食管家」页) POST 到 :8092/ask。

    机器人：python3 ~/llm_agent.py        （systemd 服务 llm-agent）
    依赖：  pip3 install anthropic websocket-client
    鉴权：  export ANTHROPIC_API_KEY=...  （或 ant auth login 后留空，SDK 自己找凭据）

为什么不直接用 rclpy：这个进程只需要发一个话题、读一个话题，走 rosbridge(9090)
就不用背 ROS 环境变量那套（need_compile/HOST/MASTER），systemd 里好起，
和 jetson_agent.py / webrtc_agent.py 保持一致。

为什么用手写 tool loop 而不是 SDK 的 tool_runner：tool_runner 还是 beta，
机器人上的 anthropic 版本不一定带；手写循环没有 beta 依赖，出问题也好在日志里看。
"""
import os, sys, json, time, threading, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import websocket  # websocket-client
import anthropic

ROSBRIDGE = os.environ.get('ROSBRIDGE_URL', 'ws://127.0.0.1:9090')
PORT = int(os.environ.get('LLM_AGENT_PORT', '8092'))
MODEL = os.environ.get('LLM_MODEL', 'claude-opus-5')
EFFORT = os.environ.get('LLM_EFFORT', 'medium')      # low | medium | high | xhigh | max
MAX_TOOL_ROUNDS = 8

CMD_TOPIC = '/snack_butler/cmd'
STATE_TOPIC = '/snack_butler/state'

CN = {'red': '红', 'orange': '橙', 'yellow': '黄', 'green': '绿', 'blue': '蓝', 'purple': '紫'}


# =====================================================================
#  rosbridge 连接：订阅状态 + 发命令
# =====================================================================
class RosBridge:
    def __init__(self, url):
        self.url = url
        self.ws = None
        self.connected = False
        self.state = None
        self.state_ts = 0.0
        self._lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                self.ws = websocket.create_connection(self.url, timeout=5)
                self.ws.send(json.dumps({'op': 'subscribe', 'topic': STATE_TOPIC,
                                         'type': 'std_msgs/msg/String',
                                         'throttle_rate': 300}))
                self.connected = True
                print(f'[ros] connected {self.url}', flush=True)
                while True:
                    msg = json.loads(self.ws.recv())
                    if msg.get('topic') == STATE_TOPIC:
                        with self._lock:
                            self.state = json.loads(msg['msg']['data'])
                            self.state_ts = time.time()
            except Exception as e:
                self.connected = False
                print(f'[ros] disconnected: {e}', flush=True)
                try:
                    self.ws.close()
                except Exception:
                    pass
                time.sleep(2)

    def snapshot(self):
        with self._lock:
            if self.state is None or time.time() - self.state_ts > 5:
                return None
            return json.loads(json.dumps(self.state))

    def send_cmd(self, obj):
        if not self.connected or self.ws is None:
            return False
        try:
            self.ws.send(json.dumps({'op': 'publish', 'topic': CMD_TOPIC,
                                     'msg': {'data': json.dumps(obj, ensure_ascii=False)}}))
            return True
        except Exception as e:
            print(f'[ros] publish failed: {e}', flush=True)
            return False

    def publish(self, topic, mtype, msg):
        if not self.connected or self.ws is None:
            return False
        try:
            self.ws.send(json.dumps({'op': 'publish', 'topic': topic, 'msg': msg}))
            return True
        except Exception:
            return False


ros = RosBridge(ROSBRIDGE)


# =====================================================================
#  给模型用的工具
# =====================================================================
def _summarize(st):
    """把节点状态压成模型好读的一小段"""
    if not st:
        return {'online': False, 'note': 'snack_butler 节点没在跑或没数据'}
    seen = []
    for d in st.get('detections', []):
        seen.append({'颜色': CN.get(d['label'], d['label']), 'label': d['label'],
                     '坐标': d.get('xyz'), '能抓到': bool(d.get('reachable')),
                     '定位方式': d.get('depth_src')})
    return {
        'online': True,
        '状态': st.get('state'), '当前动作': st.get('step'), '自动模式': st.get('auto'),
        '桌面上看到的': seen,
        '已抓取件数': st.get('stats', {}).get('picked'),
        '失败次数': st.get('stats', {}).get('failed'),
        '舵机已标定': st.get('calibrated'),
        '分拣规则': st.get('cfg', {}).get('route'),
        '投放区': {k: v.get('label', k) for k, v in (st.get('cfg', {}).get('bins') or {}).items()},
        '最近错误': st.get('error') or None,
    }


def _wait_state(pred, timeout=25.0, poll=0.3):
    end = time.time() + timeout
    while time.time() < end:
        st = ros.snapshot()
        if st and pred(st):
            return st
        time.sleep(poll)
    return ros.snapshot()


# 本轮对话实际下发过的命令，回给网页展示。
# 用 thread-local：ThreadingHTTPServer 可能同时处理多个 /ask，模块级列表会串台。
_tls = threading.local()


def _log_cmd(obj):
    getattr(_tls, 'executed', []).append(obj)


def _cmd(obj):
    ok = ros.send_cmd(obj)
    _log_cmd(obj)
    return ok


def t_get_status(_):
    return _summarize(ros.snapshot())


def t_look(_):
    """让机器人回观察位重新看一眼桌面"""
    if not _cmd({'action': 'detect'}):
        return {'error': 'rosbridge 没连上，命令没发出去'}
    st = _wait_state(lambda s: s.get('state') == 'DETECT' and '识别到' in (s.get('step') or ''),
                     timeout=20)
    return _summarize(st)


def t_pick(inp):
    color = inp.get('color')
    st = ros.snapshot()
    if color and st:
        avail = {d['label'] for d in st.get('detections', []) if d.get('reachable')}
        if avail and color not in avail:
            return {'没抓': f'桌面上现在没有能抓到的{CN.get(color, color)}色零食',
                    '现在有的': sorted(CN.get(c, c) for c in avail)}
    if not _cmd({'action': 'pick', 'label': color} if color else {'action': 'pick'}):
        return {'error': 'rosbridge 没连上'}
    st = _wait_state(lambda s: s.get('state') in ('IDLE', 'ERROR') and not s.get('auto'),
                     timeout=45)
    return {'结果': (st or {}).get('step'), '状态': _summarize(st)}


def t_tidy_all(inp):
    on = inp.get('on', True)
    if not _cmd({'action': 'auto', 'on': bool(on)}):
        return {'error': 'rosbridge 没连上'}
    if not on:
        return {'ok': '自动整理已关闭'}
    return {'ok': '已开始自动整理，会一直抓到桌面清空为止；期间可以叫我停下'}


def t_stop(_):
    _cmd({'action': 'stop'})
    return {'ok': '已停止，机械臂停在当前姿态'}


def t_move_arm(inp):
    where = inp.get('where')
    if where not in ('observe', 'home'):
        return {'error': "where 只能是 observe（观察位）或 home（收臂）"}
    _cmd({'action': where})
    return {'ok': '已回观察位' if where == 'observe' else '已收臂'}


def t_gripper(inp):
    op = bool(inp.get('open', True))
    _cmd({'action': 'gripper', 'open': op})
    return {'ok': '夹爪已张开' if op else '夹爪已闭合'}


def t_set_route(inp):
    color, bin_ = inp.get('color'), inp.get('bin')
    if not color or not bin_:
        return {'error': '需要 color 和 bin'}
    _cmd({'action': 'set_config', 'patch': {'route': {color: bin_}}})
    return {'ok': f'{CN.get(color, color)}色以后放到 {bin_} 筐'}


def t_drive(inp):
    """小幅挪一下车身。速度和时长都硬性夹住，避免模型一个手滑把车开走。"""
    vx = max(-0.15, min(0.15, float(inp.get('vx', 0))))
    vy = max(-0.15, min(0.15, float(inp.get('vy', 0))))
    wz = max(-0.8, min(0.8, float(inp.get('wz', 0))))
    sec = max(0.0, min(2.0, float(inp.get('seconds', 0.5))))
    end = time.time() + sec
    while time.time() < end:
        ros.publish('/cmd_vel', 'geometry_msgs/msg/Twist',
                    {'linear': {'x': vx, 'y': vy, 'z': 0.0},
                     'angular': {'x': 0.0, 'y': 0.0, 'z': wz}})
        time.sleep(0.1)
    ros.publish('/cmd_vel', 'geometry_msgs/msg/Twist',
                {'linear': {'x': 0.0, 'y': 0.0, 'z': 0.0},
                 'angular': {'x': 0.0, 'y': 0.0, 'z': 0.0}})
    _log_cmd({'action': 'drive', 'vx': vx, 'vy': vy, 'wz': wz, 'seconds': sec})
    return {'ok': f'挪动了 {sec:.1f} 秒 (vx={vx}, vy={vy}, wz={wz})'}


def t_say(inp):
    text = str(inp.get('text', ''))[:32]
    ros.publish('/ros_robot_controller/set_oled', 'ros_robot_controller_msgs/msg/OLEDState',
                {'index': 1, 'text': text})
    ros.publish('/ros_robot_controller/set_buzzer', 'ros_robot_controller_msgs/msg/BuzzerState',
                {'freq': 1800, 'on_time': 0.08, 'off_time': 0.05, 'repeat': 1})
    _log_cmd({'action': 'say', 'text': text})
    return {'ok': f'OLED 上显示了「{text}」'}


TOOLS = [
    {'name': 'get_status', 'description': '读当前状态：机器人在做什么、桌面上识别到哪些零食及其坐标、'
                                          '已抓几件、分拣规则。不会让机器人动。回答「桌上有什么」先用这个。',
     'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
    {'name': 'look', 'description': '让机械臂回到观察位、重新识别一次桌面，返回最新结果。'
                                    'get_status 的数据太旧或用户说「再看看」时用。会让机械臂动。',
     'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
    {'name': 'pick', 'description': '抓一个零食放到它对应的投放筐。不给 color 就抓最近的那个。'
                                    '这一步会等动作做完（最多 45 秒）。',
     'input_schema': {'type': 'object', 'properties': {
         'color': {'type': 'string', 'enum': list(CN.keys()),
                   'description': '要抓的零食颜色；不填=随便抓最近的一个'}},
         'additionalProperties': False}},
    {'name': 'tidy_all', 'description': '自动整理模式：一直抓到桌面上没有可抓的零食为止。'
                                        '用户说「把桌子收拾干净」用这个。on=false 关掉。',
     'input_schema': {'type': 'object', 'properties': {'on': {'type': 'boolean'}},
                      'additionalProperties': False}},
    {'name': 'stop', 'description': '立即停止当前动作并退出自动模式。',
     'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
    {'name': 'move_arm', 'description': '把机械臂摆到固定姿态：observe=观察位（能看到桌面），home=收起来。',
     'input_schema': {'type': 'object', 'properties': {
         'where': {'type': 'string', 'enum': ['observe', 'home']}},
         'required': ['where'], 'additionalProperties': False}},
    {'name': 'gripper', 'description': '单独开合夹爪。',
     'input_schema': {'type': 'object', 'properties': {'open': {'type': 'boolean'}},
                      'required': ['open'], 'additionalProperties': False}},
    {'name': 'set_route', 'description': '改分拣规则：某个颜色以后放进哪个筐。',
     'input_schema': {'type': 'object', 'properties': {
         'color': {'type': 'string', 'enum': list(CN.keys())},
         'bin': {'type': 'string', 'description': '筐的名字，通常是 A 或 B'}},
         'required': ['color', 'bin'], 'additionalProperties': False}},
    {'name': 'drive', 'description': '让底盘小幅移动（麦克纳姆轮，可横move）。vx 前后、vy 左右、wz 转。'
                                     '速度和时间都被限死在很小的范围，只够微调位置。',
     'input_schema': {'type': 'object', 'properties': {
         'vx': {'type': 'number', 'description': 'm/s, 前正后负, 限 ±0.15'},
         'vy': {'type': 'number', 'description': 'm/s, 左正右负, 限 ±0.15'},
         'wz': {'type': 'number', 'description': 'rad/s, 左转正, 限 ±0.8'},
         'seconds': {'type': 'number', 'description': '持续秒数, 限 0~2'}},
         'additionalProperties': False}},
    {'name': 'say', 'description': '在机器人的 OLED 小屏上显示一句话并响一声。最多 32 个字符。',
     'input_schema': {'type': 'object', 'properties': {'text': {'type': 'string'}},
                      'required': ['text'], 'additionalProperties': False}},
]

HANDLERS = {'get_status': t_get_status, 'look': t_look, 'pick': t_pick, 'tidy_all': t_tidy_all,
            'stop': t_stop, 'move_arm': t_move_arm, 'gripper': t_gripper,
            'set_route': t_set_route, 'drive': t_drive, 'say': t_say}

SYSTEM = """你是一台幻尔 JetRover 机器人的大脑。它是一台带麦克纳姆轮底盘、5 轴机械臂和深度相机的桌面机器人，
正在当「零食管家」：识别桌上的零食，用机械臂抓起来分类放进筐里。

规则：
- 用中文回答，口语化、简短（一般一两句话）。你是在跟站在机器人旁边的人说话。
- 想知道现在什么情况，先调 get_status，别猜。数据看着过期或用户让你再看一眼，就调 look。
- 用户让你干活就直接调工具，别问「要我现在做吗」。但要是指令真的有歧义（比如说了个桌上没有的颜色），
  先说清楚情况再问。
- 机械臂只能够到身前一小块桌面（大约正前方 15~30 厘米）。工具告诉你某个零食「能抓到=false」时，
  如实说够不着，可以建议把它往机器人跟前推一推，或者用 drive 挪一下车。
- 动作做完后，用工具返回的实际结果说话，不要编造成功。失败了就直说哪一步失败。
- 安全：任何时候用户说停、别动、危险，立刻调 stop，别先解释。
- 不要一次调一大堆工具。先想清楚最少要几步。"""


class Brain:
    def __init__(self):
        self.client = anthropic.Anthropic()
        self.use_fallbacks = True          # Opus 5 的服务端 refusal 兜底；组织没开通就自动关掉

    def _create(self, **kw):
        if self.use_fallbacks:
            try:
                return self.client.beta.messages.create(
                    betas=['server-side-fallback-2026-07-01'], fallbacks='default', **kw)
            except (anthropic.BadRequestError, TypeError, AttributeError) as e:
                print(f'[llm] 服务端 fallback 不可用，退回普通请求: {e}', flush=True)
                self.use_fallbacks = False
        return self.client.messages.create(**kw)

    def ask(self, text, ui_state=None):
        _tls.executed = executed = []
        ctx = _summarize(ros.snapshot() or ui_state)
        messages = [{'role': 'user', 'content':
                     f'【当前机器人状态】\n{json.dumps(ctx, ensure_ascii=False)}\n\n【用户说】\n{text}'}]
        reply = ''
        for _ in range(MAX_TOOL_ROUNDS):
            r = self._create(model=MODEL, max_tokens=8000, system=SYSTEM, tools=TOOLS,
                             thinking={'type': 'adaptive'},
                             output_config={'effort': EFFORT},
                             messages=messages)
            if r.stop_reason == 'refusal':
                cat = getattr(getattr(r, 'stop_details', None), 'category', None)
                return {'reply': f'这个请求我没法处理（{cat or "safety"}）。', 'commands': executed}
            reply = ''.join(b.text for b in r.content if b.type == 'text').strip()
            uses = [b for b in r.content if b.type == 'tool_use']
            if r.stop_reason == 'end_turn' or not uses:
                break
            messages.append({'role': 'assistant', 'content': r.content})
            results = []
            for b in uses:
                try:
                    out = HANDLERS[b.name](b.input or {})
                    err = isinstance(out, dict) and 'error' in out
                except Exception as e:
                    out, err = {'error': f'{type(e).__name__}: {e}'}, True
                    traceback.print_exc()
                print(f'[tool] {b.name}({b.input}) -> {out}', flush=True)
                results.append({'type': 'tool_result', 'tool_use_id': b.id,
                                'content': json.dumps(out, ensure_ascii=False),
                                **({'is_error': True} if err else {})})
            messages.append({'role': 'user', 'content': results})
        return {'reply': reply or '(没说话)', 'commands': executed}


brain = None


# =====================================================================
#  HTTP
# =====================================================================
class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        if self.path.startswith('/health'):
            return self._json(200, {'ok': True, 'rosbridge': ros.connected,
                                    'butler': ros.snapshot() is not None, 'model': MODEL})
        self._json(404, {'error': 'not found'})

    def do_POST(self):
        if not self.path.startswith('/ask'):
            return self._json(404, {'error': 'not found'})
        try:
            n = int(self.headers.get('Content-Length', 0))
            req = json.loads(self.rfile.read(n) or b'{}')
        except Exception as e:
            return self._json(400, {'error': f'bad json: {e}'})
        text = (req.get('text') or '').strip()
        if not text:
            return self._json(400, {'error': 'text 为空'})
        try:
            return self._json(200, brain.ask(text, req.get('state')))
        except anthropic.AuthenticationError:
            return self._json(500, {'reply': 'ANTHROPIC_API_KEY 没配对，机器人上 export 一下再重启服务。',
                                    'commands': []})
        except anthropic.APIConnectionError as e:
            return self._json(500, {'reply': f'连不上 Claude API（机器人能上外网吗）：{e}', 'commands': []})
        except Exception as e:
            traceback.print_exc()
            return self._json(500, {'reply': f'出错了：{type(e).__name__}: {e}', 'commands': []})

    def log_message(self, *a):
        pass


def main():
    global brain
    try:
        brain = Brain()
    except Exception as e:
        print(f'anthropic 客户端初始化失败（先 export ANTHROPIC_API_KEY 或 ant auth login）: {e}')
        sys.exit(1)
    print(f'[llm_agent] :{PORT}  model={MODEL} effort={EFFORT}  rosbridge={ROSBRIDGE}', flush=True)
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()


if __name__ == '__main__':
    main()
