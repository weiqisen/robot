<script setup>
import { ref, watch, onMounted, onBeforeUnmount, onActivated, onDeactivated, reactive, computed, nextTick } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { ColladaLoader } from 'three/examples/jsm/loaders/ColladaLoader.js'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import URDFLoader from 'urdf-loader'
import { useRos, quatToEuler, deg, videoUrl } from '../composables/useRos'
const props = defineProps({ bare: { type: Boolean, default: false } })
const emit = defineEmits(['focus'])
const { state, actions, HOST, VISION_VIDEO_PORT } = useRos()

const host = ref(null)
const loading = ref(true), loadErr = ref('')
const tools = reactive({ lidar: true, grid: true, points: false, ik: false, tags: true,
  workspace: true, selfbody: true, dimensions: true, angles: false, cameraFov: false, axes: true, detections: true, detectionFeed: false })

// ---- 外观参数：集中一份，材质面板直接改它，改完实时生效并存 localStorage ----
// 默认值来自官网实物图 jetrover.webp 取色（见 git log fix(twin) 那几条）。
const MAT_DEFAULT = {
  green:  { cn: '车身绿（阳极氧化铝）', color: '#45c95e', metalness: 0.60, roughness: 0.33, env: 1.25 },
  black:  { cn: '黑色件（屏壳/雷达/夹爪）', color: '#15171a', metalness: 0.25, roughness: 0.68, env: 1.05 },
  silver: { cn: '深度相机外壳', color: '#c0c0c0', metalness: 0.55, roughness: 0.35, env: 1.25 },
  white:  { cn: '白色件', color: '#d2d6d8', metalness: 0.50, roughness: 0.38, env: 1.25 },
  gray:   { cn: '灰色件', color: '#6e7478', metalness: 0.55, roughness: 0.40, env: 1.25 },
  other:  { cn: '其它', color: '#2b333a', metalness: 0.45, roughness: 0.50, env: 1.15 },
}
const LIGHT_DEFAULT = { exposure: 1.15, hemi: 0.28, key: 1.50, rim: 0.90 }
const LS_KEY = 'twin.look.v1'

const clone = o => JSON.parse(JSON.stringify(o))
const mat = reactive(clone(MAT_DEFAULT))
const lit = reactive(clone(LIGHT_DEFAULT))

// 三层来源，后面的盖前面的：
//   代码默认值 → 车上保存的那份(所有设备共用) → 本机未保存的草稿
// 走机器人 IP 而不是相对路径：从 Mac 的 vite dev server 打开时，
// 相对路径会打到 :5273 上去，拿不到车上的配置。
const LOOK_API = `http://${HOST}:8000/api/look`
const look = reactive({ dirty: false, saving: false, msg: '', onRobot: false })
let serverLook = null
let quiet = false           // 程序化写入时别触发 watch 里的"标脏 + 存草稿"

function mergeLook(src) {
  if (!src) return
  // 逐字段合并，不整体覆盖 —— 以后加了新材质档位，旧存档也不会把它抹掉
  for (const k in mat) if (src.mat && src.mat[k]) Object.assign(mat[k], src.mat[k])
  if (src.lit) Object.assign(lit, src.lit)
  if (src.screen) Object.assign(screenCfg, src.screen)
}

async function loadLook() {
  quiet = true
  try {
    const r = await fetch(LOOK_API, { cache: 'no-store' })
    if (r.ok) { serverLook = await r.json(); mergeLook(serverLook); look.onRobot = true }
  } catch (e) { /* 车没在线 / dev server 没这个接口，退回本地 */ }
  let draft = null
  try { draft = JSON.parse(localStorage.getItem(LS_KEY) || 'null') } catch (e) { /* 存档坏了就忽略 */ }
  if (draft) { mergeLook(draft); look.dirty = true; look.msg = '有未保存的本机改动' }
  quiet = false
  applyLook()
}

async function saveLook() {
  look.saving = true; look.msg = ''
  try {
    const r = await fetch(LOOK_API, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mat, lit, screen: screenCfg }),
    })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`)
    serverLook = JSON.parse(JSON.stringify({ mat, lit, screen: screenCfg }))
    try { localStorage.removeItem(LS_KEY) } catch (e) { /* 无痕模式 */ }
    look.dirty = false; look.onRobot = true; look.msg = '已保存到机器人'
  } catch (e) {
    look.msg = '保存失败：' + e.message
  } finally { look.saving = false }
}

// 放弃本机改动，回到车上那份（没保存过就回代码默认值）
function revertLook() {
  quiet = true
  for (const k in MAT_DEFAULT) Object.assign(mat[k], MAT_DEFAULT[k])
  Object.assign(lit, LIGHT_DEFAULT); Object.assign(screenCfg, SCREEN_DEFAULT)
  mergeLook(serverLook)
  try { localStorage.removeItem(LS_KEY) } catch (e) { /* 无痕模式 */ }
  look.dirty = false; look.msg = ''
  quiet = false
  applyLook()
}

const matOpen = ref(false)

// ---- YOLO 识别画面小窗 ----
// snack_butler 已经把带框的标注图发到 /snack_butler/image_result，
// web_video_server 转成 MJPEG。直接给 <img> 一个流地址就行，不用自己逐帧拉。
// 关掉时必须把 src 清空：MJPEG 是永不结束的长连接，挂着会占满浏览器并发额度。
const detFeedStamp = ref(0)
const detFeedSrc = computed(() => (tools.detectionFeed
  ? videoUrl(HOST, VISION_VIDEO_PORT, '/snack_butler/image_result', detFeedStamp.value) : ''))
const detFeedStat = computed(() => {
  const sb = state.snack
  if (!sb) return '视觉节点未运行'
  const n = (sb.detections || []).length
  const yolo = sb.detector
  if (yolo?.yolo_error) return 'YOLO 加载失败'
  if (yolo?.yolo_loading) return 'YOLO 加载中…'
  return `${n} 个目标 · ${sb.state || '—'}`
})
function reloadDetFeed() { detFeedStamp.value = Date.now() }
watch(() => tools.detectionFeed, v => { if (v) reloadDetFeed() })
const matGroups = {}          // 档位名 -> 这一档下所有 material，改参数时批量刷
let hemiL = null, keyL = null, rimL = null
let robotReady = false
const info = reactive({ ox: '0.000', oy: '0.000', yaw: '0.0', scanN: '—', pcN: '—', jointN: '—',
                        eex: '—', eey: '—', eez: '—', detN: '无' })

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
let workspaceGroup = null, selfbodyGroup = null, dimensionsGroup = null
let anglesGroup = null, cameraFovGroup = null, axesGroup = null
let detectGroup = null      // YOLO 检测结果的 3D 投影
const SERVO_MAP = [{ id: 1, joint: 'joint1' }, { id: 2, joint: 'joint2' }, { id: 3, joint: 'joint3' }, { id: 4, joint: 'joint4' }, { id: 5, joint: 'joint5' }, { id: 10, joint: 'r_joint' }]

function init() {
  const el = host.value
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
  renderer.setClearColor(0x070a0e, 1)
  // 不做色调映射的话，金属高光会直接削顶成一块平的饱和色 —— 看着就是塑料。
  // ACES 把高光滚降下来，反射的明暗过渡才留得住。曝光补一点，抵消 ACES 整体压暗。
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = lit.exposure
  el.appendChild(renderer.domElement)
  scene = new THREE.Scene(); scene.fog = new THREE.Fog(0x070a0e, 4, 14)
  const pmrem = new THREE.PMREMGenerator(renderer)
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture
  camera = new THREE.PerspectiveCamera(48, 1, 0.01, 100); camera.position.set(0.9, 0.8, 0.9)
  controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.target.set(0, 0.2, 0)
  // 金属的样子来自「反射环境」，不是「被灯照亮」。半球光给的是均匀漫反射，
  // 开大了等于往模型上糊一层平光，反射全被冲淡 —— 所以压到很低，只用来托暗部，
  // 主要交给上面那张 RoomEnvironment。再加一盏背侧轮廓光，金属边缘要有那道亮线。
  hemiL = new THREE.HemisphereLight(0xbfd4ff, 0x1a1f26, lit.hemi); scene.add(hemiL)
  keyL = new THREE.DirectionalLight(0xffffff, lit.key); keyL.position.set(2, 4, 3); scene.add(keyL)
  rimL = new THREE.DirectionalLight(0x9fc4ff, lit.rim); rimL.position.set(-2.5, 1.5, -2); scene.add(rimL)
  world = new THREE.Group(); world.rotation.x = -Math.PI / 2; scene.add(world)
  grid = new THREE.GridHelper(10, 40, 0x2a3340, 0x161b22); grid.rotation.x = Math.PI / 2; world.add(grid)
  fit(); loop()
  // urdf-loader 的 load() 回调在 URDF **解析完**就触发，而 STL 网格是异步加载的。
  // 在那个回调里 traverse 根本遍历不到网格 —— 网格随后带着 loader 默认的
  // MeshPhongMaterial 进来，而 Phong 压根不吃 metalness/roughness/envMap，
  // 于是所有材质设置全部空转、模型永远是塑料感。必须等 LoadingManager 全部完成再上材质。
  const mgr = new THREE.LoadingManager()
  const loader = new URDFLoader(mgr)
  loader.loadMeshCb = (path, m, done) => {
    const ext = path.split('.').pop().toLowerCase()
    if (ext === 'stl') new STLLoader(m).load(path, g => { g.computeVertexNormals(); done(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0xcfd6de, metalness: .25, roughness: .65 }))) }, undefined, () => done(null))
    else if (ext === 'dae') new ColladaLoader(m).load(path, r => done(r.scene), undefined, () => done(null))
    else done(null)
  }

  // 把 URDF 材质名映射到可编辑的档位，并登记进 matGroups 供面板批量刷。
  // 可重入：重复调用会先清空登记表，不会越积越多。
  function skinRobot() {
    for (const k in matGroups) delete matGroups[k]
    robot.traverse(o => {
      if (!o.isMesh || !o.material) return
      // 辅助图层的 mesh 打了 userData.helperLayer，跳过不换材质
      if (o.userData.helperLayer) return
      const mname = (o.material.name || '').toLowerCase()
      // 绿=车身/机械臂(阳极氧化铝)；空名的那个是深度相机外壳(URDF 里 rgba 0.753)
      const key = mname === 'green' ? 'green'
        : mname === 'black' ? 'black'
        : mname === 'white' ? 'white'
        : (mname === 'gray' || mname === 'darkgray') ? 'gray'
        : !mname ? 'silver' : 'other'
      const c = mat[key]
      const std = new THREE.MeshStandardMaterial({
        color: c.color, metalness: c.metalness, roughness: c.roughness, envMapIntensity: c.env,
      })
      ;(matGroups[key] || (matGroups[key] = [])).push(std)
      o.material = std
    })
  }

  function onRobotReady() {
    if (!robot || robotReady) return
    robotReady = true
    skinRobot()
    makeJointTags()
    makeScreen()
    loading.value = false
    // 给 scripts/shot.mjs 的场景探针用：改完能直接查对象在不在、位姿对不对
    window.__twin = { scene, robot, camera, renderer, world, THREE, matGroups,
                      get screenMesh() { return screenMesh },
                      get tagGroup() { return tagGroup },
                      get tagSprites() { return tagSprites },
                      get detectGroup() { return detectGroup } }
  }
  mgr.onLoad = onRobotReady
  loadLook()

  loader.load('model/robot.web.urdf', rb => {
    robot = rb
    world.add(robot)
    info.jointN = Object.keys(robot.joints).filter(n => robot.joints[n].jointType !== 'fixed').length + ' 关节'

    // 辅助图层挂在 base_link 下，跟着车一起走一起转。
    // 必须是 base_link 而不是 robot 根节点：根 link 是 base_footprint（轮子接地面），
    // 比 base_link 低 0.116m，挂错了整套图层会整体下沉一个车高。
    const anchor = (robot.links && robot.links.base_link) || robot
    workspaceGroup = new THREE.Group()
    selfbodyGroup = new THREE.Group()
    dimensionsGroup = new THREE.Group()
    anglesGroup = new THREE.Group()
    cameraFovGroup = new THREE.Group()
    axesGroup = new THREE.Group()
    detectGroup = new THREE.Group()
    for (const g of [workspaceGroup, selfbodyGroup, dimensionsGroup,
                     anglesGroup, cameraFovGroup, axesGroup, detectGroup]) anchor.add(g)

    // 构建辅助图层（单位：米，base_link 坐标系）
    buildWorkspace(workspaceGroup)
    buildSelfBody(selfbodyGroup)
    buildDimensions(dimensionsGroup)
    buildAxes(axesGroup)
    // 给所有辅助图层的 mesh 打标记，skinRobot 会跳过它们
    for (const g of [workspaceGroup, selfbodyGroup, dimensionsGroup, axesGroup, detectGroup]) {
      g.traverse(o => { if (o.isMesh) o.userData.helperLayer = true })
    }
    for (const [k, g] of [['workspace', workspaceGroup], ['selfbody', selfbodyGroup],
                          ['dimensions', dimensionsGroup], ['angles', anglesGroup],
                          ['cameraFov', cameraFovGroup], ['axes', axesGroup],
                          ['detections', detectGroup]]) g.visible = tools[k]
    syncDetections()      // 首帧就把已有的检测结果画出来

    // 兜底：万一这台车的 URDF 没有任何外部网格，onLoad 可能已经先触发过了
    if (mgr.itemsLoaded >= mgr.itemsTotal) onRobotReady()
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
  startPolling()
  drawScreen()
  restartScreenTimer()
}

const SC = { bg: '#070b10', line: 'rgba(255,255,255,.09)', dim: '#7b8798',
             fg: '#F1F5F9', ok: '#34D399', warn: '#F59E0B', bad: '#F43F5E', acc: '#38BDF8' }

// 屏幕上放什么，可在材质面板里选，跟材质一起存到车上
const SCREEN_BLOCKS = [
  ['telemetry', 'Jetson 仪表盘'], ['snack', '抓取状态'],
  ['camera', '相机画面'], ['desktop', 'Ubuntu 桌面'],
]
const SCREEN_DEFAULT = { block: 'telemetry' }
const screenCfg = reactive(clone(SCREEN_DEFAULT))

// 相机和桌面都从控制台自己的 :8000 同源取单帧 JPEG。
// 相机不能直连 web_video_server 的 :8080：那是跨源，而它 GET 时并不发
// Access-Control-Allow-Origin（HEAD 时发，很有迷惑性）—— 实测带
// crossOrigin 的 <img> 永远加载不出来，不带又会污染画布，
// 而被污染的 canvas 当 WebGL 纹理会抛 SecurityError。所以服务端转发一道。
//
// 双缓冲：新帧先加载到一个临时 Image，onload 之后才换上去。
// 直接复用同一个 Image 改 src 的话，加载期间 naturalWidth 会归零，
// 正好被定时重绘撞上 —— 那就是桌面"断断续续黑屏"的原因。
const frames = { camera: null, desktop: null }
const POLL_GAP = { camera: 350, desktop: 900 }
let pollSeq = 0, pageActive = true
function startPolling() {
  const kind = screenCfg.block
  pollSeq++                       // 让上一轮轮询自然退出
  if (!pageActive || (kind !== 'camera' && kind !== 'desktop')) return
  const my = pollSeq
  const step = () => {
    if (my !== pollSeq || screenCfg.block !== kind) return
    const im = new Image()
    im.crossOrigin = 'anonymous'
    im.onload = () => { frames[kind] = im; setTimeout(step, POLL_GAP[kind]) }
    im.onerror = () => setTimeout(step, 1500)
    im.src = `http://${HOST}:8000/api/${kind}.jpg?t=${Date.now()}`
  }
  step()
}

// 重绘节奏跟着内容走：相机要跟上流，其余 1Hz 的数据 500ms 足够
const SCREEN_FPS = { camera: 160, desktop: 500, telemetry: 500, snack: 500 }
function restartScreenTimer() {
  if (screenTimer) clearInterval(screenTimer)
  screenTimer = setInterval(drawScreen, SCREEN_FPS[screenCfg.block] || 500)
}
watch(() => screenCfg.block, () => { startPolling(); restartScreenTimer(); drawScreen() })

const pad2 = n => String(n).padStart(2, '0')
function drawFit(g, img, W, H) {
  if (!img || !img.naturalWidth) return false
  const k = Math.min(W / img.naturalWidth, H / img.naturalHeight)
  const w = img.naturalWidth * k, h = img.naturalHeight * k
  try { g.drawImage(img, (W - w) / 2, (H - h) / 2, w, h) } catch (e) { return false }
  return true
}
function drawNoSignal(g, W, H, txt) {
  g.textAlign = 'center'; g.textBaseline = 'middle'
  g.font = '500 26px Inter, system-ui, sans-serif'; g.fillStyle = SC.dim
  g.fillText(txt, W / 2, H / 2)
}
// 一块「标签 + 大数字 + 进度条」的瓦片
function tile(g, x, y, w, h, label, val, unit, pct, color) {
  g.fillStyle = 'rgba(255,255,255,.035)'; g.fillRect(x, y, w, h)
  g.textAlign = 'left'; g.textBaseline = 'middle'
  g.font = '500 20px Inter, system-ui, sans-serif'; g.fillStyle = SC.dim
  g.fillText(label, x + 16, y + 24)
  g.font = '600 52px Inter, system-ui, sans-serif'; g.fillStyle = color
  g.fillText(String(val), x + 16, y + 66)
  const tw = g.measureText(String(val)).width
  g.font = '400 21px Inter, system-ui, sans-serif'; g.fillStyle = SC.dim
  g.fillText(unit, x + 22 + tw, y + 78)
  if (pct != null) {
    g.fillStyle = 'rgba(255,255,255,.09)'; g.fillRect(x + 16, y + h - 20, w - 32, 5)
    g.fillStyle = color; g.fillRect(x + 16, y + h - 20, (w - 32) * Math.min(100, pct) / 100, 5)
  }
}
// 一行「小标签 + 值」，用于底部密集信息带
function stat(g, x, y, label, val, color) {
  g.textAlign = 'left'; g.textBaseline = 'middle'
  g.font = '400 17px Inter, system-ui, sans-serif'; g.fillStyle = SC.dim
  g.fillText(label, x, y)
  g.font = '600 19px Inter, system-ui, sans-serif'; g.fillStyle = color || SC.fg
  g.fillText(String(val), x + 74, y)
}

function drawHeader(g, W, title, right) {
  g.fillStyle = 'rgba(56,189,248,.07)'; g.fillRect(0, 0, W, 58)
  g.fillStyle = SC.line; g.fillRect(0, 57, W, 1)
  g.textBaseline = 'middle'; g.textAlign = 'left'
  g.font = '600 25px Inter, system-ui, sans-serif'; g.fillStyle = SC.fg
  g.fillText(title, 24, 30)
  g.textAlign = 'right'
  g.font = '400 19px Inter, system-ui, sans-serif'; g.fillStyle = SC.dim
  g.fillText(right, W - 48, 30)
  const d = new Date()
  g.fillText(`${pad2(d.getHours())}:${pad2(d.getMinutes())}`, W - 150, 30)
}

function drawTelemetry(g, W, H) {
  const j = state.jetson
  const cpu = j && j.cpu && j.cpu.length ? Math.round(j.cpu.reduce((a, c) => a + c.load, 0) / j.cpu.length) : 0
  const gpu = j && j.gpu != null ? j.gpu : 0
  const temp = j && j.temps ? Math.max(...Object.values(j.temps)) : 0
  const ram = j && j.ram_total ? Math.round(j.ram_used / j.ram_total * 100) : 0
  const volt = state.batt != null ? state.batt / 1000 : null
  const lv = (v, w, b) => (v >= b ? SC.bad : v >= w ? SC.warn : SC.acc)

  drawHeader(g, W, 'JETSON ORIN NANO', (j && j.power_mode) || '--')
  g.beginPath(); g.arc(W - 26, 30, 7, 0, 6.284); g.fillStyle = j ? SC.ok : SC.bad; g.fill()

  const gw = (W - 48 - 14) / 2, gh = 112
  tile(g, 24, 70, gw, gh, 'CPU', cpu, '%', cpu, lv(cpu, 75, 90))
  tile(g, 24 + gw + 14, 70, gw, gh, 'GPU', gpu, '%', gpu, lv(gpu, 75, 90))
  tile(g, 24, 70 + gh + 12, gw, gh, '温度', temp.toFixed(1), '℃', Math.min(100, temp), lv(temp, 75, 85))
  tile(g, 24 + gw + 14, 70 + gh + 12, gw, gh, '内存', ram, '%', ram, lv(ram, 80, 92))

  // 密集信息带：这些没有量程，配进度条没意义，排成两行六项
  const sy = 70 + 2 * gh + 12 + 26
  g.fillStyle = SC.line; g.fillRect(24, sy - 16, W - 48, 1)
  const up = j && j.uptime ? j.uptime : 0
  const cw = (W - 48) / 3
  stat(g, 24, sy + 6, '运行', up ? `${Math.floor(up / 3600)}h ${Math.floor(up % 3600 / 60)}m` : '--')
  stat(g, 24 + cw, sy + 6, '磁盘', j && j.disk_total ? `${j.disk_used} / ${j.disk_total} G` : '--')
  stat(g, 24 + 2 * cw, sy + 6, '内存', j && j.ram_total ? `${(j.ram_used / 1024).toFixed(1)} / ${(j.ram_total / 1024).toFixed(1)} G` : '--')
  stat(g, 24, sy + 36, '节点', state.counts.nodes || '--')
  stat(g, 24 + cw, sy + 36, '话题', state.counts.topics || '--')
  stat(g, 24 + 2 * cw, sy + 36, '舵机', (state.servos || []).length || '--')

  // 电池单独一行，低压是这台车最常见的故障，值得给个大字
  const by = H - 30
  g.fillStyle = SC.line; g.fillRect(24, by - 24, W - 48, 1)
  g.textAlign = 'left'; g.font = '400 17px Inter, system-ui, sans-serif'; g.fillStyle = SC.dim
  g.fillText('电池', 24, by)
  g.font = '600 30px Inter, system-ui, sans-serif'
  g.fillStyle = volt == null ? SC.dim : volt < 10.6 ? SC.bad : volt < 11 ? SC.warn : SC.ok
  g.fillText(volt == null ? '--.- V' : volt.toFixed(2) + ' V', 88, by)
  const sb = state.snack
  if (sb && sb.low_volt) {
    g.textAlign = 'right'; g.font = '600 20px Inter, system-ui, sans-serif'; g.fillStyle = SC.bad
    g.fillText('低压保护中', W - 24, by)
  }
}

function drawSnack(g, W, H) {
  const sb = state.snack
  drawHeader(g, W, '视觉引导抓取', sb ? sb.state : '节点未运行')
  if (!sb) return drawNoSignal(g, W, H, 'snack_butler 未运行')
  g.textAlign = 'left'; g.textBaseline = 'middle'
  g.font = '600 30px Inter, system-ui, sans-serif'; g.fillStyle = SC.fg
  g.fillText(sb.step || '待命', 24, 96)

  const dets = sb.detections || []
  const reach = dets.filter(d => d.reachable).length
  const gw = (W - 48 - 14) / 2
  tile(g, 24, 128, gw, 104, '识别到', dets.length, '个', null, SC.acc)
  tile(g, 24 + gw + 14, 128, gw, 104, '可抓', reach, '个', null, reach ? SC.ok : SC.dim)

  const t = sb.target
  const ty = 258
  g.fillStyle = SC.line; g.fillRect(24, ty - 12, W - 48, 1)
  g.font = '400 17px Inter, system-ui, sans-serif'; g.fillStyle = SC.dim
  g.fillText('目标', 24, ty + 12)
  g.font = '600 19px Inter, system-ui, sans-serif'; g.fillStyle = SC.fg
  g.fillText(t && t.xyz ? `${t.label}  (${t.xyz[0]}, ${t.xyz[1]}, ${t.xyz[2]})` : '—', 98, ty + 12)
  stat(g, 24, ty + 44, '已抓', (sb.stats && sb.stats.picked) != null ? sb.stats.picked : '--')
  stat(g, 24 + (W - 48) / 3, ty + 44, '失败', (sb.stats && sb.stats.failed) != null ? sb.stats.failed : '--')
  stat(g, 24 + 2 * (W - 48) / 3, ty + 44, '空跑', sb.cfg && sb.cfg.dry_run ? '开' : '关',
    sb.cfg && sb.cfg.dry_run ? SC.warn : SC.fg)

  const by = H - 30
  g.fillStyle = SC.line; g.fillRect(24, by - 24, W - 48, 1)
  g.font = '400 17px Inter, system-ui, sans-serif'; g.fillStyle = SC.dim
  g.fillText('电池', 24, by)
  g.font = '600 30px Inter, system-ui, sans-serif'
  const v = sb.batt_v
  g.fillStyle = v == null ? SC.dim : sb.low_volt ? SC.bad : v < 11 ? SC.warn : SC.ok
  g.fillText(v == null ? '--.- V' : v.toFixed(2) + ' V', 88, by)
  if (sb.low_volt) {
    g.textAlign = 'right'; g.font = '600 20px Inter, system-ui, sans-serif'; g.fillStyle = SC.bad
    g.fillText('低压保护中', W - 24, by)
  }
  if (sb.error) {
    g.textAlign = 'left'; g.font = '400 15px Inter, system-ui, sans-serif'; g.fillStyle = SC.bad
    g.fillText(String(sb.error).slice(0, 58), 24, by - 44)
  }
}

function drawScreen() {
  if (!screenCv) return
  const g = screenCv.getContext('2d'), W = SCREEN_W, H = SCREEN_H
  g.fillStyle = SC.bg; g.fillRect(0, 0, W, H)
  if (screenCfg.block === 'camera') {
    if (!drawFit(g, frames.camera, W, H)) drawNoSignal(g, W, H, '相机无信号')
  } else if (screenCfg.block === 'desktop') {
    if (!drawFit(g, frames.desktop, W, H)) drawNoSignal(g, W, H, '桌面无信号')
  } else if (screenCfg.block === 'snack') {
    drawSnack(g, W, H)
  } else {
    drawTelemetry(g, W, H)
  }
  screenTex.needsUpdate = true
}

// 容器尺寸变化就重新适配。原来只在 init() 里调一次 + 听 window resize，
// 而 init() 跑的时候布局还没稳定，clientHeight 可能只有十几像素；
// 此后窗口不再变化，画布就永远停在那个高度 —— 模型照画（draw call 正常），
// 只是被挤成顶部一条缝，看着像「3D 没渲染」。改成盯容器本身。
// 面板改一个值就整档刷一遍。材质数量很少（6 档几十个 mesh），不值得做增量。
function applyLook() {
  for (const k in mat) {
    const c = mat[k]
    for (const m of matGroups[k] || []) {
      m.color.set(c.color)
      m.metalness = c.metalness; m.roughness = c.roughness; m.envMapIntensity = c.env
      m.needsUpdate = true
    }
  }
  if (renderer) renderer.toneMappingExposure = lit.exposure
  if (hemiL) hemiL.intensity = lit.hemi
  if (keyL) keyL.intensity = lit.key
  if (rimL) rimL.intensity = lit.rim
}
watch([mat, lit, screenCfg], () => {
  applyLook()
  if (quiet) return
  look.dirty = true; look.msg = ''
  // 草稿留在本机，刷新不丢；点「保存到机器人」才成为所有设备共用的那份
  try { localStorage.setItem(LS_KEY, JSON.stringify({ mat, lit, screen: screenCfg })) } catch (e) { /* 无痕模式等 */ }
}, { deep: true })

function resetLook() {
  for (const k in MAT_DEFAULT) Object.assign(mat[k], MAT_DEFAULT[k])
  Object.assign(lit, LIGHT_DEFAULT); Object.assign(screenCfg, SCREEN_DEFAULT)
}

// 导出成可直接粘回本文件 MAT_DEFAULT / LIGHT_DEFAULT 的代码
const exportCode = computed(() => {
  const n = (v, d = 2) => Number(v).toFixed(d)
  const lines = Object.entries(mat).map(([k, c]) =>
    `  ${k.padEnd(7)}{ cn: '${c.cn}', color: '${c.color}', ` +
    `metalness: ${n(c.metalness)}, roughness: ${n(c.roughness)}, env: ${n(c.env)} },`)
    .map(l => l.replace(/^(\s{2}\w+)(\s+)\{/, '$1:$2{'))
  return 'const MAT_DEFAULT = {\n' + lines.join('\n') + '\n}\n' +
    `const LIGHT_DEFAULT = { exposure: ${n(lit.exposure)}, hemi: ${n(lit.hemi)}, ` +
    `key: ${n(lit.key)}, rim: ${n(lit.rim)} }`
})
const copied = ref(false)
function copyCode() {
  const t = exportCode.value
  const done = () => { copied.value = true; setTimeout(() => (copied.value = false), 1600) }
  if (navigator.clipboard) navigator.clipboard.writeText(t).then(done, done)
  else done()
}

function fit() {
  const el = host.value
  if (!el || !renderer) return
  const w = el.clientWidth, h = el.clientHeight
  if (w < 2 || h < 2) return          // 还没布局好，等下一次回调
  renderer.setSize(w, h)
  camera.aspect = w / h
  camera.updateProjectionMatrix()
}
function loop() {
  if (!pageActive || !renderer) { raf = null; return }
  raf = requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera)
}

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
  updateJointAngles()      // 标签第三行的角度跟着刷
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
  updateJointAngles()     // 本地拖动也要刷标签，别等回传
}
function syncArm() { actions.once('/controller_manager/servo_states', 'servo_controller_msgs/msg/ServoStateList', m => { (m.servo_state || []).forEach(s => { if (jval[s.id] != null) { jval[s.id] = s.position; const mp = SERVO_MAP.find(x => x.id === s.id); if (mp) driveModelJoint(mp.joint, s.position) } }) }) }

// 给父组件（大屏）用：拖它自己的滑块时立刻把模型摆过去，不等 /joint_states 回传。
// 舵机走到位要几百毫秒，只靠回传的话模型会明显拖后于滑块。
function setJointByServoId(id, pulse) {
  const mp = SERVO_MAP.find(m => m.id === +id)
  if (mp) driveModelJoint(mp.joint, +pulse)
}
defineExpose({ setJointByServoId })

// ---- CCD IK ----
const IK_CHAIN = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5']
const EE_OFFSET = new THREE.Vector3(0, 0, 0.08)
// ---- 辅助图层（base_link 米制，数值与 snack_butler.py 的 DEFAULT_CONFIG 一致）----
// TABLE_Z：机器人所站的那个台面在 base_link 系里的高度。base_link 在接地面上方
// 0.116m，所以台面是 -0.116 而不是 0 —— snack_butler 的 table_z 就是这个值。
const TABLE_Z = -0.116
// workspace_rel：x/y 是 base_link 绝对坐标，z 是「离台面多高」
const WS_REL = { x: [0.17, 0.32], y: [-0.20, 0.20], z: [-0.03, 0.12] }
// self_body_boxes：底盘顶板 + 麦轮占的盒子，落在里面的检测结果直接丢弃
const SELF_BOX = [0.05, 0.21, -0.17, 0.17, -0.045, 0.08]
const CM = m => (m * 100).toFixed(1) + ' cm'

function boxTriangles(x, y, z) {
  const verts = [
    [x[0], y[0], z[0]], [x[1], y[0], z[0]], [x[1], y[1], z[0]], [x[0], y[1], z[0]],
    [x[0], y[0], z[1]], [x[1], y[0], z[1]], [x[1], y[1], z[1]], [x[0], y[1], z[1]],
  ]
  const faces = [[0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4], [2, 3, 7, 6], [0, 3, 7, 4], [1, 2, 6, 5]]
  const pos = []
  for (const f of faces) {
    const v = f.map(i => verts[i])
    for (const tri of [[0, 1, 2], [0, 2, 3]]) for (const i of tri) pos.push(v[i][0], v[i][1], v[i][2])
  }
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  geo.computeVertexNormals()
  return geo
}

// 半透盒 + 描边。用 MeshBasicMaterial 避免光照影响，toneMapped:false 避免色调映射压暗半透材质。
function shellBox(group, x, y, z, color, fillOpacity) {
  const mesh = new THREE.Mesh(boxTriangles(x, y, z), new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: fillOpacity,
    side: THREE.DoubleSide,
    depthWrite: false,
    depthTest: true,
    toneMapped: false,  // 半透材质不走色调映射，否则会被 ACES 压暗
  }))
  mesh.renderOrder = -1  // 先画盒子，再画模型，这样模型能穿透盒子显示
  mesh.userData.helperLayer = true   // skinRobot 据此跳过，别被换成不透明的车身材质
  group.add(mesh)

  const edge = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(x[1] - x[0], y[1] - y[0], z[1] - z[0])),
    new THREE.LineBasicMaterial({
      color,
      transparent: true,
      opacity: 0.65,
      depthTest: true,
      toneMapped: false,
    }))
  edge.position.set((x[0] + x[1]) / 2, (y[0] + y[1]) / 2, (z[0] + z[1]) / 2)
  group.add(edge)
  return { mesh, edge }
}

function buildWorkspace(group) {
  const x = WS_REL.x, y = WS_REL.y
  const z = [TABLE_Z + WS_REL.z[0], TABLE_Z + WS_REL.z[1]]
  shellBox(group, x, y, z, 0x3fb950, 0.07)
  const tag = layerLabel('可抓取区', `${CM(x[1] - x[0])} × ${CM(y[1] - y[0])} × ${CM(z[1] - z[0])}`, '#3fb950')
  tag.position.set((x[0] + x[1]) / 2, (y[0] + y[1]) / 2, z[1] + 0.03)
  group.add(tag)
}

function buildSelfBody(group) {
  const b = SELF_BOX
  shellBox(group, [b[0], b[1]], [b[2], b[3]], [b[4], b[5]], 0xf85149, 0.09)
  const tag = layerLabel('车身遮挡区', '此范围内的检测结果丢弃', '#f85149')
  tag.position.set((b[0] + b[1]) / 2, b[3] + 0.02, b[5] + 0.02)
  group.add(tag)
}

// 三条高度标尺：安全高度 / 预抓悬停 / 抬起，都从台面量起
function buildDimensions(group) {
  const items = [
    { h: 0.08, c: 0xd29922, t: '安全高度', sub: 'safe_z', cc: '#d29922' },
    { h: 0.07, c: 0xbc8cff, t: '预抓悬停', sub: 'approach_h', cc: '#bc8cff' },
    { h: 0.10, c: 0x56d4dd, t: '抬起高度', sub: 'lift_h', cc: '#56d4dd' },
  ]
  let xo = WS_REL.x[1] + 0.03
  for (const it of items) {
    const y = WS_REL.y[0] - 0.04
    const p1 = new THREE.Vector3(xo, y, TABLE_Z)
    const p2 = new THREE.Vector3(xo, y, TABLE_Z + it.h)
    group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([p1, p2]),
      new THREE.LineBasicMaterial({ color: it.c })))
    for (const p of [p1, p2]) {
      const d = new THREE.Mesh(new THREE.SphereGeometry(0.005, 10, 10),
        new THREE.MeshBasicMaterial({ color: it.c }))
      d.position.copy(p); group.add(d)
    }
    const tag = layerLabel(`${it.t} ${CM(it.h)}`, it.sub, it.cc)
    tag.position.set(xo, y, TABLE_Z + it.h + 0.022)
    group.add(tag)
    xo += 0.035
  }
  // 台面参考线：z=table_z 这个平面是所有高度的基准
  const g = new THREE.GridHelper(0.5, 10, 0x3a4550, 0x232a33)
  g.rotation.x = Math.PI / 2
  g.position.set(0.19, 0, TABLE_Z)
  group.add(g)
  const tag = layerLabel(`台面 z = ${CM(TABLE_Z)}`, 'table_z · 高度基准', '#8b949e')
  tag.position.set(0.19, -0.26, TABLE_Z)
  group.add(tag)
}

function buildAxes(group) {
  const len = 0.12
  for (const ax of [{ d: [len, 0, 0], c: 0xf85149, t: 'X 前', cc: '#f85149' },
                    { d: [0, len, 0], c: 0x3fb950, t: 'Y 左', cc: '#3fb950' },
                    { d: [0, 0, len], c: 0x58a6ff, t: 'Z 上', cc: '#58a6ff' }]) {
    const end = new THREE.Vector3(...ax.d)
    group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), end]),
      new THREE.LineBasicMaterial({ color: ax.c })))
    const cone = new THREE.Mesh(new THREE.ConeGeometry(0.008, 0.022, 10),
      new THREE.MeshBasicMaterial({ color: ax.c }))
    cone.position.copy(end)
    cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), end.clone().normalize())
    group.add(cone)
    const tag = layerLabel(ax.t, 'base_link', ax.cc)
    tag.position.copy(end).multiplyScalar(1.18)
    group.add(tag)
  }
  const o = new THREE.Mesh(new THREE.SphereGeometry(0.008, 12, 12),
    new THREE.MeshBasicMaterial({ color: 0xe6edf3 }))
  group.add(o)
}

// ---- YOLO 检测结果的 3D 投影 ----
// snack_butler 已经把每个检测目标从像素反投影成 base_link 坐标（det.xyz），
// 直接拿来在场景里摆标记就行，不用在前端重算相机外参。
const DET_COLOR = { red: 0xe14b4b, orange: 0xef8c2d, yellow: 0xe8c020,
                    green: 0x43a047, blue: 0x2e7ddb, purple: 0x8e5bc4 }
const DET_CN = { red: '红', orange: '橙', yellow: '黄', green: '绿', blue: '蓝', purple: '紫' }

function clearGroup(g) {
  if (!g) return
  for (let i = g.children.length - 1; i >= 0; i--) {
    const o = g.children[i]
    if (o.geometry) o.geometry.dispose()
    if (o.material) { o.material.map && o.material.map.dispose(); o.material.dispose() }
    g.remove(o)
  }
}

// 检测结果整体重建。目标数量本来就只有几个，逐个 diff 不值当。
function syncDetections() {
  if (!detectGroup) return
  clearGroup(detectGroup)
  const dets = state.snack?.detections || []
  for (const d of dets) {
    if (!Array.isArray(d.xyz) || d.xyz.length !== 3) continue
    const [x, y, z] = d.xyz
    const reachable = !!d.reachable
    const col = DET_COLOR[d.label] ?? (reachable ? 0x43a047 : 0x8b949e)

    // 目标本体：一个小方块，可抓的实心一点、够不着的更透
    const box = new THREE.Mesh(
      new THREE.BoxGeometry(0.028, 0.028, 0.028),
      new THREE.MeshBasicMaterial({ color: col, transparent: true,
        opacity: reachable ? 0.55 : 0.28, toneMapped: false }))
    box.position.set(x, y, z)
    box.userData.helperLayer = true
    detectGroup.add(box)

    // 描边，让位置在深色背景下看得清
    const edge = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(0.028, 0.028, 0.028)),
      new THREE.LineBasicMaterial({ color: col, transparent: true,
        opacity: reachable ? 0.95 : 0.5, toneMapped: false }))
    edge.position.set(x, y, z)
    detectGroup.add(edge)

    // 竖直投影线 + 台面上的落点，判断高度用
    const foot = new THREE.Vector3(x, y, TABLE_Z)
    const drop = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(x, y, z), foot]),
      new THREE.LineDashedMaterial({ color: col, transparent: true, opacity: 0.45,
        dashSize: 0.008, gapSize: 0.006, toneMapped: false }))
    drop.computeLineDistances()      // 虚线必须算一次线长才显示成虚线
    detectGroup.add(drop)
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.012, 0.016, 20),
      new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.5,
        side: THREE.DoubleSide, toneMapped: false }))
    ring.position.copy(foot)
    ring.userData.helperLayer = true
    detectGroup.add(ring)

    // 标签：类别 + 坐标 + 可达性
    const name = DET_CN[d.label] || d.label || '目标'
    const conf = d.confidence != null ? ` ${(d.confidence * 100).toFixed(0)}%` : ''
    const tag = layerLabel(name + conf,
      `${CM(x)} ${CM(y)} · ${reachable ? '可夹' : '够不着'}`,
      '#' + col.toString(16).padStart(6, '0'))
    tag.position.set(x, y, z + 0.042)
    detectGroup.add(tag)
  }
  info.detN = dets.length ? dets.length + ' 个目标' : '无'
}

watch(() => state.snack?.detections, syncDetections, { deep: true })

// 辅助图层的标签。画法照 tagSprite：只画一个圆角框，框外留透明 ——
// 整块画布铺底色的话，场景里就是一堆跟着透视缩放的灰板子。
// sizeAttenuation 关掉，标签不随距离缩放，远近都一样大小可读。
function layerLabel(text, sub = '', color = '#8b949e') {
  const S = 4, w = 176, h = sub ? 50 : 30
  const c = document.createElement('canvas')
  c.width = w * S; c.height = h * S
  const x = c.getContext('2d')
  x.scale(S, S)
  x.fillStyle = 'rgba(8,12,18,.72)'
  x.strokeStyle = color
  x.globalAlpha = 0.55
  x.lineWidth = 1.2
  x.beginPath(); x.roundRect(1, 1, w - 2, h - 2, 8); x.fill(); x.stroke()
  x.globalAlpha = 1
  x.fillStyle = color
  x.font = '700 17px "PingFang SC", "Microsoft YaHei", sans-serif'
  x.textBaseline = 'middle'
  x.fillText(text, 11, sub ? 17 : 15)
  if (sub) {
    x.fillStyle = 'rgba(226,232,240,.6)'
    x.font = '400 12px ui-monospace, Menlo, monospace'
    x.fillText(sub, 11, 36)
  }
  const tex = new THREE.CanvasTexture(c)
  tex.minFilter = THREE.LinearFilter
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({
    map: tex, transparent: true, depthTest: false, depthWrite: false }))
  sp.material.sizeAttenuation = false
  sp.scale.set(0.108, 0.108 * h / w, 1)
  sp.renderOrder = 999
  return sp
}

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
// 标签精灵列表，保留 canvas/ctx 用于实时更新角度值
const tagSprites = []

function tagSprite(title, sub, joint) {
  // 画到 canvas 再当贴图。用 devicePixelRatio 放大再缩回去，免得在高分屏上糊。
  const S = 4, W = 168 * S, H = 64 * S
  const c = document.createElement('canvas'); c.width = W; c.height = H
  const x = c.getContext('2d')
  x.scale(S, S)
  const r = 9, w = 168, h = 64
  x.fillStyle = 'rgba(8,12,18,.82)'
  x.strokeStyle = 'rgba(56,189,248,.55)'
  x.lineWidth = 1.2
  x.beginPath(); x.roundRect(1, 1, w - 2, h - 2, r); x.fill(); x.stroke()
  x.fillStyle = '#38BDF8'
  x.font = '700 21px ui-monospace, Menlo, monospace'
  x.textBaseline = 'middle'
  x.fillText(title, 13, 16)
  x.fillStyle = 'rgba(226,232,240,.82)'
  x.font = '400 14px "PingFang SC", "Microsoft YaHei", sans-serif'
  x.fillText(sub, 13, 36)
  // 第三行留给角度，初始为 '--'
  x.fillStyle = 'rgba(148,163,184,.88)'
  x.font = '600 13px ui-monospace, Menlo, monospace'
  x.fillText('--°', 13, 54)
  const tex = new THREE.CanvasTexture(c)
  tex.minFilter = THREE.LinearFilter
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({
    map: tex, depthTest: false, depthWrite: false, transparent: true }))
  sp.scale.set(0.115, 0.044, 1)     // 高度加到 0.044 腾出第三行
  sp.material.sizeAttenuation = false
  sp.renderOrder = 999
  return { sprite: sp, canvas: c, ctx: x, title, sub, joint }
}

function makeJointTags() {
  tagSprites.length = 0
  if (tagGroup) { tagGroup.parent && tagGroup.parent.remove(tagGroup) }
  tagGroup = new THREE.Group()
  for (const g of TAGS) {
    const j = robot.joints[g.joint]
    if (!j) continue
    const ts = tagSprite(g.t, g.sub, g.joint)
    ts.sprite.position.set(0, 0, 0.055)     // 从关节原点往外挑一点，别压在结构里
    j.add(ts.sprite)
    tagGroup.add(ts.sprite)                 // 只用来统一控制显隐
    tagSprites.push(ts)
  }
  setTagsVisible(tools.tags)
}

// 更新关节标签的角度值。从 watch(state.joints) 里每帧调一次。
function updateJointAngles() {
  if (!robot || tagSprites.length === 0) return
  const S = 4
  for (const ts of tagSprites) {
    const j = robot.joints[ts.joint]
    if (!j) continue
    const ang = j.angle || 0
    const deg = (ang * 180 / Math.PI).toFixed(1)
    const x = ts.ctx, w = 168, h = 64
    // 只擦第三行，重画角度
    x.clearRect(0, 45, w, 20)
    x.fillStyle = 'rgba(148,163,184,.88)'
    x.font = '600 13px ui-monospace, Menlo, monospace'
    x.textBaseline = 'middle'
    x.fillText(deg + '°', 13, 54)
    ts.sprite.material.map.needsUpdate = true
  }
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
  if (k === 'workspace' && workspaceGroup) workspaceGroup.visible = tools.workspace
  if (k === 'selfbody' && selfbodyGroup) selfbodyGroup.visible = tools.selfbody
  if (k === 'dimensions' && dimensionsGroup) dimensionsGroup.visible = tools.dimensions
  if (k === 'angles' && anglesGroup) anglesGroup.visible = tools.angles
  if (k === 'cameraFov' && cameraFovGroup) cameraFovGroup.visible = tools.cameraFov
  if (k === 'axes' && axesGroup) axesGroup.visible = tools.axes
  if (k === 'detections' && detectGroup) detectGroup.visible = tools.detections
}
// 屏幕在车尾，默认机位在车前 —— 不给个入口就永远看不到它。
// 机位按屏幕的实际世界位姿现算：车会随 /odom 转，写死的坐标转两下就偏了。
const viewIdx = ref(0)

// ---- 全屏 ----
// 全屏目标是最外层 .twin，工具栏和面板一起进全屏；退出用 Esc 或再点一次。
// 进全屏时自动打开专注视图（大屏那边的 focusMode）。
const isFs = ref(false)
function toggleFullscreen() {
  const el = host.value?.parentElement
  if (!el) return
  if (document.fullscreenElement) {
    document.exitFullscreen?.()
  } else {
    el.requestFullscreen?.().then(() => {
      // 全屏成功后触发专注模式：通知父组件（大屏）打开 focusMode
      emit('focus', true)
    }).catch(() => {})
  }
}
function onFsChange() {
  isFs.value = !!document.fullscreenElement
  // 退出全屏时也退出专注模式
  if (!isFs.value) emit('focus', false)
  // 全屏切换会改容器尺寸，renderer 得跟着重算，否则画面被拉伸
  requestAnimationFrame(fit)
}
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
  document.addEventListener('fullscreenchange', onFsChange)
  renderer.domElement.addEventListener('pointerdown', ptrDown)
  renderer.domElement.addEventListener('pointermove', ptrMove)
  window.addEventListener('pointerup', ptrUp)
})
onDeactivated(() => {
  pageActive = false; pollSeq++
  if (screenTimer) { clearInterval(screenTimer); screenTimer = null }
  if (raf) { cancelAnimationFrame(raf); raf = null }
})
onActivated(() => {
  pageActive = true
  if (renderer && !raf) loop()
  if (screenMesh) { startPolling(); restartScreenTimer() }
})
onBeforeUnmount(() => {
  pageActive = false; pollSeq++
  cancelAnimationFrame(raf)
  if (hostRO) hostRO.disconnect()
  window.removeEventListener('resize', fit); window.removeEventListener('pointerup', ptrUp)
  document.removeEventListener('fullscreenchange', onFsChange)
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
      <div v-for="t in [['lidar', '雷达'], ['grid', '网格'], ['points', '点云'], ['tags', '标注'], ['ik', 'IK'],
                        ['workspace', '工作区'], ['selfbody', '遮挡区'], ['dimensions', '尺寸'], ['axes', '坐标轴'],
                        ['detections', '识别']]" :key="t[0]"
        :class="['glass tbtn', { on: tools[t[0]] }]" @click="toggleTool(t[0])">{{ t[1] }}</div>
      <div class="glass tbtn" :title="viewIdx ? '切回默认视角' : '看车尾屏幕'"
        @click="resetView">{{ viewIdx ? '车头' : '视角' }}</div>
      <div class="glass tbtn" :title="isFs ? '退出全屏' : '全屏显示'"
        @click="toggleFullscreen">{{ isFs ? '退出' : '全屏' }}</div>
      <div :class="['glass tbtn', { on: matOpen }]" title="材质与光照，实时生效"
        @click="matOpen = !matOpen">材质</div>
      <div :class="['glass tbtn', { on: tools.detectionFeed }]" title="YOLO 识别画面"
        @click="tools.detectionFeed = !tools.detectionFeed">识别流</div>
    </div>

    <!-- YOLO 识别画面小窗：浮在右上角，工具列左边 -->
    <div v-if="tools.detectionFeed" class="det-feed">
      <div class="df-head">
        <b>实时识别</b>
        <span class="df-close" title="关闭" @click="tools.detectionFeed = false">✕</span>
      </div>
      <img class="df-img" :src="detFeedSrc" alt="" @error="reloadDetFeed" />
      <div class="df-stat">{{ detFeedStat }}</div>
    </div>

    <!-- 材质面板：拖滑块实时看效果，自动存本机，调好一键导出成代码贴回本文件 -->
    <div v-if="matOpen" class="glass panel look">
      <h4>材质与光照
        <span class="lk-act" @click="resetLook">恢复默认</span>
      </h4>
      <div class="lk-save">
        <button class="lk-btn primary" :disabled="look.saving || !look.dirty" @click="saveLook">
          {{ look.saving ? '保存中…' : '保存到机器人' }}</button>
        <button class="lk-btn" :disabled="look.saving || !look.dirty" @click="revertLook">放弃改动</button>
      </div>
      <div class="lk-msg" :class="{ warn: look.dirty, bad: look.msg.startsWith('保存失败') }">
        {{ look.msg || (look.dirty ? '有未保存的改动（仅存在本机）'
            : look.onRobot ? '当前为车上保存的版本' : '当前为代码默认值') }}
      </div>
      <div class="lk-grp" style="border-top:0;padding-top:2px">
        <div class="lk-h"><span>屏幕内容</span></div>
        <div class="lk-seg">
          <button v-for="b in SCREEN_BLOCKS" :key="b[0]"
            :class="{ on: screenCfg.block === b[0] }" @click="screenCfg.block = b[0]">{{ b[1] }}</button>
        </div>
      </div>
      <div v-for="(c, k) in mat" :key="k" class="lk-grp">
        <div class="lk-h">
          <input type="color" v-model="c.color" />
          <span>{{ c.cn }}</span>
        </div>
        <div class="lk-r"><span>金属度</span>
          <input type="range" min="0" max="1" step="0.01" v-model.number="c.metalness" />
          <i>{{ c.metalness.toFixed(2) }}</i></div>
        <div class="lk-r"><span>粗糙度</span>
          <input type="range" min="0.02" max="1" step="0.01" v-model.number="c.roughness" />
          <i>{{ c.roughness.toFixed(2) }}</i></div>
        <div class="lk-r"><span>反射</span>
          <input type="range" min="0" max="3" step="0.05" v-model.number="c.env" />
          <i>{{ c.env.toFixed(2) }}</i></div>
      </div>
      <div class="lk-grp">
        <div class="lk-h"><span>光照</span></div>
        <div class="lk-r"><span>曝光</span>
          <input type="range" min="0.2" max="3" step="0.05" v-model.number="lit.exposure" />
          <i>{{ lit.exposure.toFixed(2) }}</i></div>
        <div class="lk-r"><span>环境光</span>
          <input type="range" min="0" max="3" step="0.02" v-model.number="lit.hemi" />
          <i>{{ lit.hemi.toFixed(2) }}</i></div>
        <div class="lk-r"><span>主光</span>
          <input type="range" min="0" max="4" step="0.05" v-model.number="lit.key" />
          <i>{{ lit.key.toFixed(2) }}</i></div>
        <div class="lk-r"><span>轮廓光</span>
          <input type="range" min="0" max="4" step="0.05" v-model.number="lit.rim" />
          <i>{{ lit.rim.toFixed(2) }}</i></div>
      </div>
      <div class="lk-out">
        <div class="lk-h"><span>导出</span>
          <span class="lk-act" @click="copyCode">{{ copied ? '已复制 ✓' : '复制代码' }}</span>
        </div>
        <textarea readonly :value="exportCode" @focus="$event.target.select()" />
        <div class="hint">「保存到机器人」写在车上（~/twin_look.json），换设备、清缓存都还在，
          所有人打开看到的都是这份。下面这段代码是给「想让它进代码库当默认值」用的：
          贴回 Twin.vue 顶部的 MAT_DEFAULT / LIGHT_DEFAULT 即可。</div>
      </div>
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
.twin:fullscreen { position: fixed; z-index: 9999; }
.scene { position: absolute; inset: 0; }
.scene :deep(canvas) { display: block; }
.loading { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; color: rgba(255,255,255,.6); font-family: ui-monospace, monospace; }
.glass { background: rgba(14,17,22,.55); backdrop-filter: blur(16px); border: 1px solid rgba(255,255,255,.12); color: #eef2f6; }
.tools { position: absolute; right: 14px; top: 14px; z-index: 10; display: flex; flex-direction: column; gap: 8px; }
.tbtn { width: 44px; height: 40px; display: flex; align-items: center; justify-content: center; font-size: 11px; border-radius: 11px; cursor: pointer; color: rgba(255,255,255,.6); }
.tbtn.on { color: #fff; box-shadow: inset 0 0 0 1px #2e9bff; background: rgba(46,155,255,.16); }

/* ---- YOLO 识别画面小窗 ----
   高度按「四个按钮」算：4×40 + 3×8 = 184px。画面 4:3，所以宽 = 画面 184-42(头尾)
   ≈ 142 高 → 190 宽，取整 208px。right 让开工具列（44 + 14 + 14 间距）。 */
.det-feed { position: absolute; right: 72px; top: 14px; z-index: 9; width: 208px;
  background: rgba(8,12,18,.88); backdrop-filter: blur(8px); border-radius: 11px;
  border: 1px solid rgba(148,163,184,.22); overflow: hidden; }
.df-head { display: flex; align-items: center; justify-content: space-between;
  padding: 5px 9px; background: rgba(15,23,42,.55); }
.df-head b { color: #E2E8F0; font-size: 11px; letter-spacing: .4px; }
.df-close { color: #64748B; font-size: 13px; line-height: 1; cursor: pointer; padding: 0 2px; }
.df-close:hover { color: #CBD5E1; }
.df-img { display: block; width: 100%; aspect-ratio: 4/3; object-fit: contain; background: #000; }
.df-stat { padding: 4px 9px; font-size: 9px; color: #94A3B8; text-align: right;
  background: rgba(15,23,42,.4); }
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
/* 材质面板 */
/* 高度必须收住：左下角还有「实时遥测」面板，伸到底就会压在它上面。
   60% + 内部滚动，两块面板各占各的。 */
.panel.look { position: absolute; left: 14px; top: 14px; width: 264px; padding: 12px 14px;
  border-radius: 14px; max-height: 60%; overflow-y: auto; z-index: 7; }
.panel.look::-webkit-scrollbar { width: 6px; }
.panel.look::-webkit-scrollbar-thumb { background: rgba(255,255,255,.18); border-radius: 3px; }
.panel.look h4 { justify-content: space-between; }
.lk-act { cursor: pointer; color: #2e9bff; font-size: 11px; font-weight: 400; letter-spacing: 0; }
.lk-act:hover { text-decoration: underline; }
.lk-grp { padding: 8px 0; border-top: 1px solid rgba(255,255,255,.1); }
.lk-h { display: flex; align-items: center; gap: 8px; margin-bottom: 6px;
  font-size: 11px; color: rgba(255,255,255,.72); justify-content: space-between; }
.lk-h > span:first-child { flex: 1; }
.lk-h input[type=color] { width: 22px; height: 18px; padding: 0; border: 1px solid rgba(255,255,255,.2);
  border-radius: 4px; background: none; cursor: pointer; flex-shrink: 0; }
.lk-r { display: flex; align-items: center; gap: 8px; margin: 3px 0; }
.lk-r > span { font-size: 10px; color: rgba(255,255,255,.5); width: 38px; flex-shrink: 0; }
.lk-r input[type=range] { flex: 1; min-width: 0; }
.lk-r i { font-style: normal; font-size: 10px; width: 30px; text-align: right;
  color: rgba(255,255,255,.6); font-variant-numeric: tabular-nums; }
.lk-seg { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }
.lk-seg button { height: 26px; border-radius: 7px; cursor: pointer; font-size: 11px;
  border: 1px solid rgba(255,255,255,.16); background: rgba(255,255,255,.05); color: rgba(255,255,255,.72); }
.lk-seg button.on { border-color: #2e9bff; background: rgba(46,155,255,.2); color: #cfe3ff; }
.lk-save { display: flex; gap: 8px; margin: 2px 0 6px; }
.lk-btn { flex: 1; height: 27px; border-radius: 8px; cursor: pointer; font-size: 11px;
  border: 1px solid rgba(255,255,255,.18); background: rgba(255,255,255,.06); color: #eef2f6; }
.lk-btn.primary { border-color: #2e9bff; background: rgba(46,155,255,.18); color: #cfe3ff; }
.lk-btn:disabled { opacity: .38; cursor: default; }
.lk-msg { font-size: 10px; color: rgba(255,255,255,.4); line-height: 1.5; margin-bottom: 2px; }
.lk-msg.warn { color: #F59E0B; }
.lk-msg.bad { color: #F43F5E; }
.lk-out { padding-top: 8px; border-top: 1px solid rgba(255,255,255,.1); }
.lk-out textarea { width: 100%; height: 104px; background: rgba(0,0,0,.35); color: #cfe3ff;
  border: 1px solid rgba(255,255,255,.12); border-radius: 8px; padding: 7px 8px; font-size: 10px;
  line-height: 1.5; font-family: ui-monospace, monospace; resize: vertical; }
@media (max-width: 820px) { .tele { width: 150px; } .ctrl { width: 190px; } }
@media (max-width: 560px) { .tele { display: none; } }

/* ---- Twin 移动端适配 ---- */
@media (max-width: 1024px) {
  .tools { right:10px; top:10px; gap:6px; }
  .tbtn { width:38px; height:36px; font-size:10px; }
  .det-feed { right:56px; top:10px; width:180px; }
  .df-head { padding:4px 7px; }
  .df-head b { font-size:10px; }
  .df-close { font-size:12px; }
  .df-stat { padding:3px 7px; font-size:8px; }
}

@media (max-width: 640px) {
  .tools { right:6px; top:6px; gap:5px; }
  .tbtn { width:34px; height:32px; font-size:9px; border-radius:9px; }
  .det-feed { right:46px; top:6px; width:150px; border-radius:9px; }
  .df-head { padding:3px 6px; }
  .df-head b { font-size:9px; }
  .df-close { font-size:11px; }
  .df-stat { font-size:7px; }
}
</style>
