"""
Echo_Bot 可视化测试面板

用法：
  python run_tests.py          # 运行测试并在终端显示
  python run_tests.py --web    # 启动 Web 可视化面板
  python run_tests.py --html   # 生成 HTML 测试报告
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

# 确保项目根目录在 path 中
_project_root = Path(__file__).parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def run_all_tests() -> dict:
    """
    运行所有测试并返回结构化结果。

    Returns:
        {
            "summary": {"total": N, "passed": N, "failed": N, "errors": N, "time": "0.65s"},
            "modules": [
                {
                    "name": "TestCharacterManager",
                    "status": "passed",
                    "time": "0.12s",
                    "cases": [
                        {"name": "test_list_characters", "status": "passed", "msg": ""},
                        ...
                    ]
                },
                ...
            ]
        }
    """
    import unittest

    # 加载测试
    loader = unittest.TestLoader()
    suite = loader.discover(
        str(_project_root / "tests"),
        pattern="test_core.py",
        top_level_dir=str(_project_root),
    )

    results = {
        "summary": {"total": 0, "passed": 0, "failed": 0, "errors": 0, "time": "0s"},
        "modules": [],
    }

    start_time = time.time()
    # 用列表包裹，子类中修改引用
    state = {"current_module": None}

    class VisualTestResult(unittest.TestResult):
        def startTest(self, test):
            class_name = test.__class__.__name__
            method_name = test._testMethodName

            cm = state["current_module"]
            if cm is None or cm["name"] != class_name:
                if cm is not None:
                    results["modules"].append(cm)
                cm = {
                    "name": class_name,
                    "status": "passed",
                    "time": "0s",
                    "cases": [],
                    "_start": time.time(),
                }
                state["current_module"] = cm

            state["current_module"]["cases"].append({
                "name": method_name,
                "status": "running",
                "msg": "",
            })

        def addSuccess(self, test):
            case = state["current_module"]["cases"][-1]
            case["status"] = "passed"
            results["summary"]["passed"] += 1
            results["summary"]["total"] += 1

        def addFailure(self, test, err):
            case = state["current_module"]["cases"][-1]
            case["status"] = "failed"
            case["msg"] = str(err[1])
            state["current_module"]["status"] = "failed"
            results["summary"]["failed"] += 1
            results["summary"]["total"] += 1

        def addError(self, test, err):
            case = state["current_module"]["cases"][-1]
            case["status"] = "error"
            case["msg"] = str(err[1])
            state["current_module"]["status"] = "failed"
            results["summary"]["errors"] += 1
            results["summary"]["total"] += 1

    runner = unittest.TextTestRunner(resultclass=VisualTestResult, verbosity=0)
    runner.run(suite)

    # 结束最后一个模块
    cm = state["current_module"]
    if cm is not None:
        cm["time"] = f"{time.time() - cm['_start']:.2f}s"
        del cm["_start"]
        results["modules"].append(cm)

    results["summary"]["time"] = f"{time.time() - start_time:.2f}s"
    return results


def print_terminal(results: dict):
    """终端彩色输出"""
    s = results["summary"]
    print(f"\n{'='*50}")
    print(f"  Echo_Bot Test Report")
    print(f"  Total:{s['total']}  Pass:{s['passed']}  Fail:{s['failed']}  Error:{s['errors']}  Time:{s['time']}")
    print(f"{'='*50}\n")

    for mod in results["modules"]:
        icon = "[OK]" if mod["status"] == "passed" else "[!!]"
        print(f"  {icon} {mod['name']} ({mod['time']})")
        for case in mod["cases"]:
            ci = "[OK]" if case["status"] == "passed" else "[!!]"
            print(f"    {ci} {case['name']}")
            if case["msg"]:
                print(f"       |-> {case['msg'][:80]}")
    print()


def generate_html(results: dict) -> str:
    """生成 HTML 测试报告"""
    s = results["summary"]
    mods_html = ""
    for mod in results["modules"]:
        status_icon = "✅" if mod["status"] == "passed" else "❌"
        cases_html = ""
        for case in mod["cases"]:
            ci = "✅" if case["status"] == "passed" else "❌"
            msg_html = f'<div class="case-msg">{case["msg"][:100]}</div>' if case["msg"] else ""
            cases_html += f'''
            <div class="case {case["status"]}">
              <span class="case-icon">{ci}</span>
              <span class="case-name">{case["name"]}</span>
              {msg_html}
            </div>'''

        mods_html += f'''
        <div class="module {mod["status"]}">
          <div class="module-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
            <span>{status_icon} {mod["name"]}</span>
            <span class="module-time">{mod["time"]}</span>
          </div>
          <div class="module-cases">{cases_html}</div>
        </div>'''

    passed_pct = round(s["passed"] / max(s["total"], 1) * 100)
    color = "#22c55e" if passed_pct == 100 else "#eab308" if passed_pct >= 80 else "#ef4444"

    return f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Echo_Bot 测试报告</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:#f8fafc; color:#1e293b; padding:20px; }}
.header {{ max-width:800px; margin:0 auto; background:linear-gradient(135deg,#6366f1,#8b5cf6); color:#fff; border-radius:12px; padding:24px 32px; }}
.header h1 {{ font-size:20px; }}
.summary {{ display:flex; gap:16px; margin-top:12px; flex-wrap:wrap; }}
.stat {{ background:rgba(255,255,255,0.15); border-radius:8px; padding:8px 16px; font-size:14px; }}
.stat-num {{ font-size:24px; font-weight:700; }}
.passed .stat-num {{ color:#22c55e; }}
.failed .stat-num {{ color:#ef4444; }}
.container {{ max-width:800px; margin:0 auto; }}
.progress-bar {{ height:6px; background:#e2e8f0; border-radius:3px; margin:16px 0; overflow:hidden; }}
.progress-fill {{ height:100%; background:{color}; border-radius:3px; width:{passed_pct}%; transition:width 1s; }}
.module {{ background:#fff; border-radius:8px; margin-bottom:8px; box-shadow:0 1px 3px rgba(0,0,0,0.06); overflow:hidden; }}
.module-header {{ padding:12px 16px; cursor:pointer; display:flex; justify-content:space-between; align-items:center; font-weight:600; font-size:14px; user-select:none; }}
.module-header:hover {{ background:#f1f5f9; }}
.module-time {{ color:#94a3b8; font-size:12px; }}
.module.failed .module-header {{ border-left:3px solid #ef4444; }}
.module.passed .module-header {{ border-left:3px solid #22c55e; }}
.module-cases {{ }}
.module-cases.collapsed {{ display:none; }}
.case {{ padding:8px 16px 8px 36px; font-size:13px; display:flex; align-items:center; gap:8px; border-top:1px solid #f1f5f9; }}
.case-icon {{ font-size:14px; }}
.case-name {{ }}
.case.failed {{ background:#fef2f2; }}
.case-msg {{ color:#ef4444; font-size:12px; margin-left:24px; }}
.footer {{ text-align:center; padding:20px; color:#94a3b8; font-size:12px; }}
</style>
</head>
<body>
<div class="container">
<div class="header">
  <h1>Echo_Bot 测试报告</h1>
  <div class="summary">
    <div class="stat"><div class="stat-num">{s["total"]}</div>总测试</div>
    <div class="stat passed"><div class="stat-num">{s["passed"]}</div>通过</div>
    <div class="stat failed"><div class="stat-num">{s["failed"]}</div>失败</div>
    <div class="stat"><div class="stat-num">{s["errors"]}</div>错误</div>
    <div class="stat"><div class="stat-num">{s["time"]}</div>耗时</div>
  </div>
  <div class="progress-bar"><div class="progress-fill"></div></div>
</div>
{mods_html}
<div class="footer">Echo_Bot Test Runner · 生成时间 {time.strftime("%Y-%m-%d %H:%M:%S")}</div>
</div>
</body>
</html>'''


def start_web_server(results: dict):
    """启动 Web 可视化面板"""
    html = generate_html(results)
    port = 8877

    # 写入临时文件
    report_path = _project_root / "test_report.html"
    report_path.write_text(html, encoding="utf-8")

    # 启动 HTTP 服务器
    from http.server import HTTPServer, SimpleHTTPRequestHandler
    os.chdir(str(_project_root))

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                self.send_response(302)
                self.send_header("Location", "/test_report.html")
                self.end_headers()
            else:
                super().do_GET()

        def log_message(self, *a):
            pass

    print(f"\n  测试面板已启动: http://localhost:{port}")
    print(f"  HTML 报告: {report_path}")
    print(f"  Ctrl+C 停止服务\n")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


def main():
    parser = argparse.ArgumentParser(description="Echo_Bot 可视化测试")
    parser.add_argument("--web", "-w", action="store_true", help="启动 Web 可视化面板")
    parser.add_argument("--html", "-m", action="store_true", help="生成 HTML 报告并打开")
    args = parser.parse_args()

    print("  正在运行测试...")
    results = run_all_tests()

    if args.web:
        start_web_server(results)
    elif args.html:
        html = generate_html(results)
        report_path = _project_root / "test_report.html"
        report_path.write_text(html, encoding="utf-8")
        print(f"\n  HTML 报告已生成: {report_path}")
        os.startfile(str(report_path))
    else:
        print_terminal(results)

    # 非 Web 模式返回退出码
    if not args.web:
        sys.exit(0 if results["summary"]["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
