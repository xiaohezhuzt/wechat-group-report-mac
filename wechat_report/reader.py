"""Strict adapter for the inspected macOS WeChat 4.x schema. Fail closed on mismatch."""
import contextlib
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'vendor/macos_toolkit'))
os.environ.setdefault('SQLCIPHER_LIBRARY',str(BASE/'.local/lib/libsqlcipher.dylib'))
from sqlcipher_probe import DB
from disk_inventory import wal_info

def literal(text): return "CAST(x'"+text.encode().hex()+"' AS TEXT)"
def roots(): return sorted((Path.home()/'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files').glob('*/db_storage'))
def source_paths(root):
    return [root/'contact/contact.db']+sorted(p for p in (root/'message').glob('message_*.db') if re.fullmatch(r'message_\d+\.db',p.name))

def signatures(paths):
    result={}
    for p in paths:
        for f in (p,Path(str(p)+'-wal')):
            if f.exists():
                s=f.stat();result[str(f)]=(s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    return result

@contextlib.contextmanager
def snapshot(root, database_paths=None):
    """Encrypted DB+WAL copy; require all sources unchanged for full copy interval.
    SHM is rebuilt only on private copy. No plaintext DB is ever created.
    """
    paths=database_paths if database_paths is not None else source_paths(root)
    if not paths or any(not p.resolve().is_relative_to(root.resolve()) for p in paths): raise RuntimeError('数据库列表为空或不属于所选账号')
    with tempfile.TemporaryDirectory(prefix='wechat-report-encrypted-') as tmp:
        dest=Path(tmp);os.chmod(dest,0o700)
        for attempt in range(3):
            before=signatures(paths)
            for src in paths:
                dst=dest/src.relative_to(root);dst.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(src,dst)
                wal=Path(str(src)+'-wal');outwal=Path(str(dst)+'-wal')
                if wal.exists(): shutil.copy2(wal,outwal)
                elif outwal.exists(): outwal.unlink()
            if before==signatures(paths): break
        else: raise RuntimeError('微信数据库持续变动，无法得到稳定副本；请稍后重试')
        details=[]
        for src in paths:
            dst=dest/src.relative_to(root);w=Path(str(dst)+'-wal');info=wal_info(w)
            if info.get('bytes',0):
                if not info.get('header_checksum_valid') or info.get('page_size')!=4096 or info.get('scan_end')=='invalid_or_incomplete_frame':
                    raise RuntimeError('WAL 校验失败，拒绝忽略或输出不完整记录')
                # Keep only checksum-valid committed prefix. Ignore old/preallocated/uncommitted tail.
                last=info.get('last_commit_frame_in_prefix',0)
                if last:
                    with w.open('r+b') as f: f.truncate(32+last*(24+4096))
                else:w.unlink()
            details.append({'database':str(src.relative_to(root)),'wal':info})
        yield dest,details

def columns(db, table): return {x['name'] for x in db.query('PRAGMA table_info("'+table+'")')}
def require(db,table,expected):
    if not set(expected)<=columns(db,table): raise RuntimeError('不匹配的实际数据库结构：'+table)

class Reader:
    def __init__(self,root,keys):self.root=root;self.keys=keys
    def open(self,rel):
        value=self.keys.get(str(rel))
        if isinstance(value,dict):value=value.get('enc_key')
        if not value:raise RuntimeError('尚未获取该分片的有效密钥：'+str(rel))
        return DB(self.root/rel,value)
    def resolve(self,name,group_id=None):
        with self.open('contact/contact.db') as db:
            require(db,'contact',['username','nick_name','remark'])
            matches=db.query('SELECT username,nick_name,remark FROM contact WHERE nick_name='+literal(name))
        matches=[x for x in matches if x['username'].endswith('@chatroom')]
        if group_id: matches=[x for x in matches if x['username']==group_id]
        if len(matches)!=1:
            raise ValueError('完整群名未唯一匹配，请核对群名或使用 --group-id：'+str(matches))
        return {'id':matches[0]['username'],'name':matches[0]['nick_name'],'remark':matches[0]['remark']}
    def read(self,group,win):
        table='Msg_'+hashlib.md5(group['id'].encode()).hexdigest(); rows=[]; shards=[]
        for p in source_paths(self.root)[1:]:
            rel=p.relative_to(self.root)
            with self.open(rel) as db:
                if not db.query('SELECT name FROM sqlite_master WHERE type=\'table\' AND name='+literal(table)):continue
                require(db,table,['local_id','server_id','local_type','create_time','real_sender_id','message_content'])
                require(db,'Name2Id',['user_name'])
                # Both known epoch units covered in SQL; normalization validates each selected row.
                a,b=win['start_epoch'],win['end_epoch']
                where=f'((create_time >= {a} AND create_time < {b}) OR (create_time >= {a*1000} AND create_time < {b*1000}))'
                count=int(db.query(f'SELECT count(*) n FROM "{table}" WHERE {where}')[0]['n'])
                db.query('BEGIN')
                cursor=-1;read_count=0
                while True:
                    batch=db.query(f'SELECT local_id,server_id,local_type,create_time,real_sender_id,hex(message_content) body FROM "{table}" WHERE {where} AND local_id>{cursor} ORDER BY local_id LIMIT 500')
                    if not batch:break
                    for row in batch:
                        sender=db.query('SELECT user_name FROM Name2Id WHERE rowid='+str(int(row['real_sender_id'])))
                        row.update(sender_id=sender[0]['user_name'] if len(sender)==1 else None,database=str(rel),table=table)
                    rows+=batch;read_count+=len(batch);cursor=int(batch[-1]['local_id'])
                db.query('COMMIT')
                if read_count!=count:raise RuntimeError('分批读取条数与数据库计数不一致')
                shards.append({'database':str(rel),'selected_rows':count,'schema_verified':True})
        if not shards:raise RuntimeError('本地消息分片未找到指定群表')
        names={}
        with self.open('contact/contact.db') as db:
            for uid in {r['sender_id'] for r in rows if r['sender_id']}:
                c=db.query('SELECT nick_name,remark FROM contact WHERE username='+literal(uid))
                if len(c)==1:names[uid]=c[0]['remark'] or c[0]['nick_name'] or uid
        coverage={'shards':shards,'all_selected_rows_read':True,'warnings':['无法从本地库证明同步完整性；没有消息也不等于群内无人发言。','发言人显示联系人备注或昵称；尚未验证群内专用昵称字段。']}
        return rows,names,coverage
