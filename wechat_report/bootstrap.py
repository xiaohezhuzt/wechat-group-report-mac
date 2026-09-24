"""Ephemeral LLDB capture. Requires user to quit WeChat; keys never touch disk."""
import os
from pathlib import Path
import json
import signal
import subprocess
import tempfile
from .reader import BASE,source_paths

def run(args):
    p=subprocess.run(args,capture_output=True,text=True)
    if p.returncode:raise RuntimeError('命令失败：'+Path(args[0]).name)
    return p.stdout or p.stderr

def capture(root, database_paths=None, *, allow_interactive=False):
    if not allow_interactive:
        raise RuntimeError("默认不启动微信登录或重启流程。当前没有可用的临时密钥；请使用已有导出。只有用户明确同意本次登录操作后才可启用 --interactive-login。")
    selected=database_paths if database_paths is not None else source_paths(root)
    selected=[p.resolve(strict=True) for p in selected]
    if not selected or any(not p.is_relative_to(root.resolve()) or p.suffix!=".db" for p in selected):
        raise RuntimeError("所选数据库必须位于该账号目录")
    selected_args=[arg for p in selected for arg in ("--database",str(p.relative_to(root.resolve())))]
    if subprocess.run(['pgrep','-x','WeChat'],capture_output=True).returncode==0:
        raise RuntimeError('请先正常退出微信；临时副本启动后可能需要点击登录或手机确认')
    app=Path('/Applications/WeChat.app');signature=run(['codesign','-dvv',str(app)])
    run(['codesign','--verify','--deep','--strict',str(app)])
    readfd,writefd=os.pipe();proc=None
    try:
        with tempfile.TemporaryDirectory(prefix='wechat-report-app-') as d:
            shadow=Path(d)/'WeChat.app'
            try:
                run(['/usr/bin/ditto',str(app),str(shadow)])
                run(['codesign','--force','--deep','--sign','-',str(shadow)])
                run(['codesign','--verify','--deep','--strict',str(shadow)])
                env=dict(os.environ,PYTHONPATH=run(['/usr/bin/lldb','-P']).strip())
                print('临时微信副本即将启动。请点击进入微信，并按需要在手机上确认。',flush=True)
                proc=subprocess.Popen(['/usr/bin/python3',str(BASE/'vendor/macos_toolkit/capture_keys.py'),'--exe',str(shadow/'Contents/MacOS/WeChat'),'--db-root',str(root),'--key-fd',str(writefd),'--timeout','240']+selected_args,env=env,pass_fds=(writefd,))
                os.close(writefd);writefd=None
                with os.fdopen(readfd,'rb') as pipe:
                    readfd=None;payload=pipe.read(65536)
                rc=proc.wait(timeout=15)
                if rc or not payload:raise RuntimeError('未取得有效密钥；未读取真实消息')
                keys=json.loads(payload)['keys'];payload=None
                if set(keys)!={str(p.relative_to(root.resolve())) for p in selected}:raise RuntimeError('密钥未覆盖全部必要分片，拒绝输出不完整记录')
                return keys
            finally:
                if proc and proc.poll() is None:
                    proc.send_signal(signal.SIGINT)
                    try:proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()
                ls='/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
                subprocess.run([ls,'-u',str(shadow)],capture_output=True)
                if run(['codesign','-dvv',str(app)])!=signature:raise RuntimeError('原微信签名意外变化')
                subprocess.Popen([str(app/'Contents/MacOS/WeChat')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    finally:
        if readfd is not None:os.close(readfd)
        if writefd is not None:os.close(writefd)
