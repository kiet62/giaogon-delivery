"""One entry point: prepare dependencies, open dashboard, run Flask."""
from pathlib import Path
import importlib.util
import os
import subprocess
import sys
import threading
import time
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent


def main():
    os.chdir(ROOT)
    env_python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if Path(sys.prefix).resolve() != (ROOT / '.venv').resolve():
        if not env_python.exists():
            print('Đang tạo môi trường Python cho GiaoGon...', flush=True)
            venv.create(ROOT / '.venv', with_pip=True)
        return subprocess.call([str(env_python), str(ROOT / 'launch.py')])
    if any(importlib.util.find_spec(m) is None for m in ['flask', 'numpy', 'sqlalchemy', 'pyodbc', 'dotenv', 'PIL', 'sklearn', 'optuna', 'scipy', 'matplotlib']):
        print('Đang cài thư viện. Lần đầu cần kết nối Internet...', flush=True)
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')])
    url = 'http://127.0.0.1:5006/'
    def open_when_ready():
        for _ in range(60):
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    if b'GiaoG' in response.read():
                        webbrowser.open(url)
                        return
            except OSError:
                pass
            time.sleep(.5)
    threading.Thread(target=open_when_ready, daemon=True).start()
    print('GiaoGon: ' + url + '\nGiữ cửa sổ này mở. Nhấn Ctrl+C để dừng.', flush=True)
    return subprocess.call([sys.executable, str(ROOT / 'app.py')])


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError) as exc:
        print('Không thể khởi động: ' + str(exc))
        sys.exit(1)
