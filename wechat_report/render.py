import hashlib
import html
import json
import math
from pathlib import Path
from playwright.sync_api import sync_playwright

SECTIONS=[('topics','主要话题及讨论结论'),('todos','待办事项'),('confirmed','已解决或已确认事项'),('unresolved','尚未解决的问题'),('other','其他信息')]

def digest(data):
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def validate(data, report):
    if report.get('messages_sha256')!=digest(data): raise ValueError('报告未绑定当前完整消息数据')
    if data.get('image_pipeline',{}).get('required'):
        image_ids=set()
        for m in data['messages']:
            if m['local_type']&0xffffffff!=3:continue
            info=m.get('image',{})
            if info.get('status') not in ('reviewed','unavailable'):raise ValueError('存在尚未实际审阅的图片，不能生成最终报告')
            if info['status']=='reviewed':
                if not info.get('review',{}).get('summary'):raise ValueError('图片审阅缺少描述')
                image_ids.add(m['id'])
            elif not info.get('reason'):raise ValueError('图片不可用必须说明原因')
        if set(report.get('reviewed_image_ids',[]))!=image_ids:raise ValueError('报告必须登记全部已审阅图片')
    ids={m['id'] for m in data['messages']}
    if set(report.get('reviewed_message_ids',[]))!=ids: raise ValueError('必须读完全部消息并登记 reviewed_message_ids')
    if len(report['reviewed_message_ids'])!=len(ids): raise ValueError('已读清单有重复项')
    if not report.get('overview'): raise ValueError('缺少概览')
    allclaims=[{'text':report['overview'],'refs':report.get('overview_refs',[])}]
    for key,_ in SECTIONS:
        items=report.get(key)
        if not isinstance(items,list): raise ValueError('缺少章节 '+key)
        allclaims+=items
        if key=='todos':
            for x in items:
                if any(not x.get(k) for k in ('owner','due','status')): raise ValueError('待办缺少负责人、时间或状态（可填未明确）')
    for claim in allclaims:
        if not claim.get('text'): raise ValueError('空结论')
        if ids and not claim.get('refs'): raise ValueError('重要结论必须引用消息')
        if any(i not in ids for i in claim.get('refs',[])): raise ValueError('引用消息不存在')
    if data['stats']['message_count']!=len(ids): raise ValueError('消息统计不一致')
    return True

CSS='''*{box-sizing:border-box}body{margin:0;background:#edf3f1;color:#203831;font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;font-size:16px;line-height:1.8}main{max-width:960px;margin:32px auto;background:white;padding:42px;border-radius:22px}header{border-bottom:3px solid #158060;padding-bottom:24px}h1{font-size:30px;margin:4px 0 16px;line-height:1.4}h2{font-size:21px;color:#11684d;margin:28px 0 12px}p{white-space:pre-wrap;overflow-wrap:anywhere}.eyebrow{font-size:13px;letter-spacing:2px;color:#117353}.meta,.notice{font-size:14px;color:#586b64}.notice{background:#f0f6f2;padding:14px 18px;border-radius:10px}.stats{display:flex;gap:30px;padding:16px 0}.stats b{font-size:26px;color:#11684d}.item{padding:12px 18px;margin:10px 0;background:#f6f8f7;border-radius:10px;break-inside:avoid}.item p{margin:0 0 6px}.refs{font-size:12px;color:#117353;overflow-wrap:anywhere}a{color:#117353}summary{cursor:pointer;color:#117353}details{border-top:1px solid #dce8e0;padding:12px 0}.source{padding:12px;background:#f7faf8;margin:10px 0;overflow-wrap:anywhere}pre{white-space:pre-wrap;font:inherit;font-size:14px}.print-source{display:none}footer{font-size:12px;color:#64786e;border-top:1px solid #dce8e0;margin-top:28px;padding-top:16px}@media(max-width:600px){main{margin:0;border-radius:0;padding:22px}h1{font-size:25px}.stats{gap:18px}}'''

def render(out):
    out=Path(out).resolve(); data=json.loads((out/'messages.json').read_text()); report=json.loads((out/'report.json').read_text()); validate(data,report)
    esc=lambda x:html.escape(str(x),quote=True)
    win=data['window']; group=data['group']; stats=data['stats']
    ref_labels={m['id']:f'消息 {i:03d}' for i,m in enumerate(data['messages'],1)}
    refs=lambda ids:'<div class="refs">来源：'+ ' · '.join(f'<a href="#src-{esc(i)}">{esc(ref_labels[i])}</a>' for i in ids)+'</div>'
    scope='仅统计该账号在本机已同步、成功读取的指定群聊记录，不代表该群完整历史。未解析的图片、视频、语音和表情仅标注类型。'
    warn='；'.join(data['coverage'].get('warnings',[]))
    if data.get('image_pipeline'):
        count=sum(m.get('image',{}).get('status')=='reviewed' for m in data['messages'])
        total=data['image_pipeline']['image_count']
        scope+=f' 本次图片 {total} 张：已审阅 {count} 张，不可用 {total-count} 张。图片文字是画面内容，不代表外部事实已核实。'
    badge='虚构数据测试 · 非真实聊天' if data['fixture'] else '本地已同步聊天记录'
    body=f'<main><header><div class="eyebrow">{esc(badge)}</div><h1>{esc(group["name"])}</h1><div class="meta">群 ID：{esc(group["id"])}<br>{esc(win["start"])} ≤ 时间 &lt; {esc(win["end"])}<br>时区：{esc(win["timezone"])}</div><div class="stats"><span><b>{stats["message_count"]}</b> 条消息</span><span><b>{stats["speaker_count"]}</b> 位发言人</span></div></header><p class="notice">{esc(scope)}<br>{esc(warn)}</p><h2>概览</h2><p>{esc(report["overview"])}</p>'+refs(report['overview_refs'])
    md=[f'# {group["name"]}',badge,f'群 ID：{group["id"]}',f'{win["start"]} ≤ 时间 < {win["end"]}（{win["timezone"]}）',f'{stats["message_count"]} 条消息，{stats["speaker_count"]} 位发言人。',scope,warn,'## 概览',report['overview'],'来源：'+', '.join(report['overview_refs'])]
    for key,title in SECTIONS:
        body+=f'<section><h2>{title}</h2>'; md+=['## '+title]
        if not report[key]: body+='<p class="meta">本次记录未发现明确事项。</p>'; md+=['本次记录未发现明确事项。']
        for item in report[key]:
            extra=''
            if key=='todos': extra=f'负责人：{item["owner"]} ｜ 时间要求：{item["due"]} ｜ 状态：{item["status"]}'
            body+=f'<article class="item"><p>{esc(item["text"])}</p><div class="meta">{esc(extra)}</div>'+refs(item['refs'])+'</article>'
            md += ['- '+item['text']+('（'+extra+'）' if extra else '')+' [来源：'+', '.join(item['refs'])+']']
        body+='</section>'
    used=set(report['overview_refs'])
    for key,_ in SECTIONS:
        for x in report[key]: used.update(x['refs'])
    body+='<details id="sources"><summary>查看总结引用的消息来源</summary>'
    for m in data['messages']:
        if m['id'] not in used and not m.get('image'): continue
        excerpt=m.get('text') or ('['+m['type']+']')
        if m['cards']: excerpt+='\n'+json.dumps(m['cards'],ensure_ascii=False)
        if m['quote']: excerpt+='\n历史引用（不计入统计）：'+json.dumps(m['quote'],ensure_ascii=False)
        image_html=''
        if m.get('image'):
            info=m['image']
            if info['status']=='reviewed':
                from .images import image_path
                import base64
                raw=image_path(out,info).read_bytes()
                image_html='<img style="max-width:100%;height:auto" loading="lazy" alt="消息图片" src="data:image/png;base64,'+base64.b64encode(raw).decode()+'">'
                excerpt+='\n图片审阅：'+info['review']['summary']+'\n可见文字：'+'；'.join(info['review']['visible_text'])+'\n不确定性：'+'；'.join(info['review']['uncertainties'])
            else:excerpt+='\n图片不可用：'+info.get('reason','未明确')
        body+=f'<div class="source" id="src-{esc(m["id"])}"><b>{esc(m["sender_name"])}</b> · {esc(m["time"])}<div class="refs">{esc(ref_labels[m['id']])} · {esc(m["id"])} · 服务器 ID {esc(m["server_id"])}</div><pre>{esc(excerpt)}</pre>{image_html}</div>'
    body+='</details><footer>由 Codex 会话结合全部导出消息撰写；群内说法不等于独立核实的事实。引用存在性已机器校验，含义需结合原文复核。完整来源见同目录 messages.json / messages.txt。</footer></main>'
    script="document.querySelectorAll('a[href^=\"#src-\"]').forEach(a=>a.addEventListener('click',()=>{document.getElementById('sources').open=true}));"
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; script-src \'unsafe-inline\'; img-src data:"><title>'+esc(group['name'])+' · 聊天总结</title><style>'+CSS+'</style><body>'+body+'<script>'+script+'</script></body></html>'
    (out/'index.html').write_text(page); (out/'summary.md').write_text('\n\n'.join(md)+'\n')
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=browser.new_context(viewport={'width':1000,'height':800},device_scale_factor=2,offline=True)
        tab=context.new_page(); tab.goto((out/'index.html').as_uri()); tab.evaluate('document.fonts.ready')
        height=tab.evaluate('document.documentElement.scrollHeight')
        # Split at section/article boundaries where possible. Adjacent clips cover every pixel.
        boundaries=tab.locator('article,section,h2,footer,details').evaluate_all('(els)=>els.map(e=>e.getBoundingClientRect().top+scrollY)')
        max_height=7000; clips=[]; y=0
        while y<height:
            end=min(height,y+max_height)
            if end<height:
                choices=[int(b) for b in boundaries if y+max_height*.6<b<=end]
                if choices: end=max(choices)
            clips.append((y,end-y)); y=end
        paths=[]
        for n,(top,h) in enumerate(clips,1):
            name='report.png' if n==1 else f'report-{n:02d}.png'
            tab.screenshot(path=str(out/name),full_page=True,clip={'x':0,'y':top,'width':1000,'height':h},animations='disabled')
            import struct
            width_px,height_px=struct.unpack('>II',(out/name).read_bytes()[16:24])
            if width_px!=2000 or abs(height_px-h*2)>2: raise RuntimeError('PNG 尺寸不匹配，可能截断')
            paths.append(name)
        tab.set_viewport_size({'width':390,'height':844})
        overflow=tab.evaluate('document.documentElement.scrollWidth > innerWidth')
        if overflow: raise RuntimeError('移动端发生横向溢出')
        browser.close()
    result={'png_files':paths,'css_height':height,'pixel_scale':2,'split_reason':'报告超过 7000 CSS 像素，连续分图完整保留内容' if len(paths)>1 else None,'offline_render_verified':True,'mobile_overflow':False}
    (out/'render-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result
