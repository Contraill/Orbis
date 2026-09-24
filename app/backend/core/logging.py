"""Redact opaque room/capability paths from Uvicorn's WebSocket messages."""
import logging
import re


class PrivatePathFilter(logging.Filter):
    def filter(self, record):
        text=record.getMessage()
        record.msg=re.sub(r'(/api/(?:playback/sources|watch-together/rooms)/)[^\s"?]+',r'\1[redacted]',text)
        record.args=()
        return True


def install():
    logging.getLogger('uvicorn.error').addFilter(PrivatePathFilter())
