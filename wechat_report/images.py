"""Local images for selected messages. Decode -> OCR -> explicit Codex visual review.
DAT/WXGF algorithms adapted from MIT macos-toolkit c98dbb10 (see vendor license).
"""
import hashlib,io,json,os,re,struct,subprocess,tempfile,warnings
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from PIL import Image,ImageOps
from .reader import BASE,literal,require

MAX_BYTES=64*1024*1024
Image.MAX_IMAGE_PIXELS=40_000_000

def key_candidates(account_root):
    # Only the selected account and container's local kvcomm metadata. Never persist keys.
    app_data=account_root.parent.parent/'app_data'
    codes=set()
    for sub in ('net/kvcomm','ilink/kvcomm'):
        for p in (app_data/sub).glob('key_*_*.statistic'):
            match=re.fullmatch(r'key_(\d+)_.*\.statistic',p.name)
            if match:codes.add(int(match[1]))
    account_name=account_root.name
    self_id=account_name.rsplit('_',1)[0] if re.search(r'_[0-9a-f]{4}$',account_name) else account_name
    for code in sorted(codes):
        for name in sorted({account_name,self_id}):
            yield hashlib.md5((str(code)+name).encode()).hexdigest()[:16].encode(),code&255

def dat_decode(data,key,xor):
    from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
    from cryptography.hazmat.primitives.padding import PKCS7
    if len(data)<15 or data[:6] not in (b'\x07\x08V1\x08\x07',b'\x07\x08V2\x08\x07'):raise ValueError('unsupported_dat')
    plain_length,xor_length=struct.unpack('<II',data[6:14]);aes_length=plain_length+(16-plain_length%16) if plain_length else 0
    if 15+aes_length+xor_length>len(data):raise ValueError('invalid_dat_lengths')
    decryptor=Cipher(algorithms.AES(key),modes.ECB()).decryptor()
    decrypted=decryptor.update(data[15:15+aes_length])+decryptor.finalize()
    if aes_length:
        unpad=PKCS7(128).unpadder();decrypted=unpad.update(decrypted)+unpad.finalize()
    if len(decrypted)!=plain_length:raise ValueError('invalid_decrypted_length')
    tail=data[15+aes_length:]
    return decrypted+(tail[:-xor_length] if xor_length else tail)+(bytes(b^xor for b in tail[-xor_length:]) if xor_length else b'')

def variants(data,keys):
    if data.startswith((b'\x07\x08V1\x08\x07',b'\x07\x08V2\x08\x07')):
        candidates=((b'cfcd208495d565ef',x) for x in range(256)) if data.startswith(b'\x07\x08V1') else keys
        for key,xor in candidates:
            try:yield dat_decode(data,key,xor)
            except ValueError:continue
    elif data.startswith((b'\xff\xd8',b'\x89PNG',b'GIF8',b'RIFF',b'wxgf')):yield data
    elif data:
        for magic in (0xff,0x89,0x47,0x52):
            xor=data[0]^magic;yield bytes(b^xor for b in data)

def save_image(raw,dest):
    """Require real codec decode; don't call a magic-header match successful."""
    first_frame=False
    if raw.startswith(b'wxgf'):
        positions=[m.start() for m in re.finditer(b'\x00\x00\x00\x01\x40|\x00\x00\x01\x40',raw)]
        if not positions:raise ValueError('unsupported_wxgf')
        import imageio_ffmpeg
        with tempfile.TemporaryDirectory(prefix='wechat-image-decode-') as tmp:
            stream=Path(tmp)/'stream.hevc';png=Path(tmp)/'frame.png'
            stream.write_bytes(raw[min(positions):])
            proc=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','hevc','-i',str(stream),'-frames:v','1','-y',str(png)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=30)
            if proc.returncode or not png.exists():raise ValueError('wxgf_decode_failed')
            raw=png.read_bytes();first_frame=True
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as check:check.verify()
        with Image.open(io.BytesIO(raw)) as image:
            first_frame=first_frame or getattr(image,'n_frames',1)>1
            image.seek(0);image.load();frame=ImageOps.exif_transpose(image).convert('RGB')
            frame.save(dest,format='PNG')
            return {'width':frame.width,'height':frame.height,'first_frame_only':first_frame}

def decode_image(paths,account_root,out):
    keys=list(key_candidates(account_root));reasons=[]
    # Prefer original/large versions, never call an available thumbnail original.
    for path in sorted(set(paths),key=lambda p:(p.name.endswith('_t.dat'),-p.stat().st_size)):
        if path.stat().st_size>MAX_BYTES:reasons.append('oversized');continue
        stat=path.stat();data=path.read_bytes()
        if (stat.st_size,stat.st_mtime_ns)!=(path.stat().st_size,path.stat().st_mtime_ns):reasons.append('file_changed');continue
        for raw in variants(data,keys):
            try:
                meta=save_image(raw,out)
                return {'status':'needs_visual_review',**meta,'thumbnail_only':path.name.endswith('_t.dat'),
                        'asset_filename':path.name,'source_sha256':hashlib.sha256(data).hexdigest(),
                        'sha256':hashlib.sha256(out.read_bytes()).hexdigest()}
            except Exception:continue
    return {'status':'unavailable','reason':'local_image_format_or_key_unsupported' if paths else 'image_not_downloaded_or_resource_unmatched'}

def locate_assets(db,account_root,group_id,message,timezone):
    require(db,'MessageResourceInfo',['message_id','chat_id','message_svr_id','packed_info'])
    require(db,'MessageResourceDetail',['message_id','packed_info','size','status'])
    require(db,'ChatName2Id',['user_name'])
    server_id=int(message['server_id'])
    if not server_id:return [],{'matched_resource_rows':0,'reason':'server_id_unavailable'}
    rows=db.query('SELECT hex(i.packed_info) AS info,hex(d.packed_info) AS detail,d.size,d.status FROM MessageResourceInfo i '
        'JOIN MessageResourceDetail d ON d.message_id=i.message_id JOIN ChatName2Id c ON c.rowid=i.chat_id '
        f'WHERE c.user_name={literal(group_id)} AND i.message_svr_id={server_id}')
    # Month is just a directory locator; exact message association comes from resource table.
    month=datetime.fromtimestamp(message['timestamp_epoch'],ZoneInfo(timezone)).strftime('%Y-%m')
    folder=account_root/'msg/attach'/hashlib.md5(group_id.encode()).hexdigest()/month/'Img'
    allowed={}
    for row in rows:
        if row['status']!='1' or int(row['size'] or 0)<=0:continue
        hashes=set()
        for column in ('info','detail'):
            hashes.update(x.decode().lower() for x in re.findall(rb'(?<![a-fA-F0-9])[a-fA-F0-9]{32}(?![a-fA-F0-9])',bytes.fromhex(row[column] or '')))
        for h in hashes:allowed.setdefault(h,set()).add(int(row['size']))
    paths=[]
    if folder.is_dir() and folder.resolve().is_relative_to(account_root.resolve()):
        for h,sizes in allowed.items():
            for p in folder.glob(h+'*.dat'):
                if not re.fullmatch(h+r'(?:_[A-Za-z0-9]+)?\.dat',p.name) or p.is_symlink() or not p.is_file():continue
                if p.stat().st_size in sizes:paths.append(p)
    return paths,{'matched_resource_rows':len(rows),'candidate_count':len(set(paths)),
                  'association':'resource chat_id + server_id + resource filename + resource file size'}

def ocr(path):
    exe=BASE/'.local/bin/wechat-image-ocr'
    if not exe.exists():return {'status':'unavailable','reason':'ocr_executable_missing'}
    try:
        result=subprocess.run([str(exe),str(path)],capture_output=True,text=True,timeout=60)
        return json.loads(result.stdout)
    except Exception:return {'status':'unavailable','reason':'ocr_failed'}

def prepare_images(data,out,reader,account_root):
    pics=[m for m in data['messages'] if m['local_type']&0xffffffff==3]
    if not pics:return data
    media=out/'media';media.mkdir(mode=0o700,exist_ok=True)
    with reader.open('message/message_resource.db') as db:
        for message in pics:
            mid=message['id']
            if not re.fullmatch(r'm-[a-f0-9]{24}',mid):raise ValueError('invalid_message_id')
            paths,evidence=locate_assets(db,account_root,data['group']['id'],message,data['window']['timezone'])
            dest=media/(mid+'.png');info=decode_image(paths,account_root,dest)
            info['association']=evidence
            if info['status']=='needs_visual_review':
                info['path']=dest.relative_to(out).as_posix();info['ocr']=ocr(dest)
            message['image']=info
    data['image_pipeline']={'version':1,'required':True,'recognition':'Apple Vision OCR + Codex session visual review',
                            'image_count':len(pics),'prepared_count':sum(m['image']['status']=='needs_visual_review' for m in pics)}
    persist(data,out)
    return data

def persist(data,out):
    for m in data['messages']:
        if m['local_type']&0xffffffff in (3,34,43,47):
            m.pop('raw_text',None)
            m['raw_media_metadata_omitted']=True
    (out/'messages.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
    lines=[]
    for m in data['messages']:
        lines.append(f"[{m['id']}] {m['time']} {m['sender_name']} [{m['type']}]\n{m.get('text') or ''}")
        for key in ('cards','quote','image'):
            if m.get(key):lines.append(key+': '+json.dumps(m[key],ensure_ascii=False))
    (out/'messages.txt').write_text('\n'.join(lines))
    images=[{'message_id':m['id'],'server_id':m['server_id'],'time':m['time'],**m['image']} for m in data['messages'] if m.get('image')]
    (out/'images.json').write_text(json.dumps({'images':images},ensure_ascii=False,indent=2))

def image_path(out,info):
    path=out/info['path']
    if path.is_symlink() or not path.resolve().is_relative_to((out/'media').resolve()) or path.suffix!='.png':raise ValueError('unsafe_image_path')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=info['sha256']:raise ValueError('image_hash_mismatch')
    return path

def apply_reviews(out,reviews_file):
    data=json.loads((out/'messages.json').read_text());reviews=json.loads(reviews_file.read_text())
    indexed={x['message_id']:x for x in reviews['images']}
    expected={m['id'] for m in data['messages'] if m.get('image',{}).get('status') in ('needs_visual_review','reviewed')}
    if set(indexed)!=expected or len(indexed)!=len(reviews['images']):raise ValueError('每一张可解码图片必须且只能有一份审阅记录')
    for m in data['messages']:
        if m['id'] not in expected:continue
        info=m['image'];item=indexed[m['id']];image_path(out,info)
        if item.get('image_sha256')!=info['sha256']:raise ValueError('审阅记录图片指纹不匹配')
        if not item.get('summary') or not isinstance(item.get('visible_text'),list) or not isinstance(item.get('uncertainties'),list):raise ValueError('审阅需要描述、可见文字和不确定性列表')
        if item.get('reviewer')!='current_codex_session':raise ValueError('必须由当前会话实际看图后填写')
        if info.get('thumbnail_only') and not item['uncertainties']:raise ValueError('缩略图必须注明识读限制')
        info.update(status='reviewed',review={k:item[k] for k in ('summary','visible_text','uncertainties','reviewer')})
    persist(data,out)
    return data
