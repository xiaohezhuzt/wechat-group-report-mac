import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from playwright.sync_api import sync_playwright
from wechat_report.render import render

class RenderTests(unittest.TestCase):
    def test_offline_sources_escaping_and_multi_png(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            for name in ('messages.json','report.json'):shutil.copy2(Path('outputs/fixture-verified')/name,out/name)
            report=json.loads((out/'report.json').read_text())
            report['other'].append({'text':'<script>window.BAD=true</script> & 中文测试','refs':report['overview_refs'][:1]})
            report['topics']*=40
            (out/'report.json').write_text(json.dumps(report,ensure_ascii=False))
            result=render(out)
            self.assertGreater(len(result['png_files']),1)
            total=sum(struct.unpack('>II',(out/name).read_bytes()[16:24])[1] for name in result['png_files'])
            self.assertAlmostEqual(total,2*result['css_height'],delta=4)
            with sync_playwright() as p:
                b=p.chromium.launch();page=b.new_page(offline=True)
                page.goto((out/'index.html').as_uri())
                self.assertFalse(page.locator('#sources').evaluate('(e)=>e.open'))
                self.assertIsNone(page.evaluate('window.BAD'))
                page.locator('a[href^="#src-"]').first.click()
                self.assertTrue(page.locator('#sources').evaluate('(e)=>e.open'))
                b.close()

if __name__=='__main__':unittest.main()
