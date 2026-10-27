import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = sorted([*REPO.glob("monitor/scripts/*.sh"), *REPO.glob("scripts/*.sh")])

# macOS 自带的 bash 3.2 在 UTF-8 环境下，会把紧跟在 $变量 后面的中文的第一个字节当成变量名的一部分：
# set -u 时报 "PY?: unbound variable"，否则变量直接变成空的。所以变量后面紧跟非 ASCII 字符时必须写成 ${变量}
BARE_VARIABLE_BEFORE_NON_ASCII = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*(?=[^\x00-\x7f])")


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: str(path.relative_to(REPO)))
def test_variables_before_chinese_text_use_braces(script: Path):
    bad = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1)
        if BARE_VARIABLE_BEFORE_NON_ASCII.search(line)
    ]
    assert not bad, "\n".join(bad)
