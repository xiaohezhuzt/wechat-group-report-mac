"""Install a copy of the skill without overwriting an existing installation."""
from pathlib import Path
import os
project = Path(__file__).resolve().parents[1]
codex_dir = Path(os.environ.get("CODEX_HOME", str(Path.home()/".codex")))
target = codex_dir/"skills/wechat-group-report-mac"
if target.exists() or target.is_symlink():
    raise SystemExit("已有同名技能，未覆盖：" + str(target))
target.mkdir(parents=True)
text = (project/"skills/wechat-group-report-mac/SKILL.md").read_text()
(target/"SKILL.md").write_text(text.replace("__PROJECT_ROOT__", str(project)))
print("技能已安装：" + str(target))
print("请保持项目目录位置不变，并在 Codex 新任务中检查技能是否可用。")
