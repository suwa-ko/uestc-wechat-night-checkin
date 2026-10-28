# 运维

## 常用命令

```sh
sudo systemctl list-timers 'wechat-checkin-*'
sudo cat /var/lib/wechat-checkin/health.json
sudo cat /var/lib/wechat-checkin/last-prepare.json
sudo cat /var/lib/wechat-checkin/last-backup.json
sudo cat /var/lib/wechat-checkin/last-cleanup.json
sudo cat /var/lib/wechat-checkin/local-sync.json
sudo python3 /usr/local/lib/wechat-checkin/checkin.py dry-run
```

每日账本是`/var/lib/wechat-checkin/YYYY-MM-DD.json`。不要删除已有`confirmIntent`的账本强制重试。遇到验证码、MFA或失效登录时，先从远程桌面由本人处理，再执行`checkin.py resume`；恢复命令不会立即提交。

最终归档UI版本为`2026.10.27.1`：只允许对已记住账号的、经过严格模板及稳定性检查的“进入微信”按钮点击一次。等待后仍无主窗口则暂停；不会自动处理手机确认、扫码、MFA或锁定。认证已经暂停后，仍需本人处理并显式`resume`。

## 维护锁与补跑

签到、心跳、备份和清理共享运行锁。维护任务先等待最多30秒，仍忙碌或备份前提暂不满足时退出75；systemd间隔60秒补跑，30分钟内最多启动4次（含首次）。业务失败和常见崩溃信号停止，避免无限执行。直接运行Python脚本不由systemd管理，不会自动补跑。

`backup-attempt.json` / `cleanup-attempt.json`保存等待、推迟和最终结果；旧成功记录不会因为一次推迟被覆盖。连续两次健康检查发现以下异常才私聊QQ，并对相同持续问题去重：

| 条件 | 阈值 |
| --- | --- |
| 聊天清理、加密备份未成功更新 | 36小时 |
| 维护等待/补跑仍未完成 | 15分钟 |
| 最新完整备份无匹配D盘回执 | 生成后12小时 |
| 同一备份的本地同步确认未刷新 | 36小时 |

手工排除故障后可重启维护服务；若刚触发启动次数上限，先`systemctl reset-failed 对应服务名`。不要去掉锁。补跑只针对备份与清理，不会在签到提交结果未知时反复点击学校页面。

## Windows本地备份

服务器暂存两份加密完整备份；完整备份排除聊天消息/会话数据库、聊天媒体、截图和日志，但仍有登录资料、配置和运行依赖。`config-snapshot-*.gpg`只含源码及配置。解密口令不在归档内。

1. 创建自己专用的本地目录，例如`D:\backups\wechat-checkin`，限制访问权限。
2. 把`checkin/sync_backups.py`复制进去；在SSH配置中配置`wechat-host`别名和非交互认证。
3. 创建`backup-target.json`，内容为`{"owner":"wechat-checkin-backups:v1"}`。
4. 使用Python3.12+执行`python sync_backups.py --root D:\backups\wechat-checkin`。
5. 在Windows任务计划程序中按自己的需要配置每天07:00及登录后运行。需要登录会话、联网；电脑离线时不会凭空完成拉取。

同步支持断点续传；只有SHA256核验通过才把`.partial`提升为正式文件，并回传最新完整备份的文件名、哈希、大小和确认时间。口令通过SSH单独保存在本地`backup-passphrase.txt`，不要公开或丢失。本地保留7份完整备份及最新配置副本。服务器不会仅因收到回执自动删除全部备份。

## 聊天与缓存

每日清空使用官方微信“设置 → 账号与存储 → 清空全部聊天记录 → 清空全部”，逐步核验公共按钮模板；不手工删除运行中的数据库，也不退出微信。未知界面、锁定或版本不符时停止。成功后数据库文件仍可能预分配空间，不代表聊天还在。

随后清理白名单中的过期缓存：聊天缓存7天、临时文件2天、崩溃记录7天、着色器缓存30天。保留登录资料、Cookie、小程序组件和数据库/WAL；不跟随符号链接。清理要求36小时内有成功备份，且未确认签到成功时不会占用签到时段。

## 故障边界

`TICKET_MISSING`需要检查本人客户端授权；`SCHOOL_LOGO_NOT_MATCHED`需要检查列表是否加载、分辨率和图标模板；`DEBUGGER_VERSION_CHANGED`应核对客户端版本及渲染器，不能跳过哈希校验。业务页面模块改名时同样停止，先人工重新验证。

健康检查没有异常，只说明已经覆盖的检查项正常，不保证微信会话永不过期。QQ或AstrBot自身离线时私信可能无法送达，服务器账本仍是依据。
