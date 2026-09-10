#!/usr/bin/env node
// 抓取调试：记录目标坐标和实际下探位置，算偏差。
// 用法：node scripts/sb-grasp-debug.mjs pick red
//       node scripts/sb-grasp-debug.mjs pick_at 320 120
import WebSocket from 'ws'
const HOST = process.env.ROBOT || '192.168.3.63'
const [,, action, ...args] = process.argv

if (!action || !['pick', 'pick_at'].includes(action)) {
  console.error('用法: node sb-grasp-debug.mjs pick <label>')
  console.error('      node sb-grasp-debug.mjs pick_at <u> <v>')
  process.exit(1)
}

const ws = new WebSocket(`ws://${HOST}:9090`)
const send = o => ws.send(JSON.stringify(o))
let targetXYZ = null, graspXYZ = null, detsBefore = []

ws.on('open', () => {
  send({ op: 'subscribe', topic: '/snack_butler/state', type: 'std_msgs/msg/String', throttle_rate: 100 })
})

ws.on('message', buf => {
  const m = JSON.parse(buf.toString())
  if (m.op !== 'publish' || m.topic !== '/snack_butler/state') return
  const s = JSON.parse(m.msg.data)

  // 记录识别前的检测结果
  if (s.state === 'DETECT' && !detsBefore.length) {
    detsBefore = s.detections || []
  }

  // GRASP 状态开始时，记录目标坐标
  if (s.state === 'GRASP' && s.target && !targetXYZ) {
    targetXYZ = s.target.xyz
    console.log('【目标坐标】', targetXYZ, '  label=', s.target.label)
    console.log('  grasp_z_offset=', s.cfg.grasp_z_offset, '  实际合爪 z=', targetXYZ[2] + s.cfg.grasp_z_offset)
  }

  // 打印所有状态变化，方便调试
  const line = `state=${s.state}  step=${s.step || '—'}  ee=${s.ee && s.ee.xyz ? JSON.stringify(s.ee.xyz.map(v => v.toFixed(3))) : '—'}`
  if (line !== ws._lastLine) {
    console.log(line)
    ws._lastLine = line
  }

  // 下探时记录末端坐标
  if (s.state === 'GRASP' && s.step && (s.step.includes('下探') || s.step.includes('预抓取')) && s.ee && s.ee.xyz) {
    if (!graspXYZ) {
      graspXYZ = s.ee.xyz
      console.log('【夹爪位置】', graspXYZ)
      if (targetXYZ) {
        const dx = (graspXYZ[0] - targetXYZ[0]) * 1000
        const dy = (graspXYZ[1] - targetXYZ[1]) * 1000
        const dz = (graspXYZ[2] - targetXYZ[2]) * 1000
        const dxy = Math.sqrt(dx*dx + dy*dy)
        console.log('【偏差】x方向', dx.toFixed(1), 'mm  y方向', dy.toFixed(1), 'mm  z方向', dz.toFixed(1), 'mm')
        console.log('        水平偏差', dxy.toFixed(1), 'mm')
      }
    }
  }

  // 回到 IDLE 就退出
  if (targetXYZ && graspXYZ && s.state === 'IDLE') {
    console.log('【流程结束】state=', s.state, '  step=', s.step || '—')
    ws.close()
    process.exit(0)
  }
})

// 等订阅建立后发命令
setTimeout(() => {
  const cmd = action === 'pick'
    ? { action: 'pick', label: args[0] }
    : { action: 'pick_at', u: +args[0], v: +args[1] }
  console.log('发送命令:', JSON.stringify(cmd))
  send({ op: 'publish', topic: '/snack_butler/cmd', msg: { data: JSON.stringify(cmd) } })
}, 500)

setTimeout(() => {
  console.error('✗ 超时 40s')
  ws.close()
  process.exit(1)
}, 40000)
