"""Render a single QQ failure card with the user's existing AstrBot theme."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import uuid


async def main():
    os.umask(0o077)
    payload = json.loads(sys.stdin.read(16384))
    spec = importlib.util.spec_from_file_location('_wechat_checkin_theme', '/AstrBot/data/render_theme/kit.py')
    theme = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(theme)
    kinds = {'test': '通知通道测试', 'auth_pause': '需要本人处理认证', 'failure': '自动签到未确认成功'}
    kind = kinds.get(payload.get('kind'), '运行提醒')
    image = theme.list_card('晚安成电', payload['day'].removesuffix('-test') + ' · ' + kind,
                            [{'title': payload.get('label', '21:01 自动签到'),
                              'detail': str(payload.get('detail', payload.get('message', '')))[:2000],
                              'status': '打开网页检查；遇到认证时请本人处理'}],
                            kind='系统通知', metrics=[('当前状态', kind)],
                            footer='只在失败或需处理时通知 · 管理入口见卡片正文')
    root = Path('/AstrBot/data/temp/wechat-checkin-notices')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    output = root / ('wechat_notice_' + uuid.uuid4().hex + '.png')
    image.save(output)
    from astrbot.core.db.sqlite import SQLiteDatabase
    db = SQLiteDatabase('/AstrBot/data/data_v4.db')
    db.inited = True
    manifest = root / 'attachments.json'
    try:
        previous = json.loads(manifest.read_text()) if manifest.exists() else []
        keep = []
        for index, item in enumerate(previous):
            path = Path(item['path'])
            expired = time.time() - item['created_at'] > 86400 or (len(previous) - index >= 30 and time.time() - item['created_at'] > 600)
            if expired and path.parent == root and path.name.startswith('wechat_notice_'):
                await db.delete_attachment(item['attachment_id'])
                path.unlink(missing_ok=True)
            else:
                keep.append(item)
        attachment = await db.insert_attachment(str(output), 'image', 'image/png')
        keep.append({'path': str(output), 'attachment_id': attachment.attachment_id, 'created_at': time.time()})
        temp = manifest.with_suffix('.tmp')
        temp.write_text(json.dumps(keep))
        os.replace(temp, manifest)
        print(json.dumps({'attachment_id': attachment.attachment_id}), flush=True)
    finally:
        await db.engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
