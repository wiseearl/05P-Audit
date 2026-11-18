"""MCP Server 守護行程 (Supervisor) - 完整支援跨平台與 UTF-8 中英特殊字元。

功能：
1. 自動守護 server.py：收到熱重啟訊號 (Exit Code 0) 即時重啟。
2. 崩潰防禦：連續異常崩潰達 3 次自動以 server.py.bak 執行災難還原。
3. 完美編碼支援：使用原生 Python Subprocess 與 UTF-8 輸出串流，徹底避免 Windows cmd 批次檔亂碼與特殊符號中斷。
"""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
SERVER_PY = BASE_DIR / "server.py"
BAK_PY = BASE_DIR / "server.py.bak"
MAX_CONSECUTIVE_CRASHES = 3


def get_now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    os.chdir(BASE_DIR)
    fail_count = 0

    print("=" * 65)
    print("  🚀 MCP Server Supervisor 啟動中...")
    print("  📌 支援：自動熱重啟、多語系 UTF-8、連線中斷防禦與自動災難還原")
    print("=" * 65, flush=True)

    while True:
        print(f"[{get_now()}] 正在啟動 MCP Server (server.py)...", flush=True)
        try:
            # 啟動 server.py 並由 Python 守護進程接管
            proc = subprocess.Popen([sys.executable, str(SERVER_PY)], cwd=str(BASE_DIR))
            exit_code = proc.wait()
        except KeyboardInterrupt:
            print(f"\n[{get_now()}] 收到手動中斷訊號 (Ctrl+C)，Supervisor 正常退出。", flush=True)
            break
        except Exception as e:
            print(f"[{get_now()}] 啟動伺服器程序發生異常: {e}", flush=True)
            exit_code = 1

        print(f"[{get_now()}] Server 程序已結束，結束代碼 (Exit Code): {exit_code}", flush=True)

        # 正常退出 / 自主更新重啟 (Exit Code 0)
        if exit_code == 0:
            print(f"[{get_now()}] [Supervisor] 正常熱重啟請求，準備重新拉起伺服器...", flush=True)
            fail_count = 0
            time.sleep(1)
            continue

        # 異常退出 (Crash)
        fail_count += 1
        print(
            f"[{get_now()}] [Supervisor] ⚠️ 偵測到異常崩潰！連續失敗次數: {fail_count}/{MAX_CONSECUTIVE_CRASHES}",
            flush=True,
        )

        if fail_count >= MAX_CONSECUTIVE_CRASHES:
            print(f"[{get_now()}] [Supervisor] 🚨 警告：已連續崩潰 {MAX_CONSECUTIVE_CRASHES} 次，新程式碼可能存在致命錯誤！", flush=True)
            if BAK_PY.exists():
                print(f"[{get_now()}] [Supervisor] 正在自動從 server.py.bak 執行災難復原...", flush=True)
                shutil.copyfile(BAK_PY, SERVER_PY)
                print(f"[{get_now()}] [Supervisor] ✅ 還原完成！重置計數並啟動穩定版本...", flush=True)
                fail_count = 0
                time.sleep(2)
                continue
            else:
                print(f"[{get_now()}] [Supervisor] ❌ 錯誤：找不到 server.py.bak，無法自動復原，請手動介入檢查！", flush=True)
                time.sleep(5)
                sys.exit(1)

        time.sleep(2)


if __name__ == "__main__":
    main()
