def init_security_headers(app):
    """
    Enforces enterprise-grade security headers on all responses.
    """

    @app.after_request
    def apply_security_headers(response):
        # 1. Prevent Clickjacking
        response.headers["X-Frame-Options"] = "SAMEORIGIN"

        # 2. Prevent MIME Sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # 3. Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 4. HTTP Strict Transport Security (HSTS) - 1 year, subdomains included
        response.headers[
            "Strict-Transport-Security"
        ] = "max-age=31536000; includeSubDomains; preload"

        # 4a. Permissions Policy (restricting hardware APIs)
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        # 4b. X-XSS-Protection (Legacy filter enablement)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # 5. Content Security Policy (CSP)
        # Allows styles and images from self, fonts from fonts.gstatic.com/fonts.googleapis.com,
        # CDNs for icons, and prevents flash, object and frame embedding.
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://checkout.razorpay.com",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net",
            "img-src 'self' data: https: blob:",
            "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net",
            "frame-src 'self' https://api.razorpay.com https://checkout.razorpay.com",
            "object-src 'none'",
            "connect-src 'self' https://api.twilio.com https://api.razorpay.com",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

        # 6. Secure Caching for sensitive pages
        # Prevent caching for authenticated routes / dynamic endpoints
        if request_is_sensitive(response):
            response.headers[
                "Cache-Control"
            ] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        return response


def request_is_sensitive(response):
    """
    Determines if response is a sensitive/dynamic page that shouldn't be cached.
    """
    from flask import request

    try:
        from flask_login import current_user

        is_auth = current_user.is_authenticated
    except Exception:
        is_auth = False

    # Don't cache admin, worker, organization portals, security pages, or dynamic api requests
    path = request.path.lower()
    sensitive_prefixes = ["/platform", "/org", "/security", "/api", "/worker"]

    # Also check if it's a HTML response or JSON response (avoid static images/css files)
    content_type = response.headers.get("Content-Type", "")
    is_html_or_json = "text/html" in content_type or "application/json" in content_type

    if is_html_or_json:
        if any(path.startswith(prefix) for prefix in sensitive_prefixes) or is_auth:
            return True

    return False
