import hashlib,io,json,os,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw,ImageFont
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from cryptography.hazmat.primitives.padding import PKCS7
from wechat_report.images import dat_decode,decode_image,ocr,locate_assets,apply_reviews,image_path
from wechat_report.reader import DB,literal
from wechat_report.render import validate,digest,render

class ImageTests(unittest.TestCase):
    def png(self):
        im=Image.new('RGB',(900,280),'white');draw=ImageDraw.Draw(im)
        font=ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc',42)
        draw.text((30,35),'项目名称：图片解析测试',fill='black',font=font)
        draw.text((30,110),'BTC 12345',fill='black',font=font)
        b=io.BytesIO();im.save(b,format='PNG');return b.getvalue()
    def dat(self,raw,key,xor):
        n=min(80,len(raw));tail=raw[n:];x=min(20,len(tail))
        pad=PKCS7(128).padder();padded=pad.update(raw[:n])+pad.finalize()
        enc=Cipher(algorithms.AES(key),modes.ECB()).encryptor()
        return b'\x07\x08V2\x08\x07'+struct.pack('<II',n,x)+b'\0'+enc.update(padded)+enc.finalize()+tail[:-x]+bytes(v^xor for v in tail[-x:])
    def test_plain_xor_dat_validation_and_ocr(self):
        raw=self.png();key=b'1234567890abcdef';xor=73;encrypted=self.dat(raw,key,xor)
        self.assertEqual(dat_decode(encrypted,key,xor),raw)
        with self.assertRaises(ValueError):dat_decode(encrypted[:20],key,xor)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);dst=p/'image.png'
            for i,body in enumerate((raw,bytes(v^71 for v in raw),encrypted)):
                src=p/f'{i}.dat';src.write_bytes(body)
                with patch('wechat_report.images.key_candidates',return_value=iter([(key,xor)])):
                    r=decode_image([src],p,dst)
                self.assertEqual(r['status'],'needs_visual_review');self.assertEqual(r['width'],900)
            result=ocr(dst);text=' '.join(x['text'] for x in result['lines'])
            self.assertIn('12345',text);self.assertIn('图片',text)
            bad=p/'bad.dat';bad.write_bytes(b'\x89PNG'+b'bad'*100)
            self.assertEqual(decode_image([bad],p,dst)['status'],'unavailable')
    def test_no_media_credentials_exported(self):
        from wechat_report.core import parse_body
        r=parse_body(b'<msg><img aeskey="PRIVATE_SENTINEL" cdnthumburl="SIGNED_SENTINEL"/></msg>',3)
        self.assertNotIn('PRIVATE_SENTINEL',json.dumps(r))
        self.assertNotIn('SIGNED_SENTINEL',json.dumps(r))
        self.assertTrue(r['raw_media_metadata_omitted'])
    def test_resource_message_and_size_binding(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);key=os.urandom(32).hex();gid='g@chatroom';h='a'*32
            folder=p/'msg/attach'/hashlib.md5(gid.encode()).hexdigest()/'2026-09/Img';folder.mkdir(parents=True)
            good=folder/(h+'.dat');good.write_bytes(b'123456')
            wrong=folder/(h+'_t.dat');wrong.write_bytes(b'bad')
            with DB(p/'r.db',key,fixture_write=True) as db:
                db.query('CREATE TABLE MessageResourceInfo(message_id INTEGER,chat_id INTEGER,message_svr_id INTEGER,packed_info BLOB);CREATE TABLE MessageResourceDetail(message_id INTEGER,packed_info BLOB,size INTEGER,status INTEGER);CREATE TABLE ChatName2Id(user_name TEXT);')
                db.query('INSERT INTO ChatName2Id VALUES('+literal(gid)+');INSERT INTO MessageResourceInfo VALUES(1,1,123,x\''+h.encode().hex()+"');INSERT INTO MessageResourceDetail VALUES(1,x'',6,1)")
                msg={'server_id':'123','timestamp_epoch':1790227192}
                paths,_=locate_assets(db,p,gid,msg,'Asia/Shanghai');self.assertEqual(paths,[good])
                self.assertEqual(locate_assets(db,p,'another@chatroom',msg,'Asia/Shanghai')[0],[])
                self.assertEqual(locate_assets(db,p,gid,dict(msg,server_id='456'),'Asia/Shanghai')[0],[])
    def test_review_required_hash_bound_and_offline_evidence(self):
        data=json.loads(Path('outputs/fixture-verified/messages.json').read_text());report=json.loads(Path('outputs/fixture-verified/report.json').read_text())
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);(out/'media').mkdir();m=next(x for x in data['messages'] if x['type']=='图片');img=out/'media/p.png';img.write_bytes(self.png());sha=hashlib.sha256(img.read_bytes()).hexdigest()
            m['image']={'status':'needs_visual_review','path':'media/p.png','sha256':sha,'thumbnail_only':False};data['image_pipeline']={'required':True,'image_count':1}
            (out/'messages.json').write_text(json.dumps(data));report['messages_sha256']=digest(data)
            with self.assertRaises(ValueError):validate(data,report)
            reviews={'images':[{'message_id':m['id'],'image_sha256':'bad','summary':'可见中文测试标题和数字','visible_text':['图片解析测试','12345'],'uncertainties':[],'reviewer':'current_codex_session'}]}
            f=out/'review.json';f.write_text(json.dumps(reviews))
            with self.assertRaises(ValueError):apply_reviews(out,f)
            reviews['images'][0]['image_sha256']=sha;f.write_text(json.dumps(reviews));data=apply_reviews(out,f)
            report['messages_sha256']=digest(data);report['reviewed_image_ids']=[m['id']];self.assertTrue(validate(data,report))
            (out/'report.json').write_text(json.dumps(report));render(out)
            self.assertIn('data:image/png;base64,',(out/'index.html').read_text())
            img.write_bytes(b'changed')
            with self.assertRaises(ValueError):image_path(out,m['image'])

if __name__=='__main__':unittest.main()
