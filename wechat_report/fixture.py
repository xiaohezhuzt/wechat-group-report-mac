"""Entirely invented dialogue: deliberately separates proposals, receipts and completion."""
import json
from .core import window,write_export
from .render import digest,render

def create(out):
    win=window(start='2026-09-23T10:00:00+08:00',end='2026-09-24T10:00:00+08:00',timezone='Asia/Shanghai')
    texts=[('alice',1,'建议周五上线新版本，大家先评估风险。'),('bob',1,'收到，我先核对测试结果。'),('alice',1,'决定改到下周一上线；小陈负责回归测试，周五 18 点前反馈。'),('chen',1,'同意，我来负责。目前还没执行完。'),('chen',1,'回归测试已完成，发现的登录问题已修复，测试通过。'),('bob',1,'监控阈值由谁确认？截止时间有要求吗？'),('alice',49,'<msg><appmsg><title>发布检查清单</title><des>文档卡片</des><type>5</type><url>https://example.org/checklist</url><refermsg><svrid>1003</svrid><displayname>小林</displayname><content>决定改到下周一上线</content></refermsg></appmsg></msg>'),('bob',3,'<msg><img /></msg>'),('alice',1,'安全转义测试：<script>alert("测试")</script> & 中文排版。')]
    rows=[]
    for i,(sender,kind,body) in enumerate(texts,1):
        rows.append(dict(local_id=i,server_id=str(1000+i),local_type=kind,create_time=int(win['start_epoch'])+(i-1)*600,sender_id=sender,database='message/message_0.db',table='Msg_fixture',body=(sender+':\n'+body).encode().hex()))
    rows.append(dict(rows[0],database='message/message_1.db'))
    rows.append(dict(rows[0],local_id=90,server_id='1090',create_time=int(win['end_epoch'])))
    data=write_export(out,{'name':'产品协作群 <虚构>','id':'fixture@chatroom'},win,rows,{'alice':'小林','bob':'小王','chen':'小陈'},{'warnings':['虚构数据，仅用于验证解析、统计和渲染。']},fixture=True)
    ids=[m['id'] for m in data['messages']]
    report={'messages_sha256':digest(data),'reviewed_message_ids':ids,'overview':'讨论了版本上线安排与回归测试。最初建议周五上线，随后决定调整到下周一；小陈报告回归测试完成。监控阈值的确认责任和时间仍未明确。','overview_refs':[ids[i] for i in (0,2,4,5)],'topics':[{'text':'周五上线是初始建议；小林随后明确决定改为下周一。群内未说明具体日历日期。','refs':[ids[0],ids[2]]},{'text':'小王回复“收到”仅确认收悉，不能视作同意上线安排或完成测试。','refs':[ids[1]]}],'todos':[{'text':'确认监控阈值','owner':'未明确','due':'未明确','status':'待确认','refs':[ids[5]]}],'confirmed':[{'text':'小陈在群内报告回归测试已完成、登录问题已修复且测试通过；未独立核验实际系统状态。','refs':[ids[4]]}],'unresolved':[{'text':'监控阈值由谁确认、何时完成，尚未得到回答。','refs':[ids[5]]}],'other':[{'text':'分享了“发布检查清单”链接卡片；另有一条图片消息，未解析图片内容。','refs':[ids[6],ids[7]]}]}
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return render(out)
