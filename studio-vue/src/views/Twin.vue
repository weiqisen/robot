<script setup>
import { ref, watch, onMounted, onBeforeUnmount, reactive, computed } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { ColladaLoader } from 'three/examples/jsm/loaders/ColladaLoader.js'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import URDFLoader from 'urdf-loader'
import { useRos, quatToEuler, deg } from '../composables/useRos'
const props = defineProps({ bare: { type: Boolean, default: false } })
const { state, actions } = useRos()

const host = ref(null)
const loading = ref(true), loadErr = ref('')
const tools = reactive({ lidar: true, grid: true, points: false, ik: false, tags: true })
const info = reactive({ ox: '0.000', oy: '0.000', yaw: '0.0', scanN: '—', pcN: '—', jointN: '—',
                        eex: '—', eey: '—', eez: '—' })

// 3D 模型旁边的实时数字：关节角来自 /joint_states，脉冲来自 /servo_states
const CN = { joint1: '底座', joint2: '大臂', joint3: '小臂', joint4: '腕俯仰', joint5: '腕自转', r_joint: '夹爪' }
const jointRows = computed(() => {
  const js = state.joints, sv = state.servos || []
  const rad = js ? Object.fromEntries((js.name || []).map((n, i) => [n, js.position[i]])) : {}
  const pulse = Object.fromEntries(sv.map(x => [x.id, x.position]))
  return SERVO_MAP.map(m => ({
    id: m.id, cn: CN[m.joint] || m.joint,
    deg: rad[m.joint] == null ? null : deg(rad[m.joint]),
    pulse: pulse[m.id] ?? null,
  }))
})
const jetson = computed(() => state.jetson)
const battV = computed(() => (state.batt != null ? (state.batt / 1000).toFixed(2) : '—'))

let renderer, scene, camera, controls, world, grid, robot, raf
let lidarPoints = null
const SERVO_MAP = [{ id: 1, joint: 'joint1' }, { id: 2, joint: 'joint2' }, { id: 3, joint: 'joint3' }, { id: 4, joint: 'joint4' }, { id: 5, joint: 'joint5' }, { id: 10, joint: 'r_joint' }]

function init() {
  const el = host.value
  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
  renderer.setClearColor(0x070a0e, 1)
  // 不做色调映射的话，金属高光会直接削顶成一块平的饱和色 —— 看着就是塑料。
  // ACES 把高光滚降下来，反射的明暗过渡才留得住。曝光补一点，抵消 ACES 整体压暗。
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.15
  el.appendChild(renderer.domElement)
  scene = new THREE.Scene(); scene.fog = new THREE.Fog(0x070a0e, 4, 14)
  const pmrem = new THREE.PMREMGenerator(renderer)
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture
  camera = new THREE.PerspectiveCamera(48, 1, 0.01, 100); camera.position.set(0.9, 0.8, 0.9)
  controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.target.set(0, 0.2, 0)
  // 金属的样子来自「反射环境」，不是「被灯照亮」。半球光给的是均匀漫反射，
  // 开大了等于往模型上糊一层平光，反射全被冲淡 —— 所以压到很低，只用来托暗部，
  // 主要交给上面那张 RoomEnvironment。再加一盏背侧轮廓光，金属边缘要有那道亮线。
  scene.add(new THREE.HemisphereLight(0xbfd4ff, 0x1a1f26, 0.28))
  const key = new THREE.DirectionalLight(0xffffff, 1.5); key.position.set(2, 4, 3); scene.add(key)
  const rim = new THREE.DirectionalLight(0x9fc4ff, 0.9); rim.position.set(-2.5, 1.5, -2); scene.add(rim)
  world = new THREE.Group(); world.rotation.x = -Math.PI / 2; scene.add(world)
  grid = new THREE.GridHelper(10, 40, 0x2a3340, 0x161b22); grid.rotation.x = Math.PI / 2; world.add(grid)
  fit(); loop()
  const loader = new URDFLoader()
  loader.loadMeshCb = (path, mgr, done) => {
    const ext = path.split('.').pop().toLowerCase()
    if (ext === 'stl') new STLLoader(mgr).load(path, g => { g.computeVertexNormals(); done(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0xcfd6de, metalness: .25, roughness: .65 }))) }, undefined, () => done(null))
    else if (ext === 'dae') new ColladaLoader(mgr).load(path, r => done(r.scene), undefined, () => done(null))
    else done(null)
  }
  loader.load('model/robot.web.urdf', rb => {
    robot = rb
    robot.traverse(o => {
      if (!o.isMesh || !o.material) return
      const mname = (o.material.name || '').toLowerCase()
      let std
      if (mname === 'green') {
        // 车身/机械臂是「亮绿阳极氧化铝」，不是喷漆也不是塑料。取色自官网图
        // jetrover.webp：中调 #41A553~#67B973、亮面 #70F682，色相 131°(偏黄的鲜绿)，
        // 明度 0.65~0.83 —— 是个又亮又饱和的绿，不是深祖母绿。
        // 阳极氧化 = 染色氧化层直接长在铝上，没有清漆层，所以不能加 clearcoat；
        // 观感是缎面(satin)：高光清脆但不「湿」，粗糙度中等。
        // metalness 留在 .6 而不是拉满：氧化层本身有色，实物暗部仍是明确的绿，
        // 拉到 .9 以上暗部只剩环境反射，绿会掉成灰黑。
        std = new THREE.MeshStandardMaterial({
          color: 0x45c95e, metalness: .6, roughness: .33, envMapIntensity: 1.25,
        })
      } else if (mname === 'black') {
        // 显示屏外壳/雷达罩/夹爪：实测 #171815，很暗且几乎不反光，是哑光件
        std = new THREE.MeshStandardMaterial({ color: 0x15171a, metalness: .25, roughness: .68, envMapIntensity: 1.05 })
      } else if (mname === 'white') {
        std = new THREE.MeshStandardMaterial({ color: 0xd2d6d8, metalness: .5, roughness: .38, envMapIntensity: 1.25 })
      } else if (mname === 'gray' || mname === 'darkgray') {
        std = new THREE.MeshStandardMaterial({ color: 0x6e7478, metalness: .55, roughness: .4, envMapIntensity: 1.25 })
      } else if (!mname && o.material.color) {
        // URDF 里有一个匿名材质(深度相机外壳，rgba 0.753 银灰)。以前它掉进 else
        // 被刷成深蓝灰，实物是 #CCCECE 的银色件 —— 匿名的就尊重 URDF 自己写的颜色。
        std = new THREE.MeshStandardMaterial({ metalness: .55, roughness: .35, envMapIntensity: 1.25 })
        std.color.copy(o.material.color)
      } else {
        std = new THREE.MeshStandardMaterial({ color: 0x2b333a, metalness: .45, roughness: .5, envMapIntensity: 1.15 })
      }
      o.material = std
    })
    world.add(robot); loading.value = false
    info.jointN = Object.keys(robot.joints).filter(n => robot.joints[n].jointType !== 'fixed').length + ' 关节'
    makeJointTags()
    makeScreen()
    // 给 scripts/shot.mjs 的场景探针用：改完能直接查对象在不在、位姿对不对，
    // 不用靠肉眼看图猜。只是几个引用，不额外占资源。
    window.__twin = { scene, robot, camera, renderer, world, THREE, get screenMesh() { return screenMesh } }
  }, undefined, e => { loadErr.value = String(e); loading.value = false })
}
// ---- 车身显示屏：把 #jetson 那页的核心遥测画上去 ----
// URDF 里没有「屏幕」这个 link，那块面板是 back_shell_black_link 网格的一部分。
// 位姿是从 STL 解出来的：法向 (-0.9113, 0, 0.4116)（朝车后上方，离竖直 24.3°）。
// 沿这个法向按面积分层后，玻璃面是深度 +0.1733 处那个「只有 2 个三角形」的大矩形 ——
// 138.7 x 87.0mm、长宽比 1.594(16:10)，base_link 系中心 (-0.1469, 0.0002, 0.1136)；
// 它外面 +0.178/+0.179 还有两圈边框，所以贴图只抬 0.8mm，正好嵌在边框里。
// （最初取的是面积最大的共面组 +0.1680，那是面板底板，被边框埋掉 8.9mm 才不显示。）
const SCREEN_W = 800, SCREEN_H = 502      // canvas 像素，1.594 贴合玻璃面长宽比
let screenCv = null, screenTex = null, screenMesh = null, screenTimer = null

function makeScreen() {
  const parent = (robot.links && robot.links.base_link) || robot   // 根 link 是 base_footprint，差 0.116m
  screenCv = document.createElement('canvas')
  screenCv.width = SCREEN_W; screenCv.height = SCREEN_H
  screenTex = new THREE.CanvasTexture(screenCv)
  screenTex.colorSpace = THREE.SRGBColorSpace
  screenTex.anisotropy = renderer.capabilities.getMaxAnisotropy()
  // 屏幕是自发光的 UI，不该被 ACES 压暗，也不该吃环境反射 —— 所以用 Basic + toneMapped:false
  screenMesh = new THREE.Mesh(
    new THREE.PlaneGeometry(0.1366, 0.0857),
    new THREE.MeshBasicMaterial({ map: screenTex, toneMapped: false }))
  // 用三根轴显式搭基，不用 setFromUnitVectors —— 后者绕法向的滚转是任意的，画面会歪
  const zAx = new THREE.Vector3(-0.9113, 0, 0.4116).normalize()   // 屏幕朝外
  const yAx = new THREE.Vector3(0.4116, 0, 0.9113).normalize()    // 屏幕向上
  const xAx = new THREE.Vector3().crossVectors(yAx, zAx).normalize()
  screenMesh.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(xAx, yAx, zAx))
  // 玻璃面在 +0.1733，但外面还有两圈边框伸到 +0.1789 —— 只抬 0.8mm 会被埋掉 4.8mm，
  // 屏幕位置朝向纹理全对却什么都看不见。抬 6.5mm，露出边框约 0.9mm。
  screenMesh.position.set(-0.1469, 0.0002, 0.1136).addScaledVector(zAx, 0.0065)
  parent.add(screenMesh)
  drawScreen()
  screenTimer = setInterval(drawScreen, 500)   // 遥测约 1Hz，500ms 足够跟上
}

const SC = { bg: '#070b10', line: 'rgba(255,255,255,.09)', dim: '#7b8798',
             fg: '#F1F5F9', ok: '#34D399', warn: '#F59E0B', bad: '#F43F5E', acc: '#38BDF8' }

function drawScreen() {
  if (!screenCv) return
  const g = screenCv.getContext('2d'), W = SCREEN_W, H = SCREEN_H
  const j = state.jetson
  const cpu = j && j.cpu && j.cpu.length ? Math.round(j.cpu.reduce((a, c) => a + c.load, 0) / j.cpu.length) : 0
  const gpu = j && j.gpu != null ? j.gpu : 0
  const temp = j && j.temps ? Math.max(...Object.values(j.temps)) : 0
  const ram = j && j.ram_total ? Math.round(j.ram_used / j.ram_total * 100) : 0
  const volt = state.batt != null ? state.batt / 1000 : null
  const lv = (v, w, b) => (v >= b ? SC.bad : v >= w ? SC.warn : SC.acc)

  g.fillStyle = SC.bg; g.fillRect(0, 0, W, H)

  // 顶栏
  g.fillStyle = 'rgba(56,189,248,.07)'; g.fillRect(0, 0, W, 66)
  g.fillStyle = SC.line; g.fillRect(0, 65, W, 1)
  g.font = '600 27px Inter, system-ui, sans-serif'; g.fillStyle = SC.fg
  g.textBaseline = 'middle'; g.textAlign = 'left'
  g.fillText('JETSON ORIN NANO', 26, 34)
  g.textAlign = 'right'
  g.font = '400 21px Inter, system-ui, sans-serif'; g.fillStyle = SC.dim
  g.fillText((j && j.power_mode) || '--', W - 52, 34)
  g.beginPath(); g.arc(W - 28, 34, 8, 0, 6.284)
  g.fillStyle = j ? SC.ok : SC.bad; g.fill()

  // 2x2 四块：有量程的才配条
  const tiles = [
    { l: 'CPU', v: cpu, u: '%', p: cpu, c: lv(cpu, 75, 90) },
    { l: 'GPU', v: gpu, u: '%', p: gpu, c: lv(gpu, 75, 90) },
    { l: '温度', v: temp.toFixed(1), u: '℃', p: Math.min(100, temp), c: lv(temp, 75, 85) },
    { l: '内存', v: ram, u: '%', p: ram, c: lv(ram, 80, 92) },
  ]
  const gx = 26, gy = 88, gw = (W - 52 - 18) / 2, gh = 134
  tiles.forEach((t, i) => {
    const x = gx + (i % 2) * (gw + 18), y = gy + Math.floor(i / 2) * (gh + 16)
    g.fillStyle = 'rgba(255,255,255,.035)'; g.fillRect(x, y, gw, gh)
    g.textAlign = 'left'; g.textBaseline = 'middle'
    g.font = '500 21px Inter, system-ui, sans-serif'; g.fillStyle = SC.dim
    g.fillText(t.l, x + 18, y + 27)
    g.font = '600 60px Inter, system-ui, sans-serif'; g.fillStyle = t.c
    g.fillText(String(t.v), x + 18, y + 76)
    const tw = g.measureText(String(t.v)).width
    g.font = '400 23px Inter, system-ui, sans-serif'; g.fillStyle = SC.dim
    g.fillText(t.u, x + 24 + tw, y + 88)
    g.fillStyle = 'rgba(255,255,255,.09)'; g.fillRect(x + 18, y + gh - 26, gw - 36, 6)
    g.fillStyle = t.c; g.fillRect(x + 18, y + gh - 26, (gw - 36) * Math.min(100, t.p) / 100, 6)
  })

  // 底栏：电压 + 内存绝对值
  const by = gy + 2 * gh + 16 + 16
  g.fillStyle = SC.line; g.fillRect(26, by - 14, W - 52, 1)
  g.textAlign = 'left'; g.font = '500 22px Inter, system-ui, sans-serif'; g.fillStyle = SC.dim
  g.fillText('电池', 26, by + 22)
  g.font = '600 32px Inter, system-ui, sans-serif'
  g.fillStyle = volt == null ? SC.dim : volt < 10.6 ? SC.bad : volt < 11 ? SC.warn : SC.ok
  g.fillText(volt == null ? '--.-' : volt.toFixed(2) + ' V', 92, by + 22)
  g.textAlign = 'right'; g.font = '500 22px Inter, system-ui, sans-serif'; g.fillStyle = SC.dim
  g.fillText(j && j.ram_total ? (j.ram_used / 1024).toFixed(1) + ' / ' + (j.ram_total / 1024).toFixed(1) + ' GB' : '--',
    W - 26, by + 22)

  screenTex.needsUpdate = true
}

// 容器尺寸变化就重新适配。原来只在 init() 里调一次 + 听 window resize，
// 而 init() 跑的时候布局还没稳定，clientHeight 可能只有十几像素；
// 此后窗口不再变化，画布就永远停在那个高度 —— 模型照画（draw call 正常），
// 只是被挤成顶部一条缝，看着像「3D 没渲染」。改成盯容器本身。
function fit() {
  const el = host.value
  if (!el || !renderer) return
  const w = el.clientWidth, h = el.clientHeight
  if (w < 2 || h < 2) return          // 还没布局好，等下一次回调
  renderer.setSize(w, h)
  camera.aspect = w / h
  camera.updateProjectionMatrix()
}
function loop() { raf = requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera) }

// 关节反馈 -> 模型
watch(() => state.joints, m => {
  if (!robot || !m) return
  let n = 0
  for (let i = 0; i < m.name.length; i++) {
    const name = m.name[i], p = m.position[i]
    const j = robot.joints[name]
    if (!j || !Number.isFinite(p) || dragging) continue
    let lo = -Math.PI, hi = Math.PI
    if (j.limit && +j.limit.lower !== +j.limit.upper) { lo = +j.limit.lower; hi = +j.limit.upper }
    robot.setJointValue(name, Math.max(lo, Math.min(hi, p)))
    n++
  }
  info.jointN = n + ' 关节实时'
  const w = eeWorld()
  info.eex = w.x.toFixed(3); info.eey = w.y.toFixed(3); info.eez = w.z.toFixed(3)
})
watch(() => state.odom, m => {
  if (!robot || !m) return
  const p = m.pose.pose.position, e = quatToEuler(m.pose.pose.orientation)
  robot.position.set(p.x, p.y, 0); robot.rotation.set(0, 0, e.yaw)
  info.ox = p.x.toFixed(3); info.oy = p.y.toFixed(3); info.yaw = deg(e.yaw).toFixed(1)
})
watch(() => state.scan, s => {
  if (!tools.lidar || !s || !robot) { if (lidarPoints) lidarPoints.visible = false; return }
  const pts = []
  for (let i = 0; i < s.ranges.length; i++) { const d = s.ranges[i]; if (!isFinite(d) || d <= s.range_min || d > s.range_max) continue; const a = s.angle_min + i * s.angle_increment; pts.push(d * Math.cos(a), d * Math.sin(a), 0.18) }
  info.scanN = (pts.length / 3 | 0) + ' 点'
  const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3))
  if (lidarPoints) { lidarPoints.geometry.dispose(); lidarPoints.geometry = geo; lidarPoints.visible = true }
  else { lidarPoints = new THREE.Points(geo, new THREE.PointsMaterial({ color: 0x2e9bff, size: 0.03 })); robot.add(lidarPoints) }
})

// ---- 关节控制滑块 ----
const jval = reactive({ 1: 500, 2: 500, 3: 500, 4: 500, 5: 500, 10: 500 })
let sq = {}, st = null
function sendServo(id, pos) { sq[id] = pos; if (st) return; st = setTimeout(() => { st = null; const position = Object.entries(sq).map(([i, p]) => ({ id: +i, position: +p })); sq = {}; actions.setServos(position, 0.8) }, 60) }
function onSlider(id, v) { jval[id] = v; sendServo(id, v); driveModelJoint(SERVO_MAP.find(m => m.id === id).joint, v) }
function driveModelJoint(name, pulse) {
  if (!robot || !robot.joints[name]) return
  const j = robot.joints[name]; let lo = -1.57, hi = 1.57
  if (j.limit && +j.limit.lower !== +j.limit.upper) { lo = +j.limit.lower; hi = +j.limit.upper }
  robot.setJointValue(name, lo + (pulse / 1000) * (hi - lo))
}
function syncArm() { actions.once('/controller_manager/servo_states', 'servo_controller_msgs/msg/ServoStateList', m => { (m.servo_state || []).forEach(s => { if (jval[s.id] != null) { jval[s.id] = s.position; const mp = SERVO_MAP.find(x => x.id === s.id); if (mp) driveModelJoint(mp.joint, s.position) } }) }) }

// ---- CCD IK ----
const IK_CHAIN = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5']
const EE_OFFSET = new THREE.Vector3(0, 0, 0.08)
let ikTarget = null, dragging = false
const raycaster = new THREE.Raycaster(), ndc = new THREE.Vector2()
// ---- 关节标注：J1..J5 + 夹爪，直接挂在对应关节上，跟着一起动 ----
const TAGS = [
  { joint: 'joint1', t: 'J1', sub: '底座回转' },
  { joint: 'joint2', t: 'J2', sub: '大臂俯仰' },
  { joint: 'joint3', t: 'J3', sub: '小臂俯仰' },
  { joint: 'joint4', t: 'J4', sub: '腕俯仰 · 相机' },
  { joint: 'joint5', t: 'J5', sub: '腕自转' },
  { joint: 'r_joint', t: '夹爪', sub: 'ID 10' },
]
let tagGroup = null

function tagSprite(title, sub) {
  // 画到 canvas 再当贴图。用 devicePixelRatio 放大再缩回去，免得在高分屏上糊。
  const S = 4, W = 168 * S, H = 52 * S
  const c = document.createElement('canvas'); c.width = W; c.height = H
  const x = c.getContext('2d')
  x.scale(S, S)
  const r = 9, w = 168, h = 52
  x.fillStyle = 'rgba(8,12,18,.82)'
  x.strokeStyle = 'rgba(56,189,248,.55)'
  x.lineWidth = 1.2
  x.beginPath(); x.roundRect(1, 1, w - 2, h - 2, r); x.fill(); x.stroke()
  x.fillStyle = '#38BDF8'
  x.font = '700 21px ui-monospace, Menlo, monospace'
  x.textBaseline = 'middle'
  x.fillText(title, 13, 19)
  x.fillStyle = 'rgba(226,232,240,.82)'
  x.font = '400 14px "PingFang SC", "Microsoft YaHei", sans-serif'
  x.fillText(sub, 13, 38)
  const tex = new THREE.CanvasTexture(c)
  tex.minFilter = THREE.LinearFilter
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({
    map: tex, depthTest: false, depthWrite: false, transparent: true }))
  sp.scale.set(0.115, 0.036, 1)     // sizeAttenuation 关掉后这是屏幕比例
  sp.material.sizeAttenuation = false
  sp.renderOrder = 999
  return sp
}

function makeJointTags() {
  if (tagGroup) { tagGroup.parent && tagGroup.parent.remove(tagGroup) }
  tagGroup = new THREE.Group()
  for (const g of TAGS) {
    const j = robot.joints[g.joint]
    if (!j) continue
    const sp = tagSprite(g.t, g.sub)
    sp.position.set(0, 0, 0.055)     // 从关节原点往外挑一点，别压在结构里
    j.add(sp)
    tagGroup.add(sp)                  // 只用来统一控制显隐
  }
  setTagsVisible(tools.tags)
}
function setTagsVisible(v) { tagGroup && tagGroup.children.forEach(o => (o.visible = v)) }

function eeWorld() { const j = robot && robot.joints['joint5']; return j ? j.localToWorld(EE_OFFSET.clone()) : new THREE.Vector3() }
function makeTarget() { ikTarget = new THREE.Mesh(new THREE.SphereGeometry(0.02, 16, 16), new THREE.MeshBasicMaterial({ color: 0xffcf33 })); ikTarget.add(new THREE.Mesh(new THREE.SphereGeometry(0.03, 16, 16), new THREE.MeshBasicMaterial({ color: 0xffcf33, transparent: true, opacity: .25 }))); scene.add(ikTarget); ikTarget.position.copy(eeWorld()) }
function jWorldPos(n) { return new THREE.Vector3().setFromMatrixPosition(robot.joints[n].matrixWorld) }
function jWorldAxis(n) { const j = robot.joints[n]; return (j.axis || new THREE.Vector3(0, 0, 1)).clone().applyQuaternion(j.getWorldQuaternion(new THREE.Quaternion())).normalize() }
function solveCCD(target) {
  if (!robot) return
  for (let it = 0; it < 12; it++) {
    for (let i = IK_CHAIN.length - 1; i >= 0; i--) {
      const name = IK_CHAIN[i], j = robot.joints[name]; robot.updateMatrixWorld(true)
      const jp = jWorldPos(name), axis = jWorldAxis(name), ee = eeWorld()
      const toEE = ee.clone().sub(jp), toT = target.clone().sub(jp)
      toEE.sub(axis.clone().multiplyScalar(toEE.dot(axis))); toT.sub(axis.clone().multiplyScalar(toT.dot(axis)))
      if (toEE.lengthSq() < 1e-8 || toT.lengthSq() < 1e-8) continue
      toEE.normalize(); toT.normalize()
      let ang = Math.acos(Math.max(-1, Math.min(1, toEE.dot(toT))))
      if (new THREE.Vector3().crossVectors(toEE, toT).dot(axis) < 0) ang = -ang
      let lo = -3.14, hi = 3.14; if (j.limit && +j.limit.lower !== +j.limit.upper) { lo = +j.limit.lower; hi = +j.limit.upper }
      robot.setJointValue(name, Math.max(lo, Math.min(hi, (j.angle || 0) + ang * 0.5)))
    }
    robot.updateMatrixWorld(true); if (eeWorld().distanceTo(target) < 0.005) break
  }
  const position = IK_CHAIN.map(name => { const j = robot.joints[name], mp = SERVO_MAP.find(x => x.joint === name); let lo = -1.57, hi = 1.57; if (j.limit && +j.limit.lower !== +j.limit.upper) { lo = +j.limit.lower; hi = +j.limit.upper }; const pulse = Math.max(0, Math.min(1000, Math.round(1000 * ((j.angle || 0) - lo) / (hi - lo)))); jval[mp.id] = pulse; return { id: mp.id, position: pulse } })
  if (!ikSend) ikSend = setTimeout(() => { ikSend = null; actions.setServos(position, 0.3) }, 120)
}
let ikSend = null
function ptrDown(e) { if (!tools.ik || !ikTarget) return; const r = renderer.domElement.getBoundingClientRect(); ndc.x = (e.clientX - r.left) / r.width * 2 - 1; ndc.y = -((e.clientY - r.top) / r.height) * 2 + 1; raycaster.setFromCamera(ndc, camera); if (raycaster.intersectObject(ikTarget, true).length) { dragging = true; controls.enabled = false } }
function ptrMove(e) { if (!dragging) return; const r = renderer.domElement.getBoundingClientRect(); ndc.x = (e.clientX - r.left) / r.width * 2 - 1; ndc.y = -((e.clientY - r.top) / r.height) * 2 + 1; raycaster.setFromCamera(ndc, camera); const n = camera.getWorldDirection(new THREE.Vector3()).negate(); const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(n, ikTarget.position); const hit = new THREE.Vector3(); if (raycaster.ray.intersectPlane(plane, hit)) { ikTarget.position.copy(hit); solveCCD(hit) } }
function ptrUp() { if (dragging) { dragging = false; controls.enabled = true } }

function toggleTool(k) {
  tools[k] = !tools[k]
  if (k === 'grid') grid.visible = tools.grid
  if (k === 'lidar' && lidarPoints) lidarPoints.visible = tools.lidar
  if (k === 'tags') setTagsVisible(tools.tags)
  if (k === 'ik') { if (tools.ik) { if (!ikTarget) makeTarget(); ikTarget.visible = true; ikTarget.position.copy(eeWorld()) } else if (ikTarget) ikTarget.visible = false }
}
// 屏幕在车尾，默认机位在车前 —— 不给个入口就永远看不到它。
// 机位按屏幕的实际世界位姿现算：车会随 /odom 转，写死的坐标转两下就偏了。
const viewIdx = ref(0)
function resetView() {
  viewIdx.value ^= 1
  if (viewIdx.value === 1 && screenMesh) {
    const p = screenMesh.getWorldPosition(new THREE.Vector3())
    const n = screenMesh.getWorldDirection(new THREE.Vector3())
    camera.position.copy(p).addScaledVector(n, 0.38)
    controls.target.copy(p)
  } else {
    viewIdx.value = 0
    camera.position.set(0.9, 0.8, 0.9); controls.target.set(0, 0.2, 0)
  }
}

let hostRO = null
onMounted(() => {
  init()
  hostRO = new ResizeObserver(fit)
  hostRO.observe(host.value)
  window.addEventListener('resize', fit)
  renderer.domElement.addEventListener('pointerdown', ptrDown)
  renderer.domElement.addEventListener('pointermove', ptrMove)
  window.addEventListener('pointerup', ptrUp)
})
onBeforeUnmount(() => {
  cancelAnimationFrame(raf)
  if (hostRO) hostRO.disconnect()
  window.removeEventListener('resize', fit); window.removeEventListener('pointerup', ptrUp)
  if (screenTimer) clearInterval(screenTimer)
  if (screenMesh) { screenMesh.geometry.dispose(); screenMesh.material.dispose() }
  if (screenTex) screenTex.dispose()
  renderer && renderer.dispose()
})
</script>

<template>
  <div class="twin">
    <div ref="host" class="scene" />
    <div v-if="loading" class="loading"><a-spin size="large" /><div style="margin-top:12px">加载模型…</div></div>
    <div v-if="loadErr" class="loading">模型加载失败：{{ loadErr }}</div>

    <div class="tools">
      <div v-for="t in [['lidar', '雷达'], ['grid', '网格'], ['points', '点云'], ['tags', '标注'], ['ik', 'IK']]" :key="t[0]"
        :class="['glass tbtn', { on: tools[t[0]] }]" @click="toggleTool(t[0])">{{ t[1] }}</div>
      <div class="glass tbtn" :title="viewIdx ? '切回默认视角' : '看车尾屏幕'"
        @click="resetView">{{ viewIdx ? '车头' : '视角' }}</div>
    </div>

    <div v-if="!bare" class="glass panel tele">
      <h4>实时遥测</h4>
      <div class="kv"><span>底盘 X</span><b>{{ info.ox }} m</b></div>
      <div class="kv"><span>底盘 Y</span><b>{{ info.oy }} m</b></div>
      <div class="kv"><span>朝向</span><b>{{ info.yaw }}°</b></div>
      <div class="kv"><span>雷达</span><b>{{ info.scanN }}</b></div>
      <div class="kv"><span>关节</span><b>{{ info.jointN }}</b></div>
      <div class="sep" />
      <div class="kv"><span>末端 X</span><b>{{ info.eex }} m</b></div>
      <div class="kv"><span>末端 Y</span><b>{{ info.eey }} m</b></div>
      <div class="kv"><span>末端 Z</span><b>{{ info.eez }} m</b></div>
      <div class="sep" />
      <div class="kv"><span>电池</span><b>{{ battV }} V</b></div>
      <div class="kv"><span>CPU</span><b>{{ jetson ? Math.round(jetson.cpu.reduce((a, c) => a + c.load, 0) / jetson.cpu.length) : '—' }} %</b></div>
      <div class="kv"><span>结温</span><b>{{ jetson && jetson.temps ? Math.max(...Object.values(jetson.temps)).toFixed(1) : '—' }} °C</b></div>
    </div>

    <div v-if="!bare" class="glass panel joints">
      <h4>关节实时</h4>
      <div class="jt jt-h"><span>关节</span><b>角度</b><i>脉冲</i></div>
      <div v-for="r in jointRows" :key="r.id" class="jt">
        <span>J{{ r.id }} {{ r.cn }}</span>
        <b>{{ r.deg == null ? '--' : r.deg.toFixed(1) + '°' }}</b>
        <i>{{ r.pulse == null ? '--' : r.pulse }}</i>
      </div>
    </div>

    <div v-if="!bare" class="glass panel ctrl">
      <h4>关节控制 <a-button size="small" ghost @click="syncArm">读取姿态</a-button></h4>
      <div v-for="m in SERVO_MAP" :key="m.id" class="jr"><span>{{ m.id === 10 ? '夹爪' : 'J' + m.id }}</span>
        <a-slider :value="jval[m.id]" :min="0" :max="1000" @change="v => onSlider(m.id, v)" style="flex:1" /></div>
      <div class="hint">模型实时跟随 /joint_states 与 /odom。拖滑块下发实物；开 IK 后拖黄点逆解算控制。</div>
    </div>
  </div>
</template>

<style scoped>
.twin { position: absolute; inset: 0; overflow: hidden; background: #070a0e; }
.scene { position: absolute; inset: 0; }
.scene :deep(canvas) { display: block; }
.loading { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; color: rgba(255,255,255,.6); font-family: ui-monospace, monospace; }
.glass { background: rgba(14,17,22,.55); backdrop-filter: blur(16px); border: 1px solid rgba(255,255,255,.12); color: #eef2f6; }
.tools { position: absolute; right: 14px; top: 14px; z-index: 10; display: flex; flex-direction: column; gap: 8px; }
.tbtn { width: 44px; height: 40px; display: flex; align-items: center; justify-content: center; font-size: 11px; border-radius: 11px; cursor: pointer; color: rgba(255,255,255,.6); }
.tbtn.on { color: #fff; box-shadow: inset 0 0 0 1px #2e9bff; background: rgba(46,155,255,.16); }
.panel { position: absolute; z-index: 10; border-radius: 12px; padding: 14px; }
.sep { height: 1px; background: rgba(255,255,255,.12); margin: 8px 0; }
.joints { left: 14px; bottom: 14px; min-width: 210px; }
.jt { display: flex; align-items: baseline; gap: 8px; font-size: 12px; padding: 3px 0;
  font-variant-numeric: tabular-nums; }
.jt span { flex: 1; color: rgba(255,255,255,.6); }
.jt b { width: 58px; text-align: right; font-weight: 600; }
.jt i { width: 42px; text-align: right; font-style: normal; color: rgba(255,255,255,.45);
  font-family: ui-monospace, monospace; }
.jt-h { color: rgba(255,255,255,.4); border-bottom: 1px solid rgba(255,255,255,.12);
  padding-bottom: 5px; margin-bottom: 3px; }
.jt-h b, .jt-h i { font-weight: 400; color: rgba(255,255,255,.4); }
.panel h4 { color: rgba(255,255,255,.6); font-size: 11px; letter-spacing: 1px; margin: 0 0 10px; display: flex; align-items: center; gap: 8px; }
.tele { left: 14px; bottom: 14px; width: 200px; }
.ctrl { right: 14px; bottom: 14px; width: 250px; }
.kv { display: flex; justify-content: space-between; font-size: 12px; padding: 4px 0; }
.kv b, .jr { font-family: ui-monospace, monospace; }
.jr { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.jr span { font-size: 11px; color: rgba(255,255,255,.6); width: 34px; }
.hint { font-size: 10px; color: rgba(255,255,255,.35); margin-top: 8px; line-height: 1.6; }
@media (max-width: 820px) { .tele { width: 150px; } .ctrl { width: 190px; } }
@media (max-width: 560px) { .tele { display: none; } }
</style>
