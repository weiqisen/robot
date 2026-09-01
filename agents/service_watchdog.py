#!/usr/bin/env python3
"""零依赖 systemd notify/watchdog 辅助。

仅在 systemd 提供 NOTIFY_SOCKET 时生效，开发机和手动运行不会产生额外依赖或线程。
看门狗心跳由 ROS 定时器调用：事件循环卡住时不会再 ping，systemd 会终止并重启服务。
"""
import os
import socket


class ServiceWatchdog:
    def __init__(self, name):
        self.name = name
        self.address = os.getenv('NOTIFY_SOCKET')
        self.enabled = bool(self.address)

    def _notify(self, payload):
        if not self.enabled:
            return
        try:
            address = self.address
            if address.startswith('@'):
                address = '\0' + address[1:]
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                sock.connect(address)
                sock.sendall(payload.encode('utf-8'))
            finally:
                sock.close()
        except Exception:
            # 不能让通知失败影响机器人主控制逻辑；systemd 自己会在超时后接管。
            pass

    def ready(self, status='运行中'):
        self._notify('READY=1\nSTATUS=%s: %s' % (self.name, status))

    def ping(self, status='运行中'):
        self._notify('WATCHDOG=1\nSTATUS=%s: %s' % (self.name, status))
