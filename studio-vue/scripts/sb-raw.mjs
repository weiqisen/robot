#!/usr/bin/env node
// 把 /snack_butler/state 的原始 JSON 整个打出来——调试用，不做任何格式化。
// 需要看某个具体字段到底有没有、是什么值时用它。
//   node scripts/sb-raw.mjs              # 全量
//   node scripts/sb-raw.mjs detections   # 只看某个顶层键
import WebSocket from 'ws'
const HOST = process.env.ROBOT || '192.168.3.63'
const key = process.argv[2]
const ws = new WebSocket(`ws://${HOST}:9090`)
const t = setTimeout(() => { console.error('✗ 超时'); process.exit(1) }, 8000)
ws.on('open', () => ws.send(JSON.stringify(
  { op: 'subscribe', topic: '/snack_butler/state', type: 'std_msgs/msg/String', throttle_rate: 200 })))
ws.on('message', b => {
  const m = JSON.parse(b.toString())
  if (m.op !== 'publish') return
  clearTimeout(t)
  const s = JSON.parse(m.msg.data)
  console.log(JSON.stringify(key ? s[key] : s, null, 2))
  ws.close(); process.exit(0)
})
