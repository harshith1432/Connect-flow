import os
import sys
from app import create_app

# Force unbuffered output for real-time terminal display
os.environ["PYTHONUNBUFFERED"] = "1"

# Enable ANSI color support on Windows
if os.name == "nt":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-12), 7)
    except Exception:
        pass

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=True)
