import argparse
import json
import os
from pathlib import Path
import signal
from datetime import datetime
from .core import window,write_export
from .reader import roots,snapshot,Reader
from .render import render

def main():
    os.umask(0o077)
    def stop(*_): raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,stop)
    ap=argparse.ArgumentParser(description='本地微信指定群导出；总结由当前 Codex 会话完成，无额外 API Key')
    sub=ap.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor')
    f=sub.add_parser('fixture');f.add_argument('--out',type=Path)
    r=sub.add_parser('render');r.add_argument('out',type=Path)
    im=sub.add_parser('images');im.add_argument('source',type=Path);im.add_argument('--out',type=Path)
    ir=sub.add_parser('review-images');ir.add_argument('out',type=Path);ir.add_argument('reviews',type=Path)
    e=sub.add_parser('export');e.add_argument('--group');e.add_argument('--group-id');e.add_argument('--db-root',type=Path)
    e.add_argument('--hours',type=int,choices=(24,48,72),default=24);e.add_argument('--start');e.add_argument('--end');e.add_argument('--timezone',default='Asia/Colombo');e.add_argument('--out',type=Path)
    for parser in (im,e):parser.add_argument('--interactive-login',action='store_true',help='仅在用户明确同意本次临时微信登录后启用；默认禁止启动登录窗口')
    args=ap.parse_args()
    if args.command=='doctor':
        import platform,subprocess
        print(json.dumps({'os':platform.platform(),'architecture':platform.machine(),'accounts':[str(p) for p in roots()], 'wechat_version':subprocess.run(['/usr/libexec/PlistBuddy','-c','Print :CFBundleShortVersionString','/Applications/WeChat.app/Contents/Info.plist'],capture_output=True,text=True).stdout.strip(),'real_read_verified':False},ensure_ascii=False,indent=2));return
    if args.command=='render':print(json.dumps(render(args.out),ensure_ascii=False));return
    if args.command=='review-images':
        from .images import apply_reviews
        data=apply_reviews(args.out.resolve(),args.reviews)
        print('图片审阅已合并。请综合全部消息重写 report.json，再运行 render。');return
    out=args.out or Path('outputs')/(args.command+'-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    if args.command=='fixture':
        from .fixture import create
        create(out);print(out.resolve());return
    if args.command=='images':
        from .bootstrap import capture
        from .images import prepare_images,persist
        data=json.loads((args.source/'messages.json').read_text())
        account=data['coverage']['account_directory']
        matches=[p for p in roots() if p.parent.name==account]
        if len(matches)!=1:raise ValueError('原报告账号与本机账号不能唯一匹配')
        root=matches[0];paths=[root/'message/message_resource.db']
        keys=capture(root,paths,allow_interactive=args.interactive_login)
        try:
            with snapshot(root,paths) as (copied,wal):
                out.mkdir(parents=True,exist_ok=False,mode=0o700)
                data['coverage']['image_resource_snapshot']=wal
                data['coverage']['image_source_report']=str(args.source.resolve())
                prepare_images(data,out,Reader(copied,keys),root.parent)
                persist(data,out)
        finally:keys.clear()
        print(str(out.resolve())+'：图片已准备，请当前会话逐张看图并提交审阅。');return
    group=args.group or input('请输入完整群名：').strip()
    if not group:raise ValueError('必须提供完整群名')
    accounts=roots();root=args.db_root.resolve() if args.db_root else accounts[0] if len(accounts)==1 else None
    if root is None:raise ValueError('多账号或无账号，请明确 --db-root：'+str(accounts))
    if root not in [p.resolve() for p in accounts]:raise ValueError('仅允许本机已检测到的微信账号目录')
    win=window(args.hours,args.start,args.end,args.timezone)
    print('固定时间窗口：'+win['start']+' ≤ 时间 < '+win['end']+' '+win['timezone'],flush=True)
    from .bootstrap import capture
    from .reader import source_paths
    paths=source_paths(root)+[root/'message/message_resource.db']
    keys=capture(root,paths,allow_interactive=args.interactive_login)
    try:
        with snapshot(root,paths) as (copied,wal):
            reader=Reader(copied,keys);selected=reader.resolve(group,args.group_id)
            rows,names,coverage=reader.read(selected,win);coverage['snapshot_databases']=wal
            coverage['account_directory']=root.parent.name
            data=write_export(out,selected,win,rows,names,coverage)
            from .images import prepare_images
            prepare_images(data,out,reader,root.parent)
    finally:
        keys.clear()
    print(str(out.resolve())+'：已导出全部所选消息。请让当前 Codex 会话完整阅读 messages.json，编写 report.json，再运行 render。')

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:raise SystemExit('已中断；已执行临时副本清理。')
