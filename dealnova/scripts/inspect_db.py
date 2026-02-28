from app import create_app
import os, sqlite3
app = create_app()
uri = app.config.get('SQLALCHEMY_DATABASE_URI')
print('SQLALCHEMY_DATABASE_URI =', uri)
path = None
if uri and uri.startswith('sqlite:///'):
    path = uri.replace('sqlite:///', '')
elif uri and uri.startswith('sqlite://'):
    path = uri.replace('sqlite://', '')
print('Resolved path:', path)
print('Exists:', os.path.exists(path) if path else 'n/a')
if path and os.path.exists(path):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute('PRAGMA table_info(product)')
    cols = cur.fetchall()
    print('product columns count:', len(cols))
    for c in cols:
        print(' ', c)
    conn.close()
else:
    print('No DB file to inspect')
