# Mac MySQL 业务数据采集

MySQL 8 运行在 Mac，本机采集器主动连接机器人 rosbridge；Jetson 不运行数据库。

```bash
export MYSQL_PASSWORD='你的本机 MySQL 密码'
/opt/homebrew/opt/mysql@8.0/bin/mysql -uroot -p < tools/mysql_schema.sql
.venv/bin/python tools/mac_recorder.py
```

采集 `/explorer/state`、`/snack_butler/state`、`/nav_safety/state`、系统日志和 Jetson 遥测；YOLO 地图物品另存于 `detected_objects`。
