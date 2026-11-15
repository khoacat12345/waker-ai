from __future__ import annotations

import json
import subprocess
from pathlib import Path

from waker.cli import main
from waker.gate import AntiSlopConfig, Finding, ScanResult, scan_paths
from waker.gate.sarif import to_sarif


def write_file(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def scan(root: Path, **overrides):
    config = AntiSlopConfig(
        enable_core=False,
        enable_tests=False,
        enable_types=False,
        enable_comments=False,
        **overrides,
    )
    return scan_paths(
        root,
        config=config,
        changed_only=False,
        baseline_ref="",
        use_baseline=False,
    )


def rules(result) -> set[str]:
    return {finding.rule for finding in result.findings}


def test_architecture_cycle(tmp_path: Path) -> None:
    write_file(tmp_path, "a.py", "import b\n")
    write_file(tmp_path, "b.py", "import a\n")
    result = scan(tmp_path, enable_arch=True)
    assert "ARCH002" in rules(result)


def test_type_checking_import_does_not_form_a_cycle(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "a.py",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import b\n",
    )
    write_file(tmp_path, "b.py", "import a\n")
    result = scan(tmp_path, enable_arch=True)
    assert "ARCH002" not in rules(result)


def test_layer_inversion(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "src/core/engine.py",
        "from ..ui.dashboard import render\n\ndef run():\n    return render()\n",
    )
    write_file(tmp_path, "src/ui/dashboard.py", "def render():\n    return 'ui'\n")
    config = AntiSlopConfig(
        enable_core=False,
        enable_arch=True,
        layers={"core": ("src/core/**",), "ui": ("src/ui/**",)},
        allow_imports={"core": (), "ui": ("core",)},
    )
    result = scan_paths(
        tmp_path,
        config=config,
        changed_only=False,
        baseline_ref="",
        use_baseline=False,
    )
    assert "ARCH001" in rules(result)


def test_arch_fanout_and_dynamic_import(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "hub.py",
        "import a\nimport b\nimport c\nimport importlib\n\ndef load(name):\n    return importlib.import_module(name)\n",
    )
    for name in ("a", "b", "c"):
        write_file(tmp_path, f"{name}.py", f"VALUE = {name!r}\n")
    result = scan(tmp_path, enable_arch=True, max_fan_out=2)
    found = rules(result)
    assert "ARCH003" in found
    assert "ARCH004" in found


def test_dead_code_private_and_unused_import(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "prod.py",
        "import os\n\n"
        "def _unused():\n"
        "    return 1\n\n"
        "def used():\n"
        "    return 2\n\n"
        "def main():\n"
        "    return used()\n",
    )
    result = scan(tmp_path, enable_dead_code=True)
    found = rules(result)
    assert "DEAD001" in found
    assert "DEAD002" in found


def test_dead_code_all_exempt(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "prod.py",
        "__all__ = ['add', 'main']\n\n"
        "def add(a, b):\n"
        "    return a + b\n\n"
        "def main():\n"
        "    return add(1, 2)\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
    )
    result = scan(tmp_path, enable_dead_code=True)
    found = rules(result)
    assert "DEAD001" not in found
    assert "DEAD003" not in found


def test_dead_entry_point_is_kept(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "prod.py",
        "def main():\n    return 1\n",
    )
    write_file(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "demo"\nversion = "0.1.0"\n'
        'dependencies = []\n\n[project.scripts]\ndemo = "prod:main"\n',
    )
    result = scan(tmp_path, enable_dead_code=True)
    assert not any(
        f.rule == "DEAD003" and f.symbol == "main" for f in result.findings
    )


def test_packages_allowlist_and_mapping(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "demo"\nversion = "0.1.0"\n'
        'dependencies = ["pyyaml==6.0.2"]\n',
    )
    write_file(
        tmp_path,
        "main.py",
        "import yaml\nimport rich\nimport totally_unknown_package_xyz\n",
    )
    result = scan(tmp_path, enable_deps=True)
    found = rules(result)
    assert "PKG001" in found
    assert "PKG004" in found


def test_package_new_dependency_and_unpinned(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=False)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "test"], check=False)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@local"], check=False)
    write_file(
        repo,
        "pyproject.toml",
        '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = []\n',
    )
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=False)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "base"], check=False)
    write_file(
        repo,
        "pyproject.toml",
        '[project]\nname = "demo"\nversion = "0.1.0"\n'
        'dependencies = ["rich>=13"]\n',
    )
    config = AntiSlopConfig(
        enable_core=False,
        enable_deps=True,
    )
    result = scan_paths(
        repo,
        config=config,
        changed_only=False,
        baseline_ref="HEAD",
        use_baseline=False,
    )
    found = rules(result)
    assert "PKG002" in found
    assert "PKG003" in found


def test_security_rules_and_redaction(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "security_bad.py",
        "import os\nimport pickle\nimport subprocess\nimport yaml\nimport requests\n\n"
        "def run(cursor, x):\n"
        "    eval('1 + 1')\n"
        "    pickle.loads(b'x')\n"
        "    subprocess.run('echo x', shell=True)\n"
        "    yaml.load('a: 1')\n"
        "    requests.get('https://example.com', verify=False)\n"
        "    cursor.execute(f'SELECT * FROM t WHERE x={x}')\n"
        "    api_key = 'sk-1234567890abcdefghijklmnop'\n",
    )
    result = scan(tmp_path, enable_security=True)
    found = rules(result)
    assert {"SEC001", "SEC002", "SEC003", "SEC004", "SEC005", "SEC006", "SEC007"} <= found
    secret_messages = [f.message for f in result.findings if f.rule == "SEC006"]
    assert secret_messages
    assert "1234567890abcdefghijklmnop" not in secret_messages[0]


def test_sarif_shape() -> None:
    finding = Finding("SEC001", "error", "src/app.py", 3, 5, "eval is forbidden")
    result = ScanResult(findings=[finding], score=90, grade="A")
    sarif = to_sarif(result)
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["tool"]["driver"]["name"] == "waker-anti-slop"
    assert sarif["runs"][0]["results"][0]["ruleId"] == "SEC001"
    assert sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
        "artifactLocation"
    ]["uri"] == "src/app.py"


def test_cli_phase3_flags_and_sarif(tmp_path: Path, capsys) -> None:
    write_file(tmp_path, "a.py", "import b\n")
    write_file(tmp_path, "b.py", "import a\n")
    code = main(
        [
            "audit",
            "--all",
            "--repo",
            str(tmp_path),
            "--arch",
            "--format",
            "sarif",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 2
    assert payload["version"] == "2.1.0"
    assert any(
        result["ruleId"] == "ARCH002"
        for result in payload["runs"][0]["results"]
    )


def test_phase3_clean_all_gates(tmp_path: Path, capsys) -> None:
    write_file(
        tmp_path,
        "clean.py",
        "__all__ = ['add', 'main']\n\n"
        "def add(a, b):\n"
        "    return a + b\n\n"
        "def main():\n"
        "    return add(1, 2)\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
    )
    code = main(
        [
            "audit",
            "--all",
            "--repo",
            str(tmp_path),
            "--arch",
            "--dead-code",
            "--deps",
            "--security",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "0 finding(s)" in out
    assert "Cleanliness: 100/100 (A)" in out
