#!/usr/bin/env python3
"""在 Mac 上订阅机器人 rosbridge，并把业务状态保存到本机 MySQL。"""
import json, os, time
import mysql.connector
import websocket

HOST=os.getenv('ROBOT_HOST','192.168.3.63')
DB=dict(host='127.0.0.1',user=os.getenv('MYSQL_USER','root'),
        password=os.environ['MYSQL_PASSWORD'],database=os.getenv('MYSQL_DATABASE','jetrover'))
TOPICS=['/explorer/state','/snack_butler/state','/nav_safety/state','/system/log','/jetson/stats']
db=mysql.connector.connect(**DB); cur=db.cursor()
seen=set()
def message(ws, raw):
    m=json.loads(raw)
    if m.get('op')!='publish': return
    topic=m['topic']; data=m.get('msg',{}).get('data',m.get('msg',{}))
    try: payload=json.loads(data) if isinstance(data,str) else data
    except Exception: payload={'raw':data}
    cur.execute('INSERT INTO ros_events(topic,payload) VALUES(%s,%s)',(topic,json.dumps(payload,ensure_ascii=False)))
    if topic=='/explorer/state':
        for o in payload.get('objects',[]):
            key=(o.get('label'),o.get('x'),o.get('y'),o.get('seen_at'))
            if key in seen: continue
            seen.add(key); cur.execute('INSERT INTO detected_objects(label,confidence,map_x,map_y,seen_at,raw) VALUES(%s,%s,%s,%s,%s,%s)',
              (o.get('label'),o.get('confidence'),o.get('x'),o.get('y'),o.get('seen_at'),json.dumps(o,ensure_ascii=False)))
    db.commit()
def opened(ws):
    for i,t in enumerate(TOPICS): ws.send(json.dumps({'op':'subscribe','id':f'mac-{i}','topic':t,'throttle_rate':500}))
while True:
    try: websocket.WebSocketApp(f'ws://{HOST}:9090',on_open=opened,on_message=message).run_forever()
    except Exception as e: print('[recorder]',e,flush=True)
    time.sleep(3)
