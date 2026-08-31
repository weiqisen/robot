# Mac MySQL 业务数据采集

MySQL 8 运行在 Mac，本机采集器主动连接机器人 rosbridge；Jetson 不运行数据库。

```bash
export MYSQL_PASSWORD='你的本机 MySQL 密码'
/opt/homebrew/opt/mysql@8.0/bin/mysql -uroot -p < tools/mysql_schema.sql
.venv/bin/python tools/mac_recorder.py
```

常驻服务：

```bash
./tools/install_mac_recorder.sh
```

安装脚本会把运行副本和独立 Python 环境放到
`~/Library/Application Support/JetroverRecorder`，避免 macOS 阻止后台服务访问 Desktop。
数据库密码只保存在仓库根目录与运行目录的 `.mysql.env`（权限 `600`），不会提交 Git。

采集 `/explorer/state`、`/snack_butler/state`、`/nav_safety/state`、系统日志和 Jetson 遥测；YOLO 地图物品另存于 `detected_objects`。
