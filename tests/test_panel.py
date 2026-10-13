"""The control panel (panel/): its JavaScript tests, and static checks on the page."""

import re
import shutil
import subprocess

import pytest

from owd.config import ROOT

PANEL = ROOT / "panel"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node (preinstalled on GitHub's runners)")
def test_the_panels_javascript_tests_pass():
    run = subprocess.run(["node", "--test", str(PANEL / "panel.test.cjs")], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]


def test_every_element_the_page_script_uses_is_on_the_page():
    html = (PANEL / "index.html").read_text()
    ids = set(re.findall(r'id="([^"]+)"', html))
    used = set(re.findall(r'\$\("([^"]+)"\)', (PANEL / "page.js").read_text()))
    assert used and used <= ids, f"missing on the page: {sorted(used - ids)}"


def test_the_page_loads_only_its_own_files_and_talks_only_to_github():
    html = (PANEL / "index.html").read_text()
    assert re.findall(r'<script src="([^"]+)"', html) == ["panel.js", "page.js"]
    assert re.findall(r'<link rel="stylesheet" href="([^"]+)"', html) == ["panel.css"]
    policy = re.search(r'Content-Security-Policy"\s+content="([^"]+)"', html).group(1)
    assert "default-src 'none'" in policy and "script-src 'self'" in policy and "connect-src https://api.github.com" in policy
    for script in ("panel.js", "page.js"):
        code = (PANEL / script).read_text()
        assert "innerHTML" not in code and "eval(" not in code, script
        hosts = set(re.findall(r"https://([a-z0-9.-]+)", code))
        assert hosts <= {"api.github.com", "github.com"}, (script, hosts)
