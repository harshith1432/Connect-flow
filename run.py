import os
import sys
from app import create_app

app = create_app()

if __name__ == "__main__":
    print("\n>>> [STARTUP] Finalizing server setup...", file=sys.stderr)
    sys.stderr.flush()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=True)
