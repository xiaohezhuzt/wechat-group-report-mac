import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from wechat_report.core import window,normalize,parse_body
from wechat_report.reader import DB,Reader,snapshot,literal
from wechat_report.render import digest,validate
from wechat_report.fixture import create

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.win=window(start='2026-09-23T00:00:00+08:00',end='2026-09-24T00:00:00+08:00',timezone='Asia/Shanghai')
    def row(self,i,ts,body='你好'):
        return dict(local_id=i,server_id=str(i),create_time=ts,local_type=1,sender_id='u',body=body.encode().hex(),database='message/message_0.db',table='Msg_test')
    def test_boundaries_units_dedup(self):
        a,b=self.win['start_epoch'],self.win['end_epoch']
        r=[self.row(1,a-1),self.row(2,a),self.row(3,b),self.row(4,(a+2)*1000),self.row(2,a)]
        m,d=normalize(r,'g',self.win,{})
        self.assertEqual([x['server_id'] for x in m],['2','4']);self.assertEqual(d,1)
    def test_conflicting_duplicates_rejected(self):
        a=self.win['start_epoch']
        with self.assertRaises(ValueError):normalize([self.row(1,a),self.row(1,a,'变更')],'g',self.win,{})
    def test_unknown_unit_rejected(self):
        with self.assertRaises(ValueError):normalize([self.row(1,99)],'g',self.win,{})
    def test_xml_entities_and_media(self):
        x=parse_body(b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><msg>&x;</msg>',49)
        self.assertIn('parse_warning',x)
        self.assertIsNone(parse_body(b'<msg><img/></msg>',3)['text'])
    def test_compression_quote(self):
        import zstandard
        x=parse_body(zstandard.ZstdCompressor().compress('u:\n中文'.encode()),1,'u')
        self.assertEqual(x['text'],'中文')
    def test_report_gate(self):
        data=json.loads(Path('outputs/fixture-verified/messages.json').read_text());r=json.loads(Path('outputs/fixture-verified/report.json').read_text())
        self.assertTrue(validate(data,r));r['reviewed_message_ids'].pop()
        with self.assertRaises(ValueError):validate(data,r)
        r=json.loads(Path('outputs/fixture-verified/report.json').read_text());r['topics'][0]['refs']=['invented']
        with self.assertRaises(ValueError):validate(data,r)

class DatabaseTests(unittest.TestCase):
    def test_upstream_wal_crypto(self):
        from sqlcipher_probe import self_test
        self.assertGreaterEqual(self_test()['fixture_tests_passed'],10)
    def test_adapter_full_pagination_snapshot_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'contact').mkdir();(root/'message').mkdir()
            key=os.urandom(32).hex();keys={'contact/contact.db':key,'message/message_0.db':key}
            gid='toy@chatroom';table='Msg_'+hashlib.md5(gid.encode()).hexdigest()
            win=window(start='2026-09-23T00:00:00+08:00',end='2026-09-24T00:00:00+08:00',timezone='Asia/Shanghai');a=int(win['start_epoch'])
            with DB(root/'contact/contact.db',key,fixture_write=True) as c,DB(root/'message/message_0.db',key,fixture_write=True) as m:
                c.query('CREATE TABLE contact(username TEXT,nick_name TEXT,remark TEXT); INSERT INTO contact VALUES('+literal(gid)+','+literal('完整群名')+',NULL); INSERT INTO contact VALUES(\'u\',\'测试用户\',NULL)')
                m.query(f'PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; CREATE TABLE "{table}"(local_id INTEGER PRIMARY KEY, server_id INTEGER, local_type INTEGER, create_time INTEGER,real_sender_id INTEGER,message_content BLOB); CREATE TABLE Name2Id(user_name TEXT); INSERT INTO Name2Id VALUES(\'u\'); PRAGMA wal_checkpoint(TRUNCATE)')
                m.query('BEGIN;'+''.join(f'INSERT INTO "{table}" VALUES({i},{i},1,{a+i},1,x\'e6b58be8af95\');' for i in range(1,1202))+'COMMIT;')
                m.query('BEGIN;'+f'INSERT INTO "{table}" VALUES(2000,2000,1,{a+2000},1,\'uncommitted\');')
                before=(root/'message/message_0.db').read_bytes()
                with snapshot(root) as (snap,infos):
                    copied=snap;reader=Reader(snap,keys);group=reader.resolve('完整群名');rows,names,cov=reader.read(group,win)
                    self.assertEqual(len(rows),1201);self.assertEqual(names['u'],'测试用户');self.assertTrue(cov['all_selected_rows_read'])
                    with self.assertRaises(ValueError):reader.resolve('完整')
                self.assertFalse(copied.exists());self.assertEqual(before,(root/'message/message_0.db').read_bytes())
                m.query('ROLLBACK')
                with self.assertRaises(RuntimeError):
                    with snapshot(root) as (copied,_):raise RuntimeError('模拟异常')
                self.assertFalse(copied.exists())
                c.query('INSERT INTO contact VALUES(\'second@chatroom\','+literal('完整群名')+',NULL)')
                with snapshot(root) as (snap,_):
                    with self.assertRaises(ValueError):Reader(snap,keys).resolve('完整群名')
                    self.assertEqual(Reader(snap,keys).resolve('完整群名',gid)['id'],gid)

if __name__=='__main__':unittest.main()
