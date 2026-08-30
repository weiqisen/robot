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
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.expanduser('~/web_control')
PORT = 8000


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def end_headers(self):
        path = self.path.split('?', 1)[0]
        if path.startswith('/assets/'):
            self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
        else:
            self.send_header('Cache-Control', 'no-cache, must-revalidate')
        super().end_headers()


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
