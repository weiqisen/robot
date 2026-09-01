# -*- coding: utf-8 -*-
"""从一份结构模板生成浅色/暗色两块画板 —— 结构完全相同，只换 token，
这本身就是「一套语言、两套色板」的证明。"""
import os

FONTS = ('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
         '  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+SC:wght@400;500;600'
         '&family=Inter:wght@400;500;600;700'
         '&family=IBM+Plex+Mono:wght@400;500;600&display=swap">')

SANS = "Inter, -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif"
# 数字也走 Inter —— 它自带 tabular figures，配 font-variant-numeric 就能对齐，
# 于是整站只需要自托管这一个字族（中文本来就回退到系统字体，Inter 没有中文）
MONO = SANS

LIGHT = dict(
    name='light', label='浅色',
    bg='#F1F4F8', surface='#FFFFFF', surface2='#F6F8FA', border='#E2E8F0', divider='#EDF1F5',
    t1='#0F172A', t2='#334155', t3='#64748B', t4='#94A3B8',
    accent='#0284C7', accentSoft='rgba(2,132,199,.10)',
    ok='#0D9488', warn='#CA8A04', bad='#E11D48',
    okSoft='rgba(13,148,136,.10)', warnSoft='rgba(202,138,4,.12)', badSoft='rgba(225,29,72,.10)',
    grid='#EDF1F5', shadow='0 1px 2px rgba(15,23,42,.05), 0 1px 1px rgba(15,23,42,.03)',
)
DARK = dict(
    name='dark', label='暗色',
    bg='#080B12', surface='#0E1219', surface2='#12171F', border='rgba(255,255,255,.08)',
    divider='rgba(255,255,255,.06)',
    t1='#F1F5F9', t2='#CBD5E1', t3='#94A3B8', t4='#64748B',
    accent='#38BDF8', accentSoft='rgba(56,189,248,.12)',
    ok='#34D399', warn='#F59E0B', bad='#F43F5E',
    okSoft='rgba(52,211,153,.12)', warnSoft='rgba(245,158,11,.14)', badSoft='rgba(244,63,94,.12)',
    grid='rgba(255,255,255,.05)', shadow='none',
)

ICONS = {
 'gauge': '<path d="M3 13a9 9 0 0 1 18 0"/><path d="M12 13l4-3"/>',
 'chart': '<path d="M4 19V5"/><path d="M4 19h16"/><path d="M8 15l3-4 3 2 4-6"/>',
 'arm':   '<path d="M5 20h5"/><path d="M7.5 20V9"/><path d="M7.5 9l7-3"/><path d="M14.5 6l4 4"/>',
 'radar': '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.2"/><path d="M12 12l5-4"/>',
 'chip':  '<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M10 4v3M14 4v3M10 17v3M14 17v3M4 10h3M4 14h3M17 10h3M17 14h3"/>',
 'map':   '<path d="M9 5 3 7v12l6-2 6 2 6-2V5l-6 2z"/><path d="M9 5v12M15 7v12"/>',
 'scan':  '<path d="M4 8V5h3M20 8V5h-3M4 16v3h3M20 16v3h-3"/><circle cx="12" cy="12" r="3"/>',
 'box':   '<path d="M4 8l8-4 8 4v8l-8 4-8-4z"/><path d="M4 8l8 4 8-4M12 12v8"/>',
 'node':  '<circle cx="6" cy="6" r="2.2"/><circle cx="18" cy="6" r="2.2"/><circle cx="12" cy="18" r="2.2"/><path d="M7.6 7.6 11 15.6M16.4 7.6 13 15.6M8.2 6h7.6"/>',
 'list':  '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
 'search':'<circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/>',
 'pad':   '<rect x="3" y="7" width="18" height="10" rx="3"/><path d="M8 12h-.01M11 12h-.01M16 11v2M15 12h2"/>',
 'cube':  '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
}

MENU = [
    ('big',  'gauge', '监控大屏', None),
    (None, None, '监控', 'group'),
    ('ov',   'chart', '概览', 'active'),
    ('tel',  'chart', '遥测数据', None),
    ('arm',  'arm',   '机械臂舵机', None),
    ('sen',  'radar', '传感器', None),
    ('jet',  'chip',  'Jetson 硬件', None),
    (None, None, '感知 · 导航', 'group'),
    ('nav',  'map',   '导航建图', None),
    ('det',  'scan',  '目标检测', None),
    ('snk',  'box',   '视觉抓取', None),
    (None, None, 'ROS 系统', 'group'),
    ('sys',  'node',  '节点 · 服务', None),
    ('top',  'list',  '话题总览', None),
    ('exp',  'search','话题浏览器', None),
    (None, None, '操作', 'group'),
    ('ctl',  'pad',   '实时控制', None),
    ('twin', 'cube',  '数字孪生', None),
]

# 侧栏在两个主题下都是深色 —— 用户明确说过深色侧栏不动
SIDE_BG, SIDE_T, SIDE_T2, SIDE_GROUP = '#0B0F17', '#E2E8F0', '#8A98AC', '#5B6舒'
SIDE_GROUP = '#5B6A7E'


def icon(name, color, size=16, sw=1.6):
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{sw}" stroke-linecap="round" '
            f'stroke-linejoin="round" style="flex-shrink:0">{ICONS[name]}</svg>')


def sider(T, accent):
    rows = []
    for key, ic, label, kind in MENU:
        if kind == 'group':
            rows.append(
                f'<div style="font-size:10px;letter-spacing:1.6px;color:{SIDE_GROUP};'
                f'text-transform:uppercase;padding:14px 20px 6px;font-weight:500">{label}</div>')
            continue
        on = kind == 'active'
        bg = f'background:{accent};' if on else ''
        col = '#FFFFFF' if on else SIDE_T2
        weight = '500' if on else '400'
        rows.append(
            f'<div style="display:flex;align-items:center;gap:10px;padding:0 20px;height:34px;'
            f'{bg}color:{col};font-size:13px;font-weight:{weight};border-radius:0">'
            f'{icon(ic, col)}<span>{label}</span></div>')
    return (
      f'<div style="width:224px;flex-shrink:0;background:{SIDE_BG};display:flex;'
      f'flex-direction:column;border-right:1px solid rgba(255,255,255,.06)">'
      f'<div style="height:52px;display:flex;align-items:center;gap:10px;padding:0 20px;'
      f'border-bottom:1px solid rgba(255,255,255,.05)">'
      f'<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="{accent}" '
      f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
      f'<rect x="4" y="7" width="16" height="12" rx="3"/><path d="M9 12h.01M15 12h.01'
      f'M10 16h4M12 7V4"/></svg>'
      f'<span style="color:{SIDE_T};font-size:14px;font-weight:600;letter-spacing:.2px">'
      f'JetRover <span style="color:{accent}">管理系统</span></span></div>'
      f'<div style="flex:1;padding-top:4px;overflow:hidden">{"".join(rows)}</div>'
      f'<div style="padding:12px 20px;font:400 10px/1.7 {MONO};color:#465468">'
      f'rosbridge<br>192.168.3.63:9090</div></div>')


def topbar(T):
    return (
      f'<div style="height:52px;flex-shrink:0;display:flex;align-items:center;gap:12px;'
      f'padding:0 16px;background:{T["surface"]};border-bottom:1px solid {T["border"]}">'
      f'{icon("list", T["t3"], 18)}'
      f'<span style="font-size:15px;font-weight:600;color:{T["t1"]}">概览</span>'
      f'<span style="font:400 12px/1 {MONO};color:{T["t4"]}">/ overview</span>'
      f'<div style="margin-left:auto;display:flex;align-items:center;gap:10px">'
      f'{theme_switch(T)}'
      f'{pill("链路正常", T["ok"], T["okSoft"], dot=True)}'
      f'<span style="font:500 13px/1 {MONO};color:{T["t2"]};font-variant-numeric:tabular-nums">'
      f'11.74<span style="font-size:.72em;color:{T["t3"]};margin-left:2px">V</span>'
      f'<span style="color:{T["t4"]};margin:0 6px">·</span>'
      f'76<span style="font-size:.72em;color:{T["t3"]};margin-left:2px">%</span></span>'
      f'</div></div>')


def theme_switch(T):
    dark = T['name'] == 'dark'
    sun = ('<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2'
           'M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4"/>')
    moon = '<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a6.8 6.8 0 0 0 10.5 10.5z"/>'
    onc, offc = T['accent'], T['t4']
    return (f'<div style="display:flex;align-items:center;gap:2px;padding:2px;border-radius:7px;'
            f'background:{T["surface2"]};border:1px solid {T["border"]}">'
            + ''.join(
              f'<div style="width:26px;height:22px;display:flex;align-items:center;'
              f'justify-content:center;border-radius:5px;'
              + (f'background:{T["accentSoft"]};' if sel else '') + '">'
              + f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
                f'stroke="{onc if sel else offc}" stroke-width="1.7" stroke-linecap="round" '
                f'stroke-linejoin="round">{p}</svg></div>'
              for p, sel in ((sun, not dark), (moon, dark)))
            + '</div>')


def pill(text, color, soft, dot=False):
    d = (f'<span style="width:6px;height:6px;border-radius:50%;background:{color};'
         f'display:inline-block"></span>') if dot else ''
    return (f'<span style="display:inline-flex;align-items:center;gap:6px;height:22px;'
            f'padding:0 8px;border-radius:5px;background:{soft};color:{color};'
            f'font-size:12px;font-weight:500">{d}{text}</span>')


def card(T, title, extra, body, pad='12px 14px 14px', grow=False):
    head = ''
    if title:
        ex = (f'<span style="margin-left:auto;font:500 10px/1 {MONO};letter-spacing:1.4px;'
              f'color:{T["t4"]};text-transform:uppercase">{extra}</span>') if extra else ''
        head = (f'<div style="display:flex;align-items:center;gap:8px;padding:0 14px;height:38px;'
                f'border-bottom:1px solid {T["divider"]}">'
                f'<span style="width:3px;height:12px;border-radius:2px;background:{T["accent"]}">'
                f'</span><span style="font-size:13px;font-weight:600;color:{T["t1"]}">{title}</span>'
                f'{ex}</div>')
    g = 'flex:1;min-height:0;' if grow else ''
    return (f'<div style="{g}background:{T["surface"]};border:1px solid {T["border"]};'
            f'border-radius:10px;box-shadow:{T["shadow"]};display:flex;flex-direction:column;'
            f'overflow:hidden">{head}'
            f'<div style="padding:{pad};flex:1;min-height:0">{body}</div></div>')


def num(T, value, unit, size=22, color=None):
    return (f'<span style="font:600 {size}px/1 {MONO};color:{color or T["t1"]};'
            f'font-variant-numeric:tabular-nums;letter-spacing:-.3px">{value}'
            f'<span style="font-size:.72em;font-weight:400;color:{T["t3"]};margin-left:3px">'
            f'{unit}</span></span>')


def ring(T, pct, color):
    r, c = 26, 2 * 3.14159 * 26
    off = c * (1 - pct / 100)
    return (f'<svg width="64" height="64" viewBox="0 0 64 64" style="flex-shrink:0">'
            f'<circle cx="32" cy="32" r="{r}" fill="none" stroke="{T["surface2"]}" '
            f'stroke-width="5"/>'
            f'<circle cx="32" cy="32" r="{r}" fill="none" stroke="{color}" stroke-width="5" '
            f'stroke-linecap="round" stroke-dasharray="{c:.1f}" stroke-dashoffset="{off:.1f}" '
            f'transform="rotate(-90 32 32)"/>'
            f'<text x="32" y="34" text-anchor="middle" '
            f'style="font:600 17px {MONO};fill:{T["t1"]}">{pct}</text>'
            f'<text x="32" y="45" text-anchor="middle" '
            f'style="font:400 8px {MONO};fill:{T["t4"]};letter-spacing:1px">%</text></svg>')


# ---------- 遥测小倍数（每格一个序列、一条轴、自带标题）----------
SPARK = {
 'volt': ("M 4.0 16.7 L 8.9 16.7 L 13.9 16.4 L 18.8 16.5 L 23.8 16.6 L 28.7 16.6 L 33.7 17.0 L 38.6 17.1 L 43.6 17.0 L 48.5 16.8 L 53.5 17.4 L 58.4 17.7 L 63.4 18.2 L 68.3 18.0 L 73.3 17.8 L 78.2 18.4 L 83.2 18.0 L 88.1 17.6 L 93.1 17.5 L 98.0 17.5 L 103.0 17.9 L 107.9 18.6 L 112.9 18.6 L 117.8 19.2 L 122.8 19.6 L 127.7 20.0 L 132.7 20.6 L 137.6 20.7 L 142.6 20.9 L 147.5 20.6 L 152.5 20.7 L 157.4 20.6 L 162.4 20.7 L 167.3 20.6 L 172.3 20.8 L 177.2 21.1 L 182.2 20.7 L 187.1 20.2 L 192.1 19.9 L 197.0 19.8 L 202.0 20.1 L 206.9 20.5 L 211.9 20.8 L 216.8 21.4 L 221.8 21.2 L 226.7 21.4 L 231.7 21.1 L 236.6 21.3 L 241.6 20.9 L 246.5 20.6 L 251.5 21.3 L 256.4 21.7 L 261.4 21.3 L 266.3 21.4 L 271.3 21.0 L 276.2 21.2 L 281.2 21.8 L 286.1 21.7 L 291.1 21.5 L 296.0 21.9", 21.9),
 'cpu': ("M 4.0 49.1 L 8.9 50.7 L 13.9 46.0 L 18.8 43.3 L 23.8 47.1 L 28.7 49.6 L 33.7 53.6 L 38.6 57.9 L 43.6 54.9 L 48.5 58.1 L 53.5 57.4 L 58.4 57.9 L 63.4 61.0 L 68.3 58.6 L 73.3 61.8 L 78.2 60.3 L 83.2 61.8 L 88.1 61.8 L 93.1 61.8 L 98.0 61.8 L 103.0 57.0 L 107.9 53.8 L 112.9 55.8 L 117.8 51.8 L 122.8 54.7 L 127.7 55.7 L 132.7 52.1 L 137.6 50.6 L 142.6 54.6 L 147.5 49.6 L 152.5 52.4 L 157.4 54.8 L 162.4 52.0 L 167.3 53.6 L 172.3 55.6 L 177.2 59.9 L 182.2 61.8 L 187.1 60.9 L 192.1 61.8 L 197.0 60.7 L 202.0 61.8 L 206.9 61.8 L 211.9 57.1 L 216.8 57.2 L 221.8 56.4 L 226.7 52.6 L 231.7 55.8 L 236.6 59.2 L 241.6 55.0 L 246.5 51.8 L 251.5 54.2 L 256.4 57.3 L 261.4 54.8 L 266.3 50.3 L 271.3 53.3 L 276.2 48.7 L 281.2 44.8 L 286.1 43.7 L 291.1 44.5 L 296.0 48.4", 48.4),
 'gpu': ("M 4.0 59.5 L 8.9 53.7 L 13.9 56.8 L 18.8 54.1 L 23.8 57.0 L 28.7 52.9 L 33.7 51.6 L 38.6 54.0 L 43.6 57.9 L 48.5 55.0 L 53.5 60.2 L 58.4 61.8 L 63.4 60.9 L 68.3 56.4 L 73.3 54.9 L 78.2 57.5 L 83.2 52.2 L 88.1 55.8 L 93.1 61.6 L 98.0 61.8 L 103.0 61.8 L 107.9 61.8 L 112.9 61.8 L 117.8 61.8 L 122.8 60.7 L 127.7 61.8 L 132.7 61.8 L 137.6 56.8 L 142.6 50.8 L 147.5 48.7 L 152.5 46.2 L 157.4 45.1 L 162.4 49.4 L 167.3 55.0 L 172.3 60.8 L 177.2 55.6 L 182.2 53.0 L 187.1 47.2 L 192.1 53.0 L 197.0 51.2 L 202.0 51.3 L 206.9 48.3 L 211.9 50.4 L 216.8 44.1 L 221.8 49.3 L 226.7 48.6 L 231.7 45.5 L 236.6 40.5 L 241.6 37.4 L 246.5 34.8 L 251.5 31.1 L 256.4 25.8 L 261.4 27.5 L 266.3 25.1 L 271.3 20.1 L 276.2 15.4 L 281.2 16.3 L 286.1 12.6 L 291.1 10.2 L 296.0 10.2", 10.2),
 'temp': ("M 4.0 38.0 L 8.9 38.2 L 13.9 37.8 L 18.8 37.4 L 23.8 38.4 L 28.7 37.9 L 33.7 36.6 L 38.6 35.5 L 43.6 34.8 L 48.5 35.0 L 53.5 34.2 L 58.4 33.9 L 63.4 34.0 L 68.3 33.0 L 73.3 33.9 L 78.2 33.2 L 83.2 34.3 L 88.1 33.9 L 93.1 33.8 L 98.0 34.4 L 103.0 33.8 L 107.9 33.7 L 112.9 33.3 L 117.8 32.1 L 122.8 32.6 L 127.7 33.8 L 132.7 34.2 L 137.6 33.6 L 142.6 34.2 L 147.5 35.0 L 152.5 33.8 L 157.4 33.3 L 162.4 33.3 L 167.3 32.2 L 172.3 32.5 L 177.2 32.0 L 182.2 32.7 L 187.1 32.7 L 192.1 31.8 L 197.0 30.7 L 202.0 29.6 L 206.9 29.8 L 211.9 29.4 L 216.8 29.8 L 221.8 30.6 L 226.7 30.5 L 231.7 29.5 L 236.6 28.5 L 241.6 27.9 L 246.5 26.6 L 251.5 27.1 L 256.4 27.8 L 261.4 27.8 L 266.3 28.3 L 271.3 28.9 L 276.2 29.0 L 281.2 28.6 L 286.1 28.5 L 291.1 28.9 L 296.0 27.9", 27.9),
}

# key, 标题, 当前值, 单位, 轴下限, 轴上限, 阈值说明, 状态 ('ok'|'warn'|'bad')
PANELS = [
    ('volt', '电池电压', '11.71', 'V',  '9.0',  '12.6', '低压阈值 10.0 V', 'ok'),
    ('cpu',  'CPU 负载', '27.8',  '%',  '0',    '100',  '告警阈值 90 %',   'ok'),
    ('gpu',  'GPU 负载', '96.0',  '%',  '0',    '100',  '告警阈值 90 %',   'warn'),
    ('temp', '核心温度', '65.2',  '℃', '20',   '90',   '告警阈值 75 ℃',  'ok'),
]
STATUS_CN = {'ok': '正常', 'warn': '告警', 'bad': '故障'}


def spark_panel(T, key, title, val, unit, lo, hi, note, status):
    """一格 = 一个序列 + 自己的轴 + 自己的标题。
    颜色只在越阈值时变成状态色，平时统一用强调色 —— 颜色始终有含义，不做装饰。"""
    color = T[status] if status != 'ok' else T['accent']
    d, lasty = SPARK[key]
    area = d + " L 296.0 64.0 L 4.0 64.0 Z"
    gid = f'g-{key}-{T["name"]}'
    return (
      f'<div style="display:flex;flex-direction:column;gap:6px;padding:10px 12px 8px;'
      f'background:{T["surface2"]};border:1px solid {T["border"]};border-radius:8px">'
      f'<div style="display:flex;align-items:baseline;gap:8px">'
      f'<span style="font-size:12px;color:{T["t2"]};font-weight:500">{title}</span>'
      f'<span style="margin-left:auto">{status_tag(T, status)}</span></div>'
      f'<div>{num(T, val, unit, 24, color)}</div>'
      f'<svg width="100%" height="74" viewBox="0 0 300 74" preserveAspectRatio="none" '
      f'style="display:block;overflow:visible">'
      f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
      f'<stop offset="0%" stop-color="{color}" stop-opacity="{0.22 if T["name"]=="dark" else 0.16}"/>'
      f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
      + ''.join(f'<line x1="0" y1="{y}" x2="300" y2="{y}" stroke="{T["grid"]}" '
                f'stroke-width="1"/>' for y in (8, 26, 45, 64))
      + f'<path d="{area}" fill="url(#{gid})"/>'
      f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" '
      f'stroke-linejoin="round" stroke-linecap="round"/>'
      f'<circle cx="296" cy="{lasty}" r="4" fill="{color}" stroke="{T["surface2"]}" '
      f'stroke-width="2"/></svg>'
      f'<div style="display:flex;align-items:center;font:400 10px/1 {MONO};color:{T["t4"]}">'
      f'<span>{lo}</span>'
      f'<span style="margin:0 auto;letter-spacing:.2px">{note}</span>'
      f'<span>{hi}</span></div></div>')


def status_tag(T, status):
    """状态永远是 点 + 文字，不靠颜色单独承载语义（琥珀在白底上对比度不足 3:1）"""
    c, soft = T[status], T[status + 'Soft']
    return (f'<span style="display:inline-flex;align-items:center;gap:5px;padding:1px 7px;'
            f'border-radius:4px;background:{soft};color:{c};font-size:11px;font-weight:500">'
            f'<span style="width:5px;height:5px;border-radius:50%;background:{c}"></span>'
            f'{STATUS_CN[status]}</span>')


def status_strip(T):
    def cell(label, body, first=False):
        bd = '' if first else f'border-left:1px solid {T["divider"]};'
        return (f'<div style="flex:1;{bd}padding:0 18px;display:flex;flex-direction:column;'
                f'justify-content:center;gap:5px">'
                f'<div style="font-size:11px;color:{T["t3"]};letter-spacing:.3px">{label}</div>'
                f'<div style="display:flex;align-items:center;gap:8px">{body}</div></div>')
    batt = (f'<div style="display:flex;align-items:center;gap:14px;padding:0 20px 0 4px">'
            f'{ring(T, 76, T["ok"])}'
            f'<div style="display:flex;flex-direction:column;gap:4px">'
            f'<div style="font-size:11px;color:{T["t3"]}">电池</div>'
            f'{num(T, "11.74", "V", 22)}'
            f'<div style="font:400 10px/1 {MONO};color:{T["t4"]}">9.00 – 12.60 V</div>'
            f'</div></div>')
    cells = [
        cell('通信链路', f'{status_tag(T, "ok")}'
             f'<span style="font:400 11px/1 {MONO};color:{T["t4"]}">9090</span>', True),
        cell('ROS 节点', num(T, '3', '', 20)),
        cell('活动话题', num(T, '6', '', 20)),
        cell('服务', num(T, '1', '', 20)),
        cell('在线舵机', num(T, '6', '/ 6', 20)),
        cell('雷达点数', num(T, '0', 'pts', 20, T['bad'])
             + status_tag(T, 'bad')),
    ]
    return (f'<div style="height:86px;flex-shrink:0;display:flex;align-items:stretch;'
            f'background:{T["surface"]};border:1px solid {T["border"]};border-radius:10px;'
            f'box-shadow:{T["shadow"]};overflow:hidden">'
            f'{batt}<div style="width:1px;background:{T["divider"]}"></div>'
            f'{"".join(cells)}</div>')


def attitude(T, size=150, fill=True):
    """地平仪 + RPY。每个量各自归一化：横滚/俯仰按 ±45° 居中，航向按 0~360 从左起。"""
    roll, pitch = -6.0, 3.2
    sky = '#2B6CB0' if T['name'] == 'light' else '#1E4E79'
    ground = '#8A6A3E' if T['name'] == 'light' else '#5E4526'
    c = size / 2
    r = c - 6
    off = pitch * (size / 52.7)
    ticks = ''.join(
        f'<line x1="{c + (r-10)*(1 if t>0 else -1)}" y1="0" '
        f'x2="{c + (r-2)*(1 if t>0 else -1)}" y2="0" stroke="{T["t4"]}" stroke-width="1.4" '
        f'transform="rotate({t} {c} {c})" />' for t in (-30, -20, -10, 10, 20, 30))
    horizon = (
      f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" style="flex-shrink:0">'
      f'<defs><clipPath id="ah-{T["name"]}-{size}"><circle cx="{c}" cy="{c}" r="{r}"/>'
      f'</clipPath></defs>'
      f'<g clip-path="url(#ah-{T["name"]}-{size})">'
      f'<g transform="rotate({-roll} {c} {c}) translate(0 {off:.1f})">'
      f'<rect x="{-size}" y="{-size}" width="{size*3}" height="{size+c}" fill="{sky}"/>'
      f'<rect x="{-size}" y="{c}" width="{size*3}" height="{size*2}" fill="{ground}"/>'
      f'<line x1="{-size}" y1="{c}" x2="{size*2}" y2="{c}" stroke="rgba(255,255,255,.9)" '
      f'stroke-width="1.6"/>'
      + ''.join(f'<line x1="{c-w/2}" y1="{c+dy}" x2="{c+w/2}" y2="{c+dy}" '
                f'stroke="rgba(255,255,255,.45)" stroke-width="1"/>'
                for dy, w in ((-r*0.42, r*0.42), (-r*0.21, r*0.25),
                              (r*0.21, r*0.25), (r*0.42, r*0.42)))
      + f'</g></g>'
      f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="{T["border"]}" stroke-width="1"/>'
      f'{ticks}'
      f'<path d="M{c-r*0.5} {c}h{r*0.26} l{r*0.11} {r*0.09} l{r*0.11} -{r*0.09} h{r*0.26}" '
      f'fill="none" stroke="{T["warn"]}" stroke-width="2.2" stroke-linecap="round" '
      f'stroke-linejoin="round"/>'
      f'<path d="M{c} 4l-5 8h10z" fill="{T["t2"]}"/></svg>')

    def gauge(label, en, value, lo, hi):
        frac = (value - lo) / (hi - lo)
        centered = lo < 0
        return (
          f'<div style="display:flex;flex-direction:column;gap:6px;align-items:center;flex:1">'
          f'<div style="display:flex;align-items:baseline;gap:5px;white-space:nowrap">'
          f'<span style="font-size:11px;color:{T["t3"]}">{label}</span>'
          f'<span style="font:400 9px/1 {MONO};color:{T["t4"]};letter-spacing:.8px">{en}</span>'
          f'</div>'
          f'{num(T, f"{value:.1f}", "°", 17)}'
          f'<div style="width:100%;height:3px;border-radius:2px;background:{T["surface2"]};'
          f'position:relative">'
          + (f'<span style="position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;'
             f'background:{T["border"]}"></span>' if centered else '')
          + f'<span style="position:absolute;top:0;bottom:0;border-radius:2px;'
            f'background:{T["accent"]};left:{min(frac,0.5)*100:.1f}%;'
            f'width:{abs(frac-0.5)*100 if centered else frac*100:.1f}%"></span>'
          + f'</div>'
          f'<span style="font:400 9px/1 {MONO};color:{T["t4"]}">{lo:g} ~ {hi:g}</span></div>')

    return (f'<div style="display:flex;flex-direction:column;align-items:center;gap:16px;'
            + ('height:100%;justify-content:center;' if fill else '') + f'">{horizon}'
            f'<div style="display:flex;gap:14px;width:100%">'
            f'{gauge("横滚", "ROLL", roll, -45, 45)}'
            f'{gauge("俯仰", "PITCH", pitch, -45, 45)}'
            f'{gauge("航向", "YAW", 128.4, 0, 360)}</div></div>')


HEALTH = [('rosbridge', '已连接', 'ok'), ('低压告警', '否', 'ok'),
          ('雷达数据', '无', 'warn'), ('惯性单元', '正常', 'ok'),
          ('里程计', '正常', 'ok'), ('舵机总线', '6 在线', 'ok')]


def health_grid(T):
    return (f'<div style="display:grid;grid-template-columns:repeat(2, minmax(0,1fr));'
            f'gap:1px;background:{T["divider"]};border:1px solid {T["divider"]};'
            f'border-radius:7px;overflow:hidden">'
            + ''.join(
              f'<div style="display:flex;align-items:center;gap:8px;padding:8px 11px;'
              f'background:{T["surface"]}">'
              f'<span style="width:6px;height:6px;border-radius:50%;background:{T[s]};'
              f'flex-shrink:0"></span>'
              f'<span style="font-size:12px;color:{T["t3"]}">{k}</span>'
              f'<span style="margin-left:auto;font:500 12px/1 {MONO};color:{T["t1"]};'
              f'font-variant-numeric:tabular-nums">{v}</span></div>'
              for k, v, s in HEALTH) + '</div>')


ALARMS = [('01', '电池低压', '11.74 V', '阈值 10.00 V', 'ok'),
          ('02', '核心高温', '65.2 ℃', '阈值 75.0 ℃', 'ok'),
          ('03', '通信链路', '已连接', 'rosbridge 9090', 'ok'),
          ('04', 'CPU 过载', '27.8 %', '阈值 90 %', 'ok'),
          ('05', 'GPU 过载', '96.0 %', '阈值 90 %', 'warn'),
          ('06', '雷达数据', '无数据', '/scan 静默 42 s', 'bad')]


def alarm_table(T):
    head = (f'<div style="display:grid;grid-template-columns:38px 1fr 96px 132px 66px;'
            f'gap:0;padding:0 12px;height:30px;align-items:center;'
            f'border-bottom:1px solid {T["divider"]};font:500 10px/1 {MONO};'
            f'letter-spacing:1.2px;color:{T["t4"]};text-transform:uppercase">'
            f'<span>#</span><span>监控项</span><span>当前值</span><span>判据</span>'
            f'<span style="text-align:right">状态</span></div>')
    rows = ''.join(
        f'<div style="display:grid;grid-template-columns:38px 1fr 96px 132px 66px;'
        f'padding:0 12px;height:42px;align-items:center;'
        f'border-bottom:1px solid {T["divider"]}">'
        f'<span style="font:400 11px/1 {MONO};color:{T["t4"]}">{n}</span>'
        f'<span style="font-size:13px;color:{T["t1"]}">{name}</span>'
        f'<span style="font:500 12px/1 {MONO};color:{T["t2"] if s=="ok" else T[s]};'
        f'font-variant-numeric:tabular-nums">{val}</span>'
        f'<span style="font:400 11px/1 {MONO};color:{T["t4"]}">{crit}</span>'
        f'<span style="text-align:right">{status_tag(T, s)}</span></div>'
        for n, name, val, crit, s in ALARMS)
    return f'<div style="margin:-12px -14px -14px">{head}{rows}</div>'


def build_overview(T):
    content = (
      f'<div style="flex:1;min-height:0;background:{T["bg"]};padding:14px;'
      f'display:flex;flex-direction:column;gap:12px">'
      f'{status_strip(T)}'
      + card(T, '遥测趋势', '最近 120 s',
             f'<div style="display:grid;grid-template-columns:repeat(4, minmax(0,1fr));gap:10px">'
             + ''.join(spark_panel(T, *p) for p in PANELS) + '</div>')
      + f'<div style="flex:1;min-height:0;display:grid;'
        f'grid-template-columns:minmax(0,380px) minmax(0,1fr);gap:12px">'
        f'<div style="display:flex;flex-direction:column;gap:12px;min-height:0">'
        + card(T, '姿态 IMU', 'imu_raw', attitude(T), grow=True)
        + card(T, '系统健康', None, health_grid(T))
        + '</div>'
        + card(T, '告警监控', '6 项 · 1 告警 1 故障', alarm_table(T), grow=True)
        + '</div></div>')
    return (f'<div style="width:1440px;height:900px;display:flex;background:{T["bg"]};'
            f'font-family:{SANS};-webkit-font-smoothing:antialiased">'
            f'{sider(T, T["accent"])}'
            f'<div style="flex:1;min-width:0;display:flex;flex-direction:column">'
            f'{topbar(T)}{content}</div></div>')


DC = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <style>
    body {{ margin: 0; font-family: {sans}; }}
    a {{ color: {link}; text-decoration: none; }}
    a:hover {{ color: {linkh}; }}
    {fonts}
  </style>
  {fontlink}
</helmet>
{body}
</x-dc>
</body>
</html>
"""


def write(fn, T, body, link=None, linkh=None):
    open(fn, 'w').write(DC.format(
        sans=SANS, fonts='', fontlink=FONTS,
        link=link or T['accent'], linkh=linkh or T['t1'], body=body))
    print('wrote', fn, len(body), 'bytes of body')


# ============ 现状对照（照着 Overview.vue + 实际截图还原）============
ANTD_SANS = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', "
             "Arial, 'Noto Sans', sans-serif")


def build_current():
    C = dict(bg='#f0f2f5', card='#fff', bd='#f0f0f0', t1='rgba(0,0,0,.88)',
             t2='rgba(0,0,0,.65)', t3='rgba(0,0,0,.45)', blue='#1677ff')
    tiles = [('连接', None, 'ONLINE'), ('电压', '11.74', 'V'), ('ROS 节点', '3', None),
             ('话题', '6', None), ('服务', '1', None), ('舵机在线', '6', None)]
    tcards = ''
    for k, v, suf in tiles:
        if v is None:
            val = (f'<span style="display:inline-block;padding:0 8px;height:22px;line-height:22px;'
                   f'border-radius:4px;background:#f6ffed;border:1px solid #b7eb8f;color:#389e0d;'
                   f'font-size:12px">{suf}</span>')
        else:
            val = (f'{v}<small style="font-size:14px;color:{C["t3"]}"> {suf}</small>'
                   if suf else v)
        bar = ('<div style="height:6px;border-radius:3px;background:#f5f5f5;margin-top:8px">'
               '<div style="width:76%;height:6px;border-radius:3px;background:#52c41a"></div>'
               '</div>') if k == '电压' else ''
        tcards += (f'<div style="flex:1;background:{C["card"]};border-radius:8px;padding:12px 16px 14px">'
                   f'<div style="font-size:13px;color:{C["t3"]}">{k}</div>'
                   f'<div style="font-size:26px;font-weight:600;margin:4px 0;color:{C["t1"]}">'
                   f'{val}</div>{bar}</div>')
    rows = [('rosbridge', '已连接'), ('电池电压', '11.74 V'), ('电量估算', '76 %'),
            ('低压告警', '否'), ('ROS 节点数', '3'), ('话题数', '6'), ('服务数', '1')]
    health = ''.join(
        f'<div style="display:flex;border-bottom:1px solid {C["bd"]}">'
        f'<div style="width:180px;padding:10px 16px;background:#fafafa;font-size:14px;'
        f'color:{C["t2"]}">{k}</div>'
        f'<div style="flex:1;padding:10px 16px;font-size:14px;color:{C["t1"]}">{v}</div></div>'
        for k, v in rows)
    legend = ''.join(
        f'<span style="display:flex;align-items:center;gap:6px;font-size:12px;color:{C["t2"]}">'
        f'<i style="width:12px;height:3px;background:{c};display:inline-block;border-radius:2px">'
        f'</i>{l} <b style="font-family:ui-monospace,monospace">—</b></span>'
        for l, c in (('电压 V', '#1677ff'), ('CPU %', '#52c41a'),
                     ('GPU %', '#722ed1'), ('温度 °C', '#fa8c16')))
    grid = ''.join(f'<line x1="8" y1="{8+184*i/4:.0f}" x2="1092" y2="{8+184*i/4:.0f}" '
                   f'stroke="#f0f0f0" stroke-width="1"/>' for i in range(5))
    ttl = (lambda t, ex='': f'<div style="padding:0 16px;height:38px;display:flex;'
           f'align-items:center;border-bottom:1px solid {C["bd"]};font-size:14px;'
           f'font-weight:600;color:{C["t1"]}">{t}'
           + (f'<span style="margin-left:auto;font-weight:400;color:#999;font-size:12px">{ex}'
              f'</span>' if ex else '') + '</div>')
    side_items = ''
    for key, ic, label, kind in MENU:
        if kind == 'group':
            side_items += (f'<div style="padding:14px 20px 6px;font-size:12px;'
                           f'color:rgba(255,255,255,.45)">{label}</div>')
            continue
        on = kind == 'active'
        side_items += (f'<div style="height:40px;display:flex;align-items:center;padding:0 24px;'
                       f'font-size:14px;'
                       + (f'background:{C["blue"]};color:#fff;' if on
                          else 'color:rgba(255,255,255,.65);') + f'">{label}</div>')
    return (
      f'<div style="width:1440px;height:900px;display:flex;background:{C["bg"]};'
      f'font-family:{ANTD_SANS}">'
      f'<div style="width:224px;flex-shrink:0;background:#001529;display:flex;'
      f'flex-direction:column">'
      f'<div style="height:56px;display:flex;align-items:center;gap:10px;padding:0 20px;'
      f'color:#fff;font-size:16px;font-weight:600">JetRover '
      f'<span style="color:#4096ff">管理系统</span></div>'
      f'<div style="flex:1;overflow:hidden">{side_items}</div>'
      f'<div style="padding:12px 20px;color:rgba(255,255,255,.3);font-size:11px;'
      f'font-family:ui-monospace,monospace;line-height:1.7">rosbridge<br>192.168.3.63:9090</div>'
      f'</div>'
      f'<div style="flex:1;min-width:0;display:flex;flex-direction:column">'
      f'<div style="height:56px;background:#fff;display:flex;align-items:center;gap:12px;'
      f'padding:0 16px;box-shadow:0 1px 4px rgba(0,21,41,.08)">'
      f'<span style="font-size:16px;font-weight:600;color:{C["t1"]}">概览</span>'
      f'<span style="font-size:13px;color:{C["t3"]};font-family:ui-monospace,monospace">'
      f'/ overview</span>'
      f'<div style="margin-left:auto;display:flex;gap:8px">'
      f'<span style="padding:0 8px;height:22px;line-height:22px;border-radius:4px;'
      f'background:#f6ffed;border:1px solid #b7eb8f;color:#389e0d;font-size:12px">ONLINE</span>'
      f'<span style="padding:0 8px;height:22px;line-height:22px;border-radius:4px;'
      f'background:#e6f4ff;border:1px solid #91caff;color:#0958d9;font-size:12px">'
      f'11.74V · 76%</span></div></div>'
      f'<div style="flex:1;padding:20px;display:flex;flex-direction:column;gap:16px;'
      f'min-height:0">'
      f'<div style="display:flex;gap:16px">{tcards}</div>'
      f'<div style="display:flex;gap:16px">'
      f'<div style="flex:1;background:#fff;border-radius:8px">{ttl("系统健康")}'
      f'<div style="padding:16px">'
      f'<div style="border:1px solid {C["bd"]};border-radius:8px;overflow:hidden">{health}</div>'
      f'</div></div>'
      f'<div style="flex:1;background:#fff;border-radius:8px">{ttl("姿态 IMU")}'
      f'<div style="padding:16px;display:flex;gap:16px;align-items:center">'
      f'<svg width="150" height="150"><defs><clipPath id="cah">'
      f'<circle cx="75" cy="75" r="72"/></clipPath></defs>'
      f'<g clip-path="url(#cah)"><rect x="0" y="0" width="150" height="76" fill="#3E7CB1"/>'
      f'<rect x="0" y="76" width="150" height="74" fill="#7A5C33"/>'
      f'<line x1="0" y1="76" x2="150" y2="76" stroke="#fff" stroke-width="1.5"/>'
      f'<path d="M55 76h12l8 5 8-5h12" fill="none" stroke="#e8b62c" stroke-width="2"/></g></svg>'
      f'<div style="display:flex;flex-direction:column;gap:10px">'
      + ''.join(f'<div style="font-size:14px;color:{C["t2"]}">{k}：'
                f'<span style="color:{C["t1"]}">{v}</span></div>'
                for k, v in (('Roll', '-6.0°'), ('Pitch', '3.2°'), ('Yaw', '128.4°')))
      + f'</div></div></div></div>'
      f'<div style="background:#fff;border-radius:8px">{ttl("历史曲线", "最近 2 分钟")}'
      f'<div style="padding:16px">'
      f'<svg width="1100" height="200" style="width:100%;height:200px">{grid}'
      f'<path d="M8 120 L 200 118 L 420 112 L 640 104 L 860 99 L 1092 96" fill="none" '
      f'stroke="#1677ff" stroke-width="2"/></svg>'
      f'<div style="display:flex;gap:18px;margin-top:10px">{legend}</div>'
      f'</div></div>'
      f'<div style="flex:1"></div>'
      f'</div></div></div>')


def swatch(hex_, label, sub, T, ink='#0F172A'):
    return (f'<div style="display:flex;align-items:center;gap:10px">'
            f'<span style="width:34px;height:34px;border-radius:7px;background:{hex_};'
            f'border:1px solid rgba(0,0,0,.08);flex-shrink:0"></span>'
            f'<div style="display:flex;flex-direction:column;gap:2px;min-width:0">'
            f'<span style="font-size:12px;color:{ink};font-weight:500">{label}</span>'
            f'<span style="font:400 11px/1 {MONO};color:{T["t3"]};'
            f'text-transform:uppercase">{hex_}</span>'
            f'<span style="font-size:10px;color:{T["t4"]};white-space:nowrap">{sub}</span>'
            f'</div></div>')


def build_tokens():
    T = LIGHT
    def sec(t, note, body):
        return (f'<div style="display:flex;flex-direction:column;gap:12px">'
                f'<div style="display:flex;align-items:baseline;gap:10px;'
                f'border-bottom:1px solid {T["border"]};padding-bottom:8px">'
                f'<span style="font-size:14px;font-weight:600;color:{T["t1"]}">{t}</span>'
                f'<span style="font-size:11px;color:{T["t3"]}">{note}</span></div>{body}</div>')
    status_rows = ''.join(
        f'<div style="display:grid;grid-template-columns:76px minmax(0,1fr) minmax(0,1fr) minmax(0,1fr);gap:14px;'
        f'align-items:center;padding:9px 0;border-bottom:1px solid {T["divider"]}">'
        f'<span style="font-size:12px;color:{T["t2"]};font-weight:500">{role}</span>'
        f'{swatch(lh, "浅色", lc, T)}{swatch(dh, "暗色", dc, T)}'
        f'<span style="font:400 11px/1.6 {MONO};color:{T["t3"]}">{note}</span></div>'
        for role, lh, lc, dh, dc, note in (
          ('正常 ok', '#0D9488', '卡片面 3.74:1 · 标签底 3.30:1', '#34D399', '卡片面 9.76:1',
           'CVD 最差对 ΔE 10.2（≥8 通过）'),
          ('告警 warn', '#CA8A04', '卡片面 2.94:1 · 标签底 2.58:1', '#F59E0B', '卡片面 8.74:1',
           '浅色不足 3:1 —— 只能靠点+文字兜底'),
          ('故障 bad', '#E11D48', '卡片面 4.70:1 · 标签底 3.97:1', '#F43F5E', '卡片面 5.11:1',
           '正常视力最差对 ΔE 21.3（≥15 通过）')))
    scale = ''.join(
        f'<div style="display:flex;align-items:baseline;gap:14px;padding:5px 0">'
        f'<span style="font:400 11px/1 {MONO};color:{T["t4"]};width:52px">{px}px</span>'
        f'<span style="font-size:{px}px;font-weight:{w};color:{T["t1"]};line-height:1.5;'
        f'flex:1;min-width:0;white-space:nowrap;overflow:hidden">机器人遥测 Telemetry</span>'
        f'<span style="width:110px;flex-shrink:0;text-align:right;font-size:11px;'
        f'color:{T["t3"]}">{use}</span></div>'
        for px, w, use in ((28, 600, '大数值'), (20, 600, '页面标题 / KPI'),
                           (16, 600, '卡片标题'), (14, 400, '正文 / 表格'),
                           (13, 400, '次要正文'), (12, 400, '标签'), (11, 400, '轴刻度 / 脚注')))
    bad = ('<div style="font:400 14px/1.9 -apple-system, sans-serif;color:#E11D48">'
           '11.74 V<br>9.06 V<br>12.60 V<br>108.4 %</div>')
    good = (f'<div style="font:500 14px/1.9 {MONO};color:{T["ok"]};'
            f'font-variant-numeric:tabular-nums;text-align:right;width:96px">'
            f'11.74 <span style="font-size:.72em;color:{T["t3"]}">V</span><br>'
            f'9.06 <span style="font-size:.72em;color:{T["t3"]}">V</span><br>'
            f'12.60 <span style="font-size:.72em;color:{T["t3"]}">V</span><br>'
            f'108.4 <span style="font-size:.72em;color:{T["t3"]}">%</span></div>')
    surfaces = ''.join(
        f'<div style="display:grid;grid-template-columns:110px minmax(0,1fr) minmax(0,1fr);gap:14px;'
        f'align-items:center;padding:7px 0;border-bottom:1px solid {T["divider"]}">'
        f'<span style="font:400 11px/1 {MONO};color:{T["t2"]}">{n}</span>'
        f'{swatch(l, "浅色", "", T)}{swatch(d, "暗色", "", T)}</div>'
        for n, l, d in (('--bg', LIGHT['bg'], DARK['bg']),
                        ('--surface', LIGHT['surface'], DARK['surface']),
                        ('--surface-2', LIGHT['surface2'], DARK['surface2']),
                        ('--accent', LIGHT['accent'], DARK['accent']),
                        ('--text-1', LIGHT['t1'], DARK['t1']),
                        ('--text-3', LIGHT['t3'], DARK['t3'])))
    return (
      f'<div style="width:1180px;box-sizing:border-box;background:{T["bg"]};padding:36px 40px 40px;'
      f'font-family:{SANS};display:flex;flex-direction:column;gap:26px">'
      f'<div><div style="font-size:22px;font-weight:600;color:{T["t1"]}">设计规格</div>'
      f'<div style="font-size:13px;color:{T["t3"]};margin-top:5px">'
      f'色板从监控大屏现有语言提炼；暗色是重新取阶的，不是浅色翻转。'
      f'状态色经 dataviz 验证器实测，不是目测。</div></div>'
      + sec('语义状态色', '每个都必须「圆点 + 文字」，颜色不单独承载含义',
            f'<div>{status_rows}</div>')
      + sec('表面与文字', 'CSS 自定义属性，浅暗各一套值', f'<div>{surfaces}</div>')
      + sec('字号阶梯', '固定七级，行高 1.5（表格 1.4）', f'<div>{scale}</div>')
      + sec('数值排版', '所有数值等宽对齐、单位降级',
            f'<div style="display:flex;gap:40px;align-items:flex-start">'
            f'<div><div style="font-size:11px;color:{T["bad"]};margin-bottom:8px">'
            f'现状：比例字体，位数不对齐，刷新时跳动</div>{bad}</div>'
            f'<div><div style="font-size:11px;color:{T["ok"]};margin-bottom:8px">'
            f'提案：tabular-nums + 右对齐 + 单位 .72em</div>{good}</div></div>')
      + f'</div>')


def build_typography():
    T = LIGHT
    STACKS = [
      ('系统栈', "-apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif",
       'ui-monospace, SFMono-Regular, monospace',
       '零依赖，离线必然可用。中英混排字重不匹配，数字字形偏软。'),
      ('Inter', "Inter, -apple-system, 'PingFang SC', sans-serif",
       "Inter, ui-monospace, monospace",
       '代码里已经写了但从没加载过。需自托管 woff2（约 100 KB）。无中文字体，中文仍回退。'),
      ('IBM Plex Sans + Mono', SANS, MONO,
       '工业设备出身，中英同族（Plex Sans SC），Mono 数字字形辨识度最高。需自托管两族。'),
    ]
    blocks = ''
    for name, sans, mono, note in STACKS:
        blocks += (
          f'<div style="flex:1;background:{T["surface"]};border:1px solid {T["border"]};'
          f'border-radius:10px;padding:20px;display:flex;flex-direction:column;gap:14px">'
          f'<div style="font-size:15px;font-weight:600;color:{T["t1"]};font-family:{sans}">'
          f'{name}</div>'
          f'<div style="font-family:{sans};font-size:13px;color:{T["t2"]};line-height:1.6">'
          f'遥测趋势 · 最近 120 秒<br>Telemetry · last 120 s</div>'
          f'<div style="font-family:{mono};font-variant-numeric:tabular-nums;font-size:15px;'
          f'font-weight:500;color:{T["t1"]};line-height:1.75;text-align:right;width:130px">'
          f'11.74 <span style="font-size:.72em;color:{T["t3"]}">V</span><br>'
          f'9.06 <span style="font-size:.72em;color:{T["t3"]}">V</span><br>'
          f'108.40 <span style="font-size:.72em;color:{T["t3"]}">%</span><br>'
          f'-0.116 <span style="font-size:.72em;color:{T["t3"]}">m</span></div>'
          f'<div style="font-family:{mono};font-size:12px;color:{T["t3"]}">'
          f'0123456789 · 1lI0O · 5S8B</div>'
          f'<div style="margin-top:auto;font-family:{sans};font-size:11px;color:{T["t3"]};'
          f'line-height:1.7;border-top:1px solid {T["divider"]};padding-top:10px">{note}</div>'
          f'</div>')
    return (f'<div style="width:1180px;height:520px;box-sizing:border-box;background:{T["bg"]};padding:36px 40px;'
            f'font-family:{SANS};display:flex;flex-direction:column;gap:20px">'
            f'<div><div style="font-size:22px;font-weight:600;color:{T["t1"]}">字体三选一</div>'
            f'<div style="font-size:13px;color:{T["t3"]};margin-top:5px">'
            f'机器人是局域网离线的，Google Fonts 取不到 —— 除系统栈外都必须自托管 woff2 到 '
            f'public/fonts/。这块画板本身用的是 Plex。</div></div>'
            f'<div style="flex:1;display:flex;gap:16px;min-height:0">{blocks}</div></div>')


# ============ 变体 B：紧凑指挥版（去卡片、发丝线分隔、密度更高）============
def build_layout_b():
    T = DARK
    def col(label, val, unit, color=None, tag=None):
        return (f'<div style="display:flex;flex-direction:column;gap:4px;padding:0 16px;'
                f'border-left:1px solid {T["divider"]}">'
                f'<span style="font:500 10px/1 {MONO};letter-spacing:1.2px;color:{T["t4"]};'
                f'text-transform:uppercase">{label}</span>'
                f'<div style="display:flex;align-items:baseline;gap:6px">'
                f'{num(T, val, unit, 19, color)}{tag or ""}</div></div>')
    metrics = (
      f'<div style="display:flex;align-items:center;height:60px;flex-shrink:0;'
      f'border-bottom:1px solid {T["border"]}">'
      f'<div style="padding:0 16px 0 0;display:flex;align-items:center;gap:12px">'
      f'{ring(T, 76, T["ok"])}{num(T, "11.74", "V", 19)}</div>'
      + col('链路', 'ONLINE', '', T['ok'])
      + col('节点', '3', '') + col('话题', '6', '') + col('服务', '1', '')
      + col('舵机', '6', '/6')
      + col('CPU', '27.8', '%') + col('GPU', '96.0', '%', T['warn'])
      + col('温度', '65.2', '℃') + col('雷达', '0', 'pts', T['bad'])
      + '</div>')
    sparks = (f'<div style="display:grid;grid-template-columns:repeat(4, minmax(0,1fr));'
              f'flex-shrink:0;border-bottom:1px solid {T["border"]}">'
              + ''.join(
                f'<div style="padding:10px 14px;'
                + ('' if i == 0 else f'border-left:1px solid {T["divider"]};') + '">'
                + spark_body(T, *p) + '</div>'
                for i, p in enumerate(PANELS)) + '</div>')
    alarm_rows = ''.join(
        f'<div style="display:grid;grid-template-columns:34px 1fr 92px 60px;padding:0 16px;'
        f'height:38px;align-items:center;border-bottom:1px solid {T["divider"]}">'
        f'<span style="font:400 11px/1 {MONO};color:{T["t4"]}">{n}</span>'
        f'<span style="font-size:13px;color:{T["t1"]}">{name}</span>'
        f'<span style="font:500 12px/1 {MONO};color:{T["t2"] if s=="ok" else T[s]};'
        f'font-variant-numeric:tabular-nums">{val}</span>'
        f'<span style="text-align:right">{status_tag(T, s)}</span></div>'
        for n, name, val, crit, s in ALARMS)
    health_rows = ''.join(
        f'<div style="display:flex;align-items:center;gap:9px;padding:0 16px;height:38px;'
        f'border-bottom:1px solid {T["divider"]}">'
        f'<span style="width:6px;height:6px;border-radius:50%;background:{T[st]}"></span>'
        f'<span style="font-size:13px;color:{T["t2"]}">{k}</span>'
        f'<span style="margin-left:auto;font:500 12px/1 {MONO};color:{T["t1"]};'
        f'font-variant-numeric:tabular-nums">{v}</span></div>'
        for k, v, st in HEALTH)
    def head(t):
        return (f'<div style="height:32px;display:flex;align-items:center;padding:0 16px;'
                f'border-bottom:1px solid {T["border"]};font:500 10px/1 {MONO};'
                f'letter-spacing:1.4px;color:{T["t4"]};text-transform:uppercase">{t}</div>')
    body = (f'<div style="flex:1;min-height:0;display:grid;'
            f'grid-template-columns:320px minmax(0,1fr) 380px">'
            f'<div style="display:flex;flex-direction:column;'
            f'border-right:1px solid {T["border"]}">{head("姿态 · IMU")}'
            f'<div style="padding:18px 16px">{attitude(T, 148, fill=False)}</div></div>'
            f'<div style="display:flex;flex-direction:column;'
            f'border-right:1px solid {T["border"]}">{head("系统健康")}{health_rows}</div>'
            f'<div style="display:flex;flex-direction:column;min-height:0">'
            f'{head("告警监控 · 1 告警 1 故障")}{alarm_rows}</div></div>')
    return (f'<div style="width:1440px;height:900px;display:flex;background:{T["bg"]};'
            f'font-family:{SANS};-webkit-font-smoothing:antialiased">'
            f'{sider(T, T["accent"])}'
            f'<div style="flex:1;min-width:0;display:flex;flex-direction:column">'
            f'{topbar(T)}{metrics}{sparks}{body}</div></div>')


def spark_body(T, key, title, val, unit, lo, hi, note, status):
    color = T[status] if status != 'ok' else T['accent']
    d, lasty = SPARK[key]
    gid = f'gb-{key}'
    return (f'<div style="display:flex;align-items:baseline;gap:8px;margin-bottom:4px">'
            f'<span style="font-size:11px;color:{T["t3"]}">{title}</span>'
            f'{num(T, val, unit, 17, color)}'
            f'<span style="margin-left:auto;font:400 10px/1 {MONO};color:{T["t4"]}">'
            f'{lo}–{hi}</span></div>'
            f'<svg width="100%" height="52" viewBox="0 0 300 74" preserveAspectRatio="none" '
            f'style="display:block">'
            f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="{color}" stop-opacity=".2"/>'
            f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
            f'<path d="{d} L 296.0 64.0 L 4.0 64.0 Z" fill="url(#{gid})"/>'
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round"/></svg>')


import json as _json

CANVAS_DATA = {
  "artboards": [
    {"file": "Current.dc.html",      "x": 0,    "y": 0,    "w": 1440, "h": 900,
     "title": "后台现状 · 对照（antd 默认）"},
    {"file": "Main.dc.html",         "x": 1560, "y": 0,    "w": 1440, "h": 900,
     "title": "后台提案 A · 浅色"},
    {"file": "OverviewDark.dc.html", "x": 3120, "y": 0,    "w": 1440, "h": 900,
     "title": "后台提案 A · 暗色（同一结构）"},
    {"file": "LayoutB.dc.html",      "x": 0,    "y": 1060, "w": 1440, "h": 900,
     "title": "后台提案 B · 紧凑指挥版（未选）"},
    {"file": "Tokens.dc.html",       "x": 1560, "y": 1060, "w": 1180, "h": 1300,
     "title": "设计规格"},
    {"file": "Typography.dc.html",   "x": 2900, "y": 1060, "w": 1180, "h": 520,
     "title": "字体三选一 → 已定 Inter"},
    {"file": "BigScreenNow.dc.html", "x": 0,    "y": 2500, "w": 1920, "h": 1080,
     "title": "监控大屏 · 现状（四色分区）"},
    {"file": "BigScreenNew.dc.html", "x": 2040, "y": 2500, "w": 1920, "h": 1080,
     "title": "监控大屏 · 重设计"},
  ],
  "annotations": [
    {"id": "note-brief", "x": 0, "y": -200, "w": 760,
     "text": "已定：提案 A（卡片版，浅+暗双主题）· 字体 Inter\n\n"
             "上排 = 后台概览（左现状 / 中浅色 / 右暗色）。\n"
             "下排 = 监控大屏（左现状 / 右重设计）。\n"
             "提案 B 保留在中排左，未选。"},
    {"id": "note-bs", "x": 0, "y": 2310, "w": 940,
     "text": "大屏去五彩：拆掉「运动=青 / 姿态=蓝 / 算力=琥珀 / 系统=紫」四色分区。\n"
             "卡片一律扁平中性，分组改用小号大写标签 + 发丝线，不再靠色相区分。\n"
             "只有真越阈值的才着色 —— 这版里就 GPU 96% 和雷达 0 点两处。\n"
             "绿色「正常」保留；后台那几页颜色一点没动。"},
    {"id": "note-chart", "x": 1560, "y": 2420, "w": 640,
     "text": "四条曲线原本挤在一张图上（电压 9~12.6V、CPU 0~100%、温度 20~90℃），\n"
             "那是多轴反模式，补坐标轴也救不了。改成四联小图：\n"
             "每格一个序列、一条自己的轴、自己的阈值虚线。"},
  ],
  "launch": {"view": "canvas"},
}


def main():
    write('Main.dc.html', LIGHT, build_overview(LIGHT))
    write('OverviewDark.dc.html', DARK, build_overview(DARK))
    write('Current.dc.html', LIGHT, build_current(), link='#1677ff', linkh='#0958d9')
    write('LayoutB.dc.html', DARK, build_layout_b())
    write('Tokens.dc.html', LIGHT, build_tokens())
    write('Typography.dc.html', LIGHT, build_typography())
    write('BigScreenNew.dc.html', DARK, build_bigscreen())
    write('BigScreenNow.dc.html', DARK, build_bigscreen_now())
    open('canvas.json', 'w').write(_json.dumps(CANVAS_DATA, ensure_ascii=False, indent=2))
    print('wrote canvas.json')


# ============================ 监控大屏 ============================
BS_METRICS = [
    ('运动', [('前进速度', '0.00', 'm/s', None, None), ('转向角速度', '0.00', 'rad/s', None, None)]),
    ('姿态', [('横滚', '-6.0', '°', None, None), ('俯仰', '3.2', '°', None, None),
              ('航向', '128.4', '°', None, None)]),
    ('算力', [('CPU 负载', '27.8', '%', 28, None), ('GPU 负载', '96.0', '%', 96, 'warn'),
              ('核心温度', '65.2', '℃', 72, None), ('内存占用', '41', '%', 41, None)]),
    ('系统', [('ROS 节点', '3', '', None, None), ('活动话题', '6', '', None, None),
              ('在线舵机', '6', '', None, None), ('雷达点数', '0', 'pts', None, 'bad')]),
]
BS_STATUS = [('通信链路', True), ('激光雷达', False), ('惯性单元', True),
             ('里程计', True), ('舵机总线', True)]


def bs_panel(T, title, right, body, grow=False, pad='12px 14px'):
    return (f'<section style="{"flex:1;min-height:0;" if grow else ""}'
            f'background:{T["surface"]};border:1px solid {T["border"]};border-radius:12px;'
            f'display:flex;flex-direction:column;overflow:hidden">'
            f'<div style="height:40px;flex-shrink:0;display:flex;align-items:center;gap:10px;'
            f'padding:0 16px;border-bottom:1px solid {T["divider"]}">'
            f'<span style="width:3px;height:14px;border-radius:2px;background:{T["accent"]}">'
            f'</span>'
            f'<span style="font-size:14px;font-weight:600;color:{T["t2"]};letter-spacing:.3px">'
            f'{title}</span>'
            + (f'<span style="margin-left:auto;font-size:11px;letter-spacing:1.6px;'
               f'color:{T["t4"]};text-transform:uppercase">{right}</span>' if right else '')
            + f'</div><div style="padding:{pad};flex:1;min-height:0;overflow:hidden">{body}'
              f'</div></section>')


def bs_metric(T, label, val, unit, bar, exc):
    """卡片一律扁平中性；只有越界的那个才染色。"""
    c = T[exc] if exc else T['t1']
    bd = f'1px solid {T[exc]}44' if exc else f'1px solid {T["border"]}'
    return (f'<div style="padding:9px 11px 10px;border-radius:8px;background:{T["surface2"]};'
            f'border:{bd};display:flex;flex-direction:column;gap:5px">'
            f'<span style="font-size:11px;color:{T["t3"]};letter-spacing:.3px">{label}</span>'
            f'<div style="display:flex;align-items:baseline">{num(T, val, unit, 22, c)}'
            + (f'<span style="margin-left:auto">{status_tag(T, exc)}</span>' if exc else '')
            + '</div>'
            + (f'<div style="height:3px;border-radius:2px;background:{T["bg"]};overflow:hidden">'
               f'<div style="width:{min(100,bar)}%;height:3px;border-radius:2px;'
               f'background:{c}"></div></div>' if bar is not None else '')
            + '</div>')


def bs_chart(T, key, title, val, unit, lo, hi, thresh_label, thresh_y, exc=None):
    color = T[exc] if exc else T['accent']
    d, _ = SPARK[key]
    gid = f'bs-{key}'
    yl = ''.join(
        f'<text x="0" y="{y+3}" style="font:400 10px {SANS};fill:{T["t4"]}">{v}</text>'
        for y, v in ((10, hi), (37, ''), (64, lo)))
    return (f'<div style="display:flex;flex-direction:column;gap:8px">'
            f'<div style="display:flex;align-items:baseline;gap:10px">'
            f'{num(T, val, unit, 26, color)}'
            f'<span style="margin-left:auto;font-size:11px;color:{T["t4"]}">{thresh_label}</span>'
            f'</div>'
            f'<div style="display:flex;gap:8px;align-items:stretch">'
            f'<svg width="30" height="74" viewBox="0 0 30 74" style="flex-shrink:0;'
            f'overflow:visible">{yl}</svg>'
            f'<svg width="100%" height="74" viewBox="0 0 300 74" preserveAspectRatio="none" '
            f'style="display:block;overflow:visible">'
            f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="{color}" stop-opacity=".2"/>'
            f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
            + ''.join(f'<line x1="0" y1="{y}" x2="300" y2="{y}" stroke="{T["grid"]}" '
                      f'stroke-width="1"/>' for y in (10, 37, 64))
            + (f'<line x1="0" y1="{thresh_y}" x2="300" y2="{thresh_y}" stroke="{T["warn"]}" '
               f'stroke-width="1" stroke-dasharray="3 3" opacity=".55"/>' if thresh_y else '')
            + f'<path d="{d} L 296.0 64.0 L 4.0 64.0 Z" fill="url(#{gid})"/>'
              f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" '
              f'stroke-linejoin="round"/></svg></div></div>')


def bs_viewport(T):
    """3D 孪生视口占位：等距网格 + 简化机器人线稿"""
    return (f'<div style="position:relative;flex:1;min-height:0;border-radius:12px;'
            f'border:1px solid {T["border"]};background:#06090F;overflow:hidden">'
            f'<svg width="100%" height="100%" viewBox="0 0 900 760" '
            f'preserveAspectRatio="xMidYMid meet" style="display:block">'
            + ''.join(f'<line x1="{450-380+i*76}" y1="470" x2="{450-620+i*124}" y2="700" '
                      f'stroke="rgba(255,255,255,.05)" stroke-width="1"/>' for i in range(11))
            + ''.join(f'<line x1="{450-620+ (i*24)}" y1="{700-i*23}" '
                      f'x2="{450+620-(i*24)}" y2="{700-i*23}" '
                      f'stroke="rgba(255,255,255,.05)" stroke-width="1"/>' for i in range(11))
            + f'<g stroke="{T["accent"]}" stroke-opacity=".85" fill="none" stroke-width="2" '
              f'stroke-linejoin="round" stroke-linecap="round">'
              f'<path d="M330 560 L450 500 L570 560 L450 620 Z"/>'
              f'<path d="M330 560 v40 L450 660 v-40 M570 560 v40 L450 660"/>'
              f'<path d="M450 500 V430"/><path d="M450 430 L520 350"/>'
              f'<path d="M520 350 L470 268"/><path d="M470 268 l-26 -20 m26 20 l4 -33"/>'
              f'<circle cx="450" cy="430" r="9"/><circle cx="520" cy="350" r="8"/>'
              f'</g>'
              f'<g stroke="{T["t4"]}" stroke-opacity=".5" fill="none" stroke-width="1.4">'
              f'<circle cx="450" cy="560" r="150" stroke-dasharray="2 8"/>'
              f'<circle cx="450" cy="560" r="230" stroke-dasharray="2 10"/></g>'
              f'</svg>'
            + ''.join(f'<span style="position:absolute;{pos};width:18px;height:18px;'
                      f'border:1px solid rgba(56,189,248,.5);{edge}"></span>'
                      for pos, edge in (
                        ('top:14px;left:14px', 'border-right:0;border-bottom:0'),
                        ('top:14px;right:14px', 'border-left:0;border-bottom:0'),
                        ('bottom:14px;left:14px', 'border-right:0;border-top:0'),
                        ('bottom:14px;right:14px', 'border-left:0;border-top:0')))
            + f'<div style="position:absolute;top:17px;left:40px;font-size:11px;'
              f'letter-spacing:2.4px;color:{T["t4"]};text-transform:uppercase">'
              f'数字孪生 · DIGITAL TWIN</div>'
            + f'<div style="position:absolute;top:17px;right:44px;font-size:11px;'
              f'color:{T["t4"]}">此处为占位线稿 · 实际渲染真实 URDF 模型</div>'
              f'<div style="position:absolute;bottom:16px;left:16px;right:16px;display:flex;'
              f'gap:22px;font-size:11px;color:{T["t4"]}">'
            + ''.join(f'<span>{k} <span style="color:{T["t2"]};'
                      f'font-variant-numeric:tabular-nums">{v}</span></span>'
                      for k, v in (('底盘 X', '0.000 m'), ('底盘 Y', '0.000 m'),
                                   ('朝向', '128.4°'), ('关节', '6 实时'),
                                   ('雷达', '— 无数据')))
            + '</div></div>')


def build_bigscreen():
    T = DARK
    groups = ''
    for gname, items in BS_METRICS:
        cards = ''.join(
            bs_metric(T, *it) + ''
            if not (len(items) % 2 and i == len(items) - 1)
            else bs_metric(T, *it).replace('<div style="padding:9px 11px 10px;',
                 '<div style="grid-column:1 / -1;padding:9px 11px 10px;', 1)
            for i, it in enumerate(items))
        groups += (
          f'<div style="display:flex;flex-direction:column;gap:7px">'
          f'<div style="display:flex;align-items:center;gap:9px">'
          f'<span style="font-size:11px;font-weight:600;letter-spacing:1.8px;color:{T["t4"]};'
          f'text-transform:uppercase">{gname}</span>'
          f'<span style="flex:1;height:1px;background:{T["divider"]}"></span></div>'
          f'<div style="display:grid;grid-template-columns:repeat(2, minmax(0,1fr));gap:7px">'
          f'{cards}</div></div>')
    status_rows = ''.join(
        f'<div style="display:flex;align-items:center;gap:10px;height:26px">'
        f'<span style="width:6px;height:6px;border-radius:50%;'
        f'background:{T["ok"] if on else T["bad"]}"></span>'
        f'<span style="font-size:12px;color:{T["t3"]}">{k}</span>'
        f'<span style="margin-left:auto;font-size:12px;'
        + (f'color:{T["ok"]}">正常' if on else f'color:{T["bad"]};font-weight:500">离线')
        + '</span></div>' for k, on in BS_STATUS)
    alarms = ''.join(
        f'<div style="display:grid;grid-template-columns:34px 1fr 96px 66px;align-items:center;'
        f'height:40px;border-bottom:1px solid {T["divider"]}">'
        f'<span style="font-size:11px;color:{T["t4"]};font-variant-numeric:tabular-nums">{n}</span>'
        f'<span style="font-size:13px;color:{T["t2"] if s=="ok" else T["t1"]}">{name}</span>'
        f'<span style="font-size:12px;font-variant-numeric:tabular-nums;'
        f'color:{T["t2"] if s=="ok" else T[s]}">{val}</span>'
        f'<span style="text-align:right">{status_tag(T, s)}</span></div>'
        for n, name, val, crit, s in ALARMS)
    btn = (lambda t, kind='': f'<button style="height:38px;padding:0 20px;border-radius:9px;'
           f'font-size:13px;font-weight:500;font-family:{SANS};cursor:pointer;'
           + {'': f'background:{T["surface2"]};border:1px solid {T["border"]};color:{T["t2"]};',
              'ghost': f'background:transparent;border:1px solid {T["border"]};color:{T["t3"]};',
              'danger': f'background:{T["badSoft"]};border:1px solid {T["bad"]}66;'
                        f'color:{T["bad"]};font-weight:600;'}[kind] + f'">{t}</button>')
    return (
      f'<div style="width:1920px;height:1080px;background:{T["bg"]};font-family:{SANS};'
      f'display:flex;flex-direction:column;-webkit-font-smoothing:antialiased">'
      # 顶栏
      f'<div style="height:56px;flex-shrink:0;display:flex;align-items:center;gap:20px;'
      f'padding:0 28px;border-bottom:1px solid {T["divider"]}">'
      f'<span style="display:flex;align-items:center;gap:9px;font-size:13px;color:{T["t3"]};'
      f'letter-spacing:.5px"><span style="width:7px;height:7px;border-radius:50%;'
      f'background:{T["ok"]};box-shadow:0 0 8px {T["ok"]}"></span>系统在线</span>'
      f'<span style="font-size:13px;color:{T["t4"]}">JetRover · 192.168.3.63</span>'
      f'<span style="flex:1;height:1px;background:linear-gradient(90deg,{T["divider"]},'
      f'transparent)"></span>'
      f'<span style="font-size:12px;color:{T["warn"]}">1 告警</span>'
      f'<span style="font-size:12px;color:{T["bad"]}">1 故障</span>'
      f'<div style="display:flex;flex-direction:column;align-items:flex-end;gap:3px">'
      f'<span style="font-size:20px;font-weight:500;color:{T["t1"]};letter-spacing:1.5px;'
      f'font-variant-numeric:tabular-nums">12:27:54</span>'
      f'<span style="font-size:10px;letter-spacing:1.8px;color:{T["t4"]}">'
      f'2026 / 08 / 29 周六</span></div></div>'
      # 主体
      f'<div style="flex:1;min-height:0;display:grid;'
      f'grid-template-columns:396px minmax(0,1fr) 396px;gap:14px;padding:14px 16px">'
      f'<div style="display:flex;flex-direction:column;gap:14px;min-height:0">'
      + bs_panel(T, '电源 · 运行状态', None,
                 f'<div style="display:flex;gap:18px;align-items:center">'
                 f'<div style="display:flex;flex-direction:column;align-items:center;gap:6px">'
                 f'{ring(T, 76, T["ok"])}'
                 f'<span style="font-size:14px;font-weight:600;color:{T["t1"]};'
                 f'font-variant-numeric:tabular-nums">11.74 '
                 f'<span style="font-size:.72em;font-weight:400;color:{T["t3"]}">V</span></span>'
                 f'</div>'
                 f'<div style="flex:1">{status_rows}</div></div>')
      + bs_panel(T, '实时指标', 'real-time',
                 f'<div style="display:flex;flex-direction:column;gap:13px">{groups}</div>',
                 grow=True)
      + '</div>'
      + f'<div style="display:flex;flex-direction:column;min-height:0">{bs_viewport(T)}</div>'
      + f'<div style="display:flex;flex-direction:column;gap:14px;min-height:0">'
      + bs_panel(T, 'CPU 负载', '120s',
                 bs_chart(T, 'cpu', 'CPU', '27.8', '%', '0', '100', '阈值 90 %', 15.6))
      + bs_panel(T, '电池电压', '120s',
                 bs_chart(T, 'volt', '电压', '11.71', 'V', '9.0', '12.6', '阈值 10.0 V', 55.3))
      + bs_panel(T, '告警监控', '6 项', f'<div style="margin:-12px -14px 0">{alarms}</div>',
                 grow=True)
      + '</div></div>'
      # 底栏
      + f'<div style="height:66px;flex-shrink:0;display:flex;align-items:center;gap:10px;'
        f'padding:0 20px;border-top:1px solid {T["divider"]}">'
        f'{btn("复位姿态")}{btn("夹爪张开")}{btn("夹爪闭合")}{btn("蜂鸣提示")}'
        f'<span style="flex:1"></span>{btn("管理系统", "ghost")}{btn("急停 · STOP", "danger")}'
        f'</div></div>')


def build_bigscreen_now():
    """现状还原：四组彩色分区 + 每张卡片带色相渐变底"""
    T = DARK
    G = {'运动': '#2DD4BF', '姿态': '#38BDF8', '算力': '#F59E0B', '系统': '#8B5CF6'}
    def rgba(h, a):
        n = int(h[1:], 16)
        return f'rgba({(n>>16)&255},{(n>>8)&255},{n&255},{a})'
    groups = ''
    for gname, items in BS_METRICS:
        c = G[gname]
        cards = ''.join(
          f'<div style="position:relative;padding:5px 8px 6px;border-radius:8px;'
          f'border:1px solid {rgba(c,.16)};background:linear-gradient(155deg,{rgba(c,.16)},'
          f'transparent 58%);overflow:hidden">'
          f'<div style="display:flex;align-items:center;justify-content:space-between">'
          f'<span style="font-size:9px;color:#94A3B8;letter-spacing:.5px">{label}</span>'
          f'<span style="width:4px;height:4px;border-radius:50%;background:{c}"></span></div>'
          f'<div style="display:flex;align-items:baseline;gap:2px">'
          f'<span style="font:600 17px/1.1 {SANS};color:#F1F5F9;'
          f'font-variant-numeric:tabular-nums">{val}</span>'
          f'<span style="font-size:9px;color:#64748B">{unit}</span></div>'
          + (f'<div style="height:2px;margin-top:3px;background:rgba(255,255,255,.06);'
             f'border-radius:1px"><div style="width:{min(100,bar)}%;height:2px;background:{c};'
             f'border-radius:1px"></div></div>' if bar is not None else '')
          + '</div>' for label, val, unit, bar, exc in items)
        groups += (f'<div style="margin-bottom:8px">'
                   f'<div style="display:flex;align-items:center;gap:7px;font-size:9px;'
                   f'font-weight:600;letter-spacing:1.5px;color:#94A3B8;text-transform:uppercase;'
                   f'margin-bottom:3px">'
                   f'<span style="width:5px;height:5px;border-radius:50%;background:{c};'
                   f'box-shadow:0 0 8px {c}"></span>{gname}'
                   f'<span style="flex:1;height:1px;background:linear-gradient(90deg,'
                   f'rgba(255,255,255,.12),transparent)"></span></div>'
                   f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">{cards}</div>'
                   f'</div>')
    srows = ''.join(
        f'<div style="display:flex;align-items:center;gap:9px;font-size:11px;padding:2px 0">'
        f'<span style="width:7px;height:7px;border-radius:50%;'
        f'background:{"#34D399" if on else "#F43F5E"};box-shadow:0 0 7px '
        f'{"rgba(52,211,153,.7)" if on else "rgba(244,63,94,.7)"}"></span>'
        f'<span style="color:#94A3B8">{k}</span>'
        f'<b style="margin-left:auto;font-weight:500;font-size:12px;'
        f'color:{"#34D399" if on else "#F43F5E"}">{"正常" if on else "离线"}</b></div>'
        for k, on in BS_STATUS)
    arows = ''.join(
        f'<tr><td style="padding:7px 4px;font-size:11px;color:#64748B;'
        f'font-variant-numeric:tabular-nums">{n}</td>'
        f'<td style="padding:7px 4px;font-size:12px;color:#CBD5E1">{name}</td>'
        f'<td style="padding:7px 4px;font-size:12px;color:{"#34D399" if s=="ok" else "#F43F5E"}">'
        f'<span style="display:inline-block;width:7px;height:7px;border-radius:50%;'
        f'background:{"#34D399" if s=="ok" else "#F43F5E"};margin-right:6px"></span>'
        f'{"正常" if s=="ok" else "告警"}</td></tr>'
        for n, name, val, crit, s in ALARMS)
    pan = (lambda t, r, b, grow=False:
           f'<section style="{"flex:1;min-height:0;" if grow else ""}'
           f'background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.07);'
           f'border-radius:12px;display:flex;flex-direction:column;overflow:hidden">'
           f'<div style="height:34px;display:flex;align-items:center;gap:10px;padding:0 16px;'
           f'font-size:13px;font-weight:600;color:#CBD5E1;'
           f'border-bottom:1px solid rgba(255,255,255,.05)">'
           f'<span style="width:3px;height:13px;border-radius:2px;'
           f'background:linear-gradient(#38BDF8,#0EA5E9);box-shadow:0 0 8px rgba(56,189,248,.6)">'
           f'</span>{t}'
           + (f'<span style="margin-left:auto;font-size:10px;letter-spacing:1.5px;color:#475569">'
              f'{r}</span>' if r else '')
           + f'</div><div style="padding:10px 12px;flex:1;min-height:0;overflow:hidden">{b}'
             f'</div></section>')
    return (
      f'<div style="width:1920px;height:1080px;background:#080B12;font-family:{SANS};'
      f'display:flex;flex-direction:column;color:#F1F5F9">'
      f'<div style="height:48px;display:flex;align-items:center;gap:22px;padding:0 24px;'
      f'border-bottom:1px solid rgba(255,255,255,.06)">'
      f'<span style="display:flex;align-items:center;gap:8px;font-size:13px;color:#94A3B8">'
      f'<span style="width:7px;height:7px;border-radius:50%;background:#34D399;'
      f'box-shadow:0 0 8px #34D399"></span>系统在线</span>'
      f'<span style="flex:1;height:1px;background:linear-gradient(90deg,rgba(56,189,248,.18),'
      f'transparent)"></span>'
      f'<div style="display:flex;flex-direction:column;align-items:flex-end">'
      f'<span style="font:500 16px/1.1 {SANS};letter-spacing:1.5px;'
      f'font-variant-numeric:tabular-nums">12:27:54</span>'
      f'<span style="font-size:10px;color:#556072;letter-spacing:1.5px;margin-top:3px">'
      f'2026/08/29周六</span></div></div>'
      f'<div style="flex:1;min-height:0;display:grid;grid-template-columns:350px 1fr 350px;'
      f'gap:10px;padding:10px">'
      f'<div style="display:flex;flex-direction:column;gap:10px;min-height:0">'
      + pan('电源 · 运行状态', None,
            f'<div style="display:flex;gap:12px;align-items:center">'
            f'{ring(T, 76, "#5EEAD4")}<div style="flex:1">{srows}</div></div>')
      + pan('实时指标', 'REAL-TIME', groups, grow=True)
      + '</div>'
      + f'<div style="position:relative;border:1px solid rgba(255,255,255,.08);'
        f'border-radius:12px;background:#06090F;display:flex;align-items:center;'
        f'justify-content:center;color:#475569;font-size:13px">数字孪生 · 3D 视口</div>'
      + f'<div style="display:flex;flex-direction:column;gap:10px;min-height:0">'
      + pan('CPU 负载趋势', '120s',
            f'<svg width="100%" height="120" viewBox="0 0 300 74" preserveAspectRatio="none">'
            f'<path d="{SPARK["cpu"][0]}" fill="none" stroke="#38BDF8" stroke-width="1.6"/></svg>')
      + pan('电池电压趋势', '120s',
            f'<svg width="100%" height="120" viewBox="0 0 300 74" preserveAspectRatio="none">'
            f'<path d="{SPARK["volt"][0]}" fill="none" stroke="#5EEAD4" stroke-width="1.6"/></svg>')
      + pan('告警监控', None,
            f'<table style="width:100%;border-collapse:collapse">'
            f'<thead><tr><th style="text-align:left;font-size:10px;color:#475569;'
            f'letter-spacing:1.2px;padding:0 4px 6px">#</th>'
            f'<th style="text-align:left;font-size:10px;color:#475569;letter-spacing:1.2px;'
            f'padding:0 4px 6px">监控项</th>'
            f'<th style="text-align:left;font-size:10px;color:#475569;letter-spacing:1.2px;'
            f'padding:0 4px 6px">状态</th></tr></thead><tbody>{arows}</tbody></table>', grow=True)
      + '</div></div>'
      + f'<div style="height:60px;display:flex;align-items:center;gap:10px;padding:0 16px;'
        f'border-top:1px solid rgba(255,255,255,.06)">'
      + ''.join(f'<button style="height:36px;padding:0 18px;border-radius:8px;'
                f'background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);'
                f'color:#CBD5E1;font-size:13px;font-family:{SANS}">{t}</button>'
                for t in ('复位姿态', '夹爪张开', '夹爪闭合', '蜂鸣提示'))
      + f'<span style="flex:1"></span>'
        f'<button style="height:36px;padding:0 18px;border-radius:8px;background:transparent;'
        f'border:1px solid rgba(255,255,255,.1);color:#94A3B8;font-size:13px;'
        f'font-family:{SANS}">管理系统</button>'
        f'<button style="height:36px;padding:0 18px;border-radius:8px;'
        f'background:rgba(244,63,94,.15);border:1px solid rgba(244,63,94,.5);color:#F43F5E;'
        f'font-size:13px;font-weight:600;font-family:{SANS}">急停 · STOP</button>'
        f'</div></div>')


main()
