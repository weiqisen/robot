#!/usr/bin/env node
/* 截图 + 场景探针。之前几次「改完部署了但看不到」都是盲发导致的，
 * 这个脚本让改动能在提交前自己验证一遍。
 *
 *   node scripts/shot.mjs '#twin' out.png
 *   SHOT_BASE=http://localhost:5273/ node scripts/shot.mjs '#twin' out.png
 *   node scripts/shot.mjs '#twin' out.png --probe "window.__twin.screenMesh.visible"
 *
 * 用系统装的 Chrome(puppeteer-core)，不额外下浏览器。WebGL 走 SwiftShader 软渲染，
 * 慢但能出图，够验证「东西在不在、位置对不对」。
 */
import puppeteer from 'puppeteer-core'

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.SHOT_BASE || 'http://192.168.3.63:8000/'
const hash = process.argv[2] || '#bigscreen'
const out = process.argv[3] || 'shot.png'
const pi = process.argv.indexOf('--probe')
const probe = pi > -1 ? process.argv[pi + 1] : null
const WAIT = Number(process.env.SHOT_WAIT || 22000)

// 视口预设。移动端适配得按真机尺寸验，桌面尺寸下媒体查询根本不触发。
//   SHOT_VIEWPORT=ipad node scripts/shot.mjs '#bigscreen' out.png
const VIEWPORTS = {
  desktop: { width: 1600, height: 1000, dsf: 1, mobile: false },
  ipad:    { width: 1024, height: 768,  dsf: 2, mobile: true },  // 横屏 iPad
  ipadp:   { width: 768,  height: 1024, dsf: 2, mobile: true },  // 竖屏 iPad
  ipadair: { width: 1180, height: 820,  dsf: 2, mobile: true },  // iPad Air 横屏
  iphone:  { width: 390,  height: 844,  dsf: 3, mobile: true },  // iPhone 14
}
const vpName = process.env.SHOT_VIEWPORT || 'desktop'
const VP = VIEWPORTS[vpName] || VIEWPORTS.desktop

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ['--headless=new', '--no-sandbox', '--enable-unsafe-swiftshader',
         '--use-gl=angle', '--use-angle=swiftshader',
         `--window-size=${VP.width},${VP.height}`],
})
const page = await browser.newPage()
await page.setViewport({ width: VP.width, height: VP.height,
  deviceScaleFactor: VP.dsf, isMobile: VP.mobile, hasTouch: VP.mobile })
console.log('视口', vpName, `${VP.width}x${VP.height}`)

const logs = []
page.on('console', m => logs.push(`[${m.type()}] ${m.text()}`))
page.on('pageerror', e => logs.push(`[PAGEERROR] ${e.message}`))
page.on('requestfailed', r => logs.push(`[REQFAIL] ${r.url()} ${r.failure()?.errorText}`))

const url = BASE.replace(/\/$/, '/') + hash
console.log('打开', url)
await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 })

// 等 3D 就绪：Twin 会把内部对象挂到 window.__twin，等 robot 出现即可
const ready = await page.waitForFunction(
  () => !document.querySelector('.loading') || (window.__twin && window.__twin.robot),
  { timeout: WAIT, polling: 400 },
).then(() => true).catch(() => false)
console.log(ready ? '场景就绪' : `等了 ${WAIT}ms 仍未就绪（继续截图看现场）`)
await new Promise(r => setTimeout(r, 2500))   // 留时间让 rosbridge 送一轮数据

if (probe) {
  // 支持 async 表达式：点了按钮要等 Vue 重渲染，同步读 DOM 会扑空
  const v = await page.evaluate(async p => {
    try { return JSON.stringify(await eval(p)) } catch (e) { return 'ERR: ' + e.message }
  }, probe)
  console.log('探针', probe, '=>', v)
}

await page.screenshot({ path: out })
console.log('已存', out)
const bad = logs.filter(l => /PAGEERROR|\[error\]|REQFAIL/.test(l))
if (bad.length) { console.log('\n页面报错：'); bad.slice(0, 15).forEach(l => console.log('  ' + l)) }
else console.log('无页面报错')
await browser.close()
