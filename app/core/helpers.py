# Low-level cross-cutting helper functions
import re
from datetime import datetime


def format_phone_number(number_str):
    """
    Standardize a phone number to E.164 format.
    """
    if not number_str:
        return ""
    # Strip non-digits
    digits = re.sub(r"\D", "", number_str)
    if not digits.startswith("1") and len(digits) == 10:
        digits = "1" + digits
    return f"+{digits}" if not digits.startswith("+") else digits


def clean_html(raw_html):
    """
    Remove HTML tags from a string.
    """
    if not raw_html:
        return ""
    cleanr = re.compile("<.*?>")
    cleantext = re.sub(cleanr, "", raw_html)
    return cleantext


def time_ago(dt):
    """
    Return a pretty 'time ago' string representation.
    """
    if not dt:
        return ""
    now = datetime.utcnow()
    diff = now - dt
    
    seconds = diff.seconds
    days = diff.days
    
    if days > 0:
        if days == 1:
            return "1 day ago"
        return f"{days} days ago"
    if seconds >= 3600:
        hours = seconds // 3600
        if hours == 1:
            return "1 hour ago"
        return f"{hours} hours ago"
    if seconds >= 60:
        minutes = seconds // 60
        if minutes == 1:
            return "1 minute ago"
        return f"{minutes} minutes ago"
    return "just now"
