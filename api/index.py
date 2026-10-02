import os
import sys

# Tambahkan direktori root dan web_app ke sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_APP_DIR = os.path.join(BASE_DIR, "web_app")

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if WEB_APP_DIR not in sys.path:
    sys.path.insert(0, WEB_APP_DIR)

from web_app.main import app
