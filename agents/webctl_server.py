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
import json
import os
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.expanduser('~/web_control')
PORT = 8000

# 数字孪生的材质/光照参数。放在 web_control 外面 —— 部署时那个目录会被
# rm -rf assets + 解包覆盖，配置放里面迟早被抹掉。
LOOK = os.path.expanduser('~/twin_look.json')
MAX_BODY = 64 * 1024        # 这份配置只有几百字节，给足余量后直接拒绝


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

    def do_GET(self):
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
        if self.path.split('?', 1)[0] != '/api/look':
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
        elif path.startswith('/assets/'):
            self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
        else:
            self.send_header('Cache-Control', 'no-cache, must-revalidate')
        super().end_headers()


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
