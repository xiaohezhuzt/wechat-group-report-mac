"""Message normalization; never infer media contents or decisions."""
import base64
import hashlib
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from defusedxml import ElementTree as ET
import zstandard

TYPES = {1:'文本',3:'图片',34:'语音',42:'名片',43:'视频',47:'表情',48:'位置',49:'卡片',10000:'系统',10002:'撤回/系统'}

def window(hours=24, start=None, end=None, timezone='Asia/Colombo'):
    zone = ZoneInfo(timezone)
    def parse(value):
        d = datetime.fromisoformat(value)
        if d.tzinfo is None: raise ValueError('指定时间必须包含 UTC 偏移，如 +08:00')
        return d.astimezone(zone)
    stop = parse(end) if end else datetime.now(zone).replace(microsecond=0)
    begin = parse(start) if start else stop-timedelta(hours=hours)
    if begin >= stop: raise ValueError('起点必须早于终点')
    return dict(start=begin.isoformat(),end=stop.isoformat(),timezone=timezone,
                start_epoch=begin.timestamp(),end_epoch=stop.timestamp(),bounds='[start,end)')

def parse_body(raw, local_type, sender_id=None):
    result={'type':TYPES.get(local_type & 0xffffffff, '未知'), 'text':None, 'cards':[], 'quote':None}
    try:
        if raw.startswith(b'\x28\xb5\x2f\xfd'): raw=zstandard.ZstdDecompressor().decompress(raw,max_output_size=32*1024*1024)
        body=raw.decode('utf-8', 'strict')
    except Exception:
        result['parse_warning']='正文无法解码；保留原始字节供核对'
        result['raw_base64']=base64.b64encode(raw).decode()
        return result
    if sender_id and body.startswith(sender_id+':\n'): body=body[len(sender_id)+2:]
    result['raw_text']=body
    kind=local_type & 0xffffffff
    if kind==1:
        result['text']=body
        result['links']=re.findall(r'https?://[^\s<>"\u3000]+',body)
    elif body.lstrip().startswith('<'):
        try:
            root=ET.fromstring(body)
            app=root.find('.//appmsg') if root.tag!='appmsg' else root
            if app is not None:
                card={k:app.findtext(k) for k in ('title','des','url','type') if app.findtext(k)}
                for k in ('fileext','totallen'):
                    v=app.findtext('appattach/'+k)
                    if v: card[k]=v
                if card: result['cards'].append(card)
                q=app.find('refermsg')
                if q is not None:
                    result['quote']={k:q.findtext(k) for k in ('svrid','fromusr','displayname','content','type') if q.findtext(k)}
            # Only use explicit client-produced voice transcription, never infer from audio.
            v=root.find('.//voicetrans')
            if v is not None and (v.get('transtext') or v.text):
                result['text']=v.get('transtext') or v.text
                result['transcription_source']='微信本地消息 XML voicetrans'
        except Exception:
            result['parse_warning']='XML 无法安全解析，未推断内容'
    if kind in (3,34,43,47):
        # Raw media XML can contain CDN AES keys or signed URLs; don't export credentials.
        result.pop('raw_text',None)
        result['raw_media_metadata_omitted']=True
    return result

def normalize(rows, chat_id, win, names):
    messages=[]; seen={}; duplicates=0
    for row in rows:
        stamp=int(row['create_time'])
        # Explicit epoch-unit detection; reject ambiguous dates outside modern WeChat era.
        unit=1 if 1_000_000_000<=stamp<10_000_000_000 else 1000 if 1_000_000_000_000<=stamp<10_000_000_000_000 else None
        if unit is None: raise ValueError('未知时间戳单位，停止导出')
        seconds=stamp/unit
        if not win['start_epoch']<=seconds<win['end_epoch']: continue
        sid=str(row.get('server_id') or '0')
        source={'database':row['database'],'table':row['table'],'local_id':int(row['local_id']),'server_id':sid}
        raw=bytes.fromhex(row['body'])
        content_hash=hashlib.sha256(raw).hexdigest()
        identity=f'{chat_id}:server:{sid}' if sid not in ('0','') else f"{chat_id}:{row['database']}:{row['local_id']}"
        if identity in seen:
            existing=seen[identity]
            if existing['raw_sha256']!=content_hash or existing['timestamp_epoch']!=seconds or existing['sender_id']!=row.get('sender_id'):
                raise ValueError('相同服务器消息 ID 内容冲突，停止以免错误去重')
            existing['sources'].append(source); duplicates+=1; continue
        mid='m-'+hashlib.sha256(identity.encode()).hexdigest()[:24]
        sender=row.get('sender_id')
        msg={'id':mid,'server_id':sid,'sender_id':sender,'sender_name':names.get(sender,sender or '未识别发送人'),
             'timestamp_epoch':seconds,'timestamp_unit':'seconds' if unit==1 else 'milliseconds',
             'time':datetime.fromtimestamp(seconds,ZoneInfo(win['timezone'])).isoformat(),
             'local_type':int(row['local_type']),'sources':[source],'raw_sha256':content_hash,
             **parse_body(raw,int(row['local_type']),sender)}
        seen[identity]=msg; messages.append(msg)
    messages.sort(key=lambda m:(m['timestamp_epoch'],int(m['server_id']),m['sources'][0]['database'],m['sources'][0]['local_id']))
    return messages,duplicates

def write_export(out, group, win, rows, names, coverage, fixture=False):
    out.mkdir(parents=True,exist_ok=False,mode=0o700)
    msgs,dups=normalize(rows,group['id'],win,names)
    data={'schema_version':1,'fixture':fixture,'group':group,'window':win,
          'stats':{'message_count':len(msgs),'speaker_count':len({m['sender_id'] for m in msgs if m['sender_id']}),
                   'unknown_sender_messages':sum(m['sender_id'] is None for m in msgs),'duplicates_removed':dups},
          'coverage':coverage,'messages':msgs}
    (out/'messages.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
    lines=[f"{group['name']} ({group['id']})",f"{win['start']} ≤ 时间 < {win['end']} [{win['timezone']}]",'']
    for m in msgs:
        lines.append(f"[{m['id']}] {m['time']} {m['sender_name']} [{m['type']}]\n{m.get('text') or ''}")
        if m['cards']: lines.append(json.dumps(m['cards'],ensure_ascii=False))
        if m['quote']: lines.append('引用（历史上下文，不计入本次消息）: '+json.dumps(m['quote'],ensure_ascii=False))
    (out/'messages.txt').write_text('\n'.join(lines))
    return data
