from flask import request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import sys

# Initialize Flask-Limiter. 
# We'll use memory:// as default storage.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["500 per day", "100 per hour"],
    storage_uri="memory://"
)

def init_rate_limiting(app):
    """
    Initialize Limiter extension on the Flask App.
    """
    limiter.init_app(app)
    
    # Custom handler for rate limit exceeded errors
    @app.errorhandler(429)
    def ratelimit_handler(e):
        sys.stderr.write(f"[SECURITY RATE LIMIT] Rate limit exceeded for IP: {request.remote_addr} on path: {request.path}\n")
        
        # If request is API or expects JSON, return JSON
        if request.path.startswith("/api/") or request.headers.get("Accept") == "application/json":
            return jsonify({
                "error": "Too Many Requests",
                "message": "You have exceeded the rate limit. Please try again later."
            }), 429
            
        # For browser UI, render a professional warning or return a simple formatted string
        return """
        <div style="font-family: system-ui, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; background: #0b0c10; color: #c5c6c7; margin: 0;">
            <div style="text-align: center; max-width: 500px; padding: 2rem; border-radius: 12px; background: #1f2833; border: 1px solid #45f3ff;">
                <h1 style="color: #45f3ff; margin-bottom: 1rem;">Rate Limit Exceeded</h1>
                <p>You have made too many requests in a short period. For security, access to this resource has been temporarily restricted.</p>
                <p style="font-size: 0.85rem; color: #8892b0; margin-top: 1.5rem;">Please wait a few moments and refresh the page.</p>
            </div>
        </div>
        """, 429
