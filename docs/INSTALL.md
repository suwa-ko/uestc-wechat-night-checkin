# 参考部署步骤

当前脚本固定使用`/opt/uestc-wechat`源码目录和`/usr/local/lib/wechat-checkin`安装目录，适合有Docker、systemd和Nginx维护经验的Linux x86_64主机。原部署只验证了指定微信版本；不要用不同版本的客户端套用固定渲染器偏移。

以下是整理后的部署参考，**未在空白服务器执行整套端到端安装**。先完成所有只读检查，再启用自动提交。

## 1. 主机与客户端

需要Docker CE/Compose、Python3.12及Pillow、Nginx、OpenSSL、GnuPG、`nsenter`、sudo和字体。Ubuntu可安装主机工具：

```sh
sudo apt-get update
sudo apt-get install -y git ca-certificates python3 python3-pil nginx openssl gnupg util-linux sudo
sudo git clone https://github.com/suwa-ko/uestc-wechat-night-checkin /opt/uestc-wechat
cd /opt/uestc-wechat
```

从[微信官方Linux下载页](https://linux.weixin.qq.com/)自行获取客户端安装包，放到`vendor/wechat-official.deb`。仓库不分发客户端。**已验证的是4.1.13.26，不是官网今后任意最新版**；若对应版本不可获得，本方案可能暂时无法复现，应停止而非跳过版本校验。

```sh
sudo docker build -t wechat-web:4.1.13.26 -f desktop/Dockerfile .
sudo python3 scripts/init_layout.py
# 仅初始化上一步新建且由本项目管理的空资料卷
sudo docker run --rm --network none --user 0:0 --entrypoint chown \
  -v wechat-profile:/home/wechat wechat-web:4.1.13.26 10001:10001 /home/wechat
sudo docker compose -p wechat-web -f desktop/compose.yaml up -d
```

`wechat-profile`是独立资料卷，禁止同时挂给两个微信客户端。宿主机只发布`127.0.0.1:6080`。

## 2. 网页入口与登录

准备自己的域名及HTTPS证书。编辑`examples/nginx.conf`，把所有示例域名和证书路径换成自己的值。配置独立网页登录账号：

```sh
sudo python3 scripts/set_web_password.py
sudo install -m 644 examples/nginx.conf /etc/nginx/sites-available/checkin
# 确认此站点名未被其他网站使用，再启用链接
sudo ln -s /etc/nginx/sites-available/checkin /etc/nginx/sites-enabled/checkin
sudo nginx -t
sudo systemctl reload nginx
```

从网页远程桌面扫码登录官方Linux微信。首次登录或失效后，手机可能要求确认及解锁。确认本人设备情况，再手动打开成电智慧学工一次，让小程序运行库完成初始化。不要把noVNC或CDP端口直接暴露到公网。

## 3. 调试依赖

```sh
sudo python3 runtime/prepare_wmpf.py
sudo python3 runtime/install_wmpf.py
sudo install -m 600 runtime/cdp_probe.cjs runtime/wmpf-debugger/cdp_probe.cjs
```

准备脚本固定WMPFDebugger提交和Node22.23.4，校验Node归档与上游Git blob SHA；第三方运行依赖保存在`runtime/wmpf-debugger/`，不提交Git。下载通过标准代理环境变量设置，不内置某台服务器的代理地址。

`start_wmpf.py`只允许镜像标签、所属容器、WMPF25806和预期渲染器SHA256匹配。调试服务在容器网络命名空间的回环地址监听。它需要附加进程的权限，但微信容器不以特权模式运行。

## 4. 私有配置与QQ通知

编辑`/etc/wechat-checkin/config.json`，样例见[配置文件](../examples/config.example.json)。填写你自己的位置、管理网址、AstrBot平台ID及私聊QQ目标。

- `latitude` / `longitude`：WGS84，纬度/经度。
- `gcj02`：GCJ-02，数组顺序是经度/纬度。
- `manage_url`：自己的远程桌面HTTPS网址。
- `astrbot.umo`：`平台ID:FriendMessage:QQ号`。

在你自己的AstrBot管理界面创建专用、仅含`im`范围的API Key，写入`/etc/wechat-checkin/astrbot-im.key`，权限600。不要把Key放进仓库或命令行参数。默认假设容器名为`astrbot`、本机API为`127.0.0.1:6185`、宿主机数据目录为`/root/astrbot/data`；与你的部署不同则修改安装脚本中的对应路径。

图片通知渲染器沿用`/AstrBot/data/render_theme/kit.py`提供的`list_card`接口。仓库不包含私人主题；没有该接口时，通知自动降级为一条文字。可替换`render_notice.py`适配自己的模板，仍应保持“图片成功仅图片，失败仅文字”。

## 5. 安装与只读验证

```sh
sudo python3 scripts/preflight.py
sudo python3 checkin/deploy.py
sudo python3 /usr/local/lib/wechat-checkin/checkin.py dry-run
```

白天`PENDING`、没有可点击提交按钮是正常的；演练应显示业务日期为今天、票据存在、地图和定位匹配、没有认证要求。演练不提交签到。

原部署的Nginx扩展片段无需复用；备份脚本会收集当前存在的站点和相关配置。检查备份中的证书、数据目录是否符合你自己的安装。资料备份属于敏感文件，即便排除了聊天记录也必须加密保管。

## 6. 启用计划

确认登录及演练成功、通知目标正确后，再执行：

```sh
sudo systemctl enable --now wechat-checkin-prepare.timer wechat-checkin-submit.timer wechat-checkin-watchdog.timer
sudo python3 checkin/ops_deploy.py
```

第一条启用20:58准备、21:01签到和每5分钟心跳。第二条启用04:20加密备份并初始化独立口令、日志轮换。**完整验证一次备份成功后**，如你确实不需要云端聊天记录，再选择启用每日清空：

```sh
sudo systemctl start wechat-checkin-backup.service
sudo python3 checkin/install_cleanup.py
```

`install_cleanup.py`会启用04:50清空云端微信全部聊天记录的计划；此动作是不可恢复的，不应在需要保留聊天记录的客户端上启用。它不会清空手机或其他电脑的数据。项目默认时间窗口21:01–23:00是脚本的保守限制，不声称学校对所有账号均采用相同窗口。

每个计划首次运行后核对[运行记录](OPERATIONS.md)。首次提交仅能在实际开放时段验证；未核验学校记录之前，不把部署成功当成签到成功。
