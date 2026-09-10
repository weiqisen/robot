#!/usr/bin/env node
// 视觉抓取命令行探针。
// 调抓取时不想每次都开浏览器点——这里直连 rosbridge，读 /snack_butler/state、
// 发 /snack_butler/cmd，把结果打在终端上。
//
//   node scripts/sb.mjs state                     # 打一次状态就退
//   node scripts/sb.mjs watch [秒]                # 持续跟状态变化
//   node scripts/sb.mjs probe <u> <v>             # 只算不抓：报 base_link 坐标
//   node scripts/sb.mjs cmd '{"action":"..."}'    # 发任意命令，跟状态到空闲
//
// 环境变量：ROBOT=192.168.3.63
import WebSocket from 'ws'

const HOST = process.env.ROBOT || '192.168.3.63'
const URL = `ws://${HOST}:9090`
const STATE = '/snack_butler/state'
const CMD = '/snack_butler/cmd'

const [, , verb = 'state', ...rest] = process.argv

function connect() {
  return new Promise((res, rej) => {
    const ws = new WebSocket(URL)
    const t = setTimeout(() => { ws.terminate(); rej(new Error(`连不上 ${URL}（6s 超时）`)) }, 6000)
    ws.on('open', () => { clearTimeout(t); res(ws) })
    ws.on('error', e => { clearTimeout(t); rej(e) })
  })
}

const send = (ws, o) => ws.send(JSON.stringify(o))

function subState(ws, cb) {
  send(ws, { op: 'subscribe', topic: STATE, type: 'std_msgs/msg/String', throttle_rate: 200 })
  ws.on('message', buf => {
    let m
    try { m = JSON.parse(buf.toString()) } catch { return }
    if (m.op !== 'publish' || m.topic !== STATE) return
    try { cb(JSON.parse(m.msg.data)) } catch {}
  })
}

const pubCmd = (ws, obj) =>
  send(ws, { op: 'publish', topic: CMD, msg: { data: JSON.stringify(obj) } })

// 状态里最该盯的几项，压成一行
function line(s) {
  const ee = s.ee || {}
  const xyz = ee.xyz ? ee.xyz.map(v => v.toFixed(3)).join(',') : '—'
  return [
    `state=${s.state}`,
    `step=${s.step || '—'}`,
    `dets=${(s.detections || []).length}`,
    `ee=[${xyz}]`,
    s.last_error ? `err=${s.last_error}` : '',
  ].filter(Boolean).join('  ')
}

function dumpFull(s) {
  const c = s.cfg || {}
  console.log('--- 状态 ---')
  console.log(line(s))
  console.log('--- 标定 ---')
  console.log(`cam_fix(地面标定)   : ${s.cam_fix ? '已标定 ✓' : '未标定 ✗  ← 抓空的头号原因'}`)
  console.log(`servo_map_calibrated: ${c.servo_map_calibrated ? '已标定' : '未标定'}`)
  console.log(`require_calibration : ${c.require_calibration}`)
  if (s.servo_map) console.log(`servo dirs/centers  : ${JSON.stringify(s.servo_map.dirs)} / ${s.servo_map.centers.map(Math.round).join(',')}`)
  console.log('--- 几何 ---')
  for (const k of ['table_z', 'grasp_z_offset', 'grasp_clearance', 'approach_h', 'lift_h', 'tool_len', 'assume_object_h'])
    if (k in c) console.log(`${k.padEnd(20)}: ${c[k]}`)
  console.log('--- 夹爪 ---')
  for (const k of ['gripper_open', 'gripper_close', 'gripper_time'])
    if (k in c) console.log(`${k.padEnd(20)}: ${c[k]}`)
  console.log('--- 统计 ---')
  console.log(JSON.stringify(s.stats || {}))
  const d = s.detections || []
  if (d.length) {
    console.log('--- 当前检测 ---')
    for (const x of d)
      console.log(`  ${String(x.label).padEnd(7)} xyz=[${(x.xyz || []).map(v => v.toFixed(3)).join(', ')}]  src=${x.src}  area=${x.area}  angle=${x.angle_px}`)
  }
}

const ws = await connect().catch(e => { console.error('✗', e.message); process.exit(1) })

if (verb === 'state') {
  const t = setTimeout(() => { console.error('✗ 6s 内没收到 /snack_butler/state —— 节点没在跑'); process.exit(2) }, 6000)
  subState(ws, s => { clearTimeout(t); dumpFull(s); ws.close(); process.exit(0) })

} else if (verb === 'watch') {
  const secs = +(rest[0] || 60)
  let last = ''
  subState(ws, s => { const l = line(s); if (l !== last) { last = l; console.log(new Date().toLocaleTimeString(), l) } })
  setTimeout(() => { ws.close(); process.exit(0) }, secs * 1000)

} else if (verb === 'probe') {
  const [u, v] = rest.map(Number)
  if (!Number.isFinite(u) || !Number.isFinite(v)) { console.error('用法: probe <u> <v>'); process.exit(1) }
  subState(ws, s => {
    if (s.step && /探针|probe/i.test(s.step)) console.log('→', s.step)
  })
  pubCmd(ws, { action: 'probe', u, v })
  setTimeout(() => { ws.close(); process.exit(0) }, 4000)

} else if (verb === 'cmd') {
  let obj
  try { obj = JSON.parse(rest.join(' ')) } catch (e) { console.error('JSON 解析失败:', e.message); process.exit(1) }
  let last = '', idle = 0
  subState(ws, s => {
    const l = line(s)
    if (l !== last) { last = l; console.log(new Date().toLocaleTimeString(), l) }
    // 连续几拍都 IDLE 就认为动作做完了
    idle = (s.state === 'IDLE' && !s._first) ? idle + 1 : 0
  })
  setTimeout(() => pubCmd(ws, obj), 400)     // 等订阅建立，免得漏掉开头几拍
  const secs = +(process.env.WAIT || 40)
  setTimeout(() => { ws.close(); process.exit(0) }, secs * 1000)

} else {
  console.error(`未知命令 ${verb}。可用: state | watch | probe | cmd`)
  process.exit(1)
}
