"""Application runner and entry points."""
# runner.py
from . import config
from .data import seed
from .support_db import connect, init_db

def setup(db_path=None):
    conn = connect(db_path or config.DB_PATH)
    init_db(conn)
    seed(conn)
    return conn