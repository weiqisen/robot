// 动作组名称在编辑器和工作台共用，避免同一份 .d6a 显示成两套名字。
const ACTION_NAMES = {
  stand: '立正', relax: '放松', home: '回正', zero: '零位', init: '初始化',
  go_forward: '前进', go_back: '后退', turn_left: '左转', turn_right: '右转', move_left: '左移', move_right: '右移',
  wave: '挥手', nod: '点头', shake_head: '摇头', bow: '鞠躬', salute: '敬礼', clap: '鼓掌', thumbs_up: '点赞', ok: 'OK手势', victory: '胜利手势',
  pick: '抓取', pick_up: '拾起', place: '放下', grab: '夹取', release: '松开', hold: '保持', grasp: '握住',
  dance: '跳舞', dance1: '舞蹈1', dance2: '舞蹈2', twist: '扭动', swing: '摇摆',
  calibrate: '标定', test: '测试', demo: '演示', patrol: '巡逻', search: '搜索',
  camera_up: '相机上抬', horizontal: '水平姿态',
}

export function actionGroupLabel(name, groups = []) {
  if (ACTION_NAMES[name]) return ACTION_NAMES[name]
  const s = String(name).toLowerCase().replace(/[ _-]+/g, '')
  const rules = [
    [/^(action)?group(\d+)$/, '动作组 $2'], [/^action(\d+)$/, '动作 $1'],
    [/^(wave|waving)/, '挥手'], [/^(welcome|hello)/, '欢迎'], [/^(bow|kowtow)/, '鞠躬'],
    [/^(dance|dancing)/, '舞蹈'], [/^(clap|applause)/, '鼓掌'], [/^(nod)/, '点头'],
    [/^(shake|shaking)/, '摇头'], [/^(stand|upright)/, '立正'], [/^(relax)/, '放松'],
    [/^(home|reset)/, '回正'], [/^(grab|grasp|pick)/, '抓取'], [/^(place|release)/, '放下'],
    [/^(left|turnleft)/, '左转'], [/^(right|turnright)/, '右转'], [/^(forward)/, '前进'], [/^(back|backward)/, '后退'],
  ]
  for (const [re, label] of rules) if (re.test(s)) return label.replace('$2', s.match(re)?.[2] || '')
  const words = s.match(/camera|garbage|handcontrol|horizontal|linefollow|moveobject|navigation|pick|place|foodwaste|debug|init|center|control|up|down|left|right|object|follow|waste|vertical|open|close|test|wave|dance/g) || []
  const cn = { camera:'相机', garbage:'垃圾', handcontrol:'手动控制', horizontal:'水平', linefollow:'循迹', moveobject:'移动物体', navigation:'导航', pick:'抓取', place:'放置', foodwaste:'厨余', debug:'调试', init:'初始化', center:'居中', control:'控制', up:'上', down:'下', left:'左', right:'右', object:'物体', follow:'跟随', waste:'废弃物', vertical:'垂直', open:'打开', close:'关闭', test:'测试', wave:'挥手', dance:'舞蹈' }
  const label = [...new Set(words.map(w => cn[w]))].join(' · ')
  const n = groups.indexOf(name) + 1
  return label || (n > 0 ? `动作组 ${n}` : '动作组')
}
