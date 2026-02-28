from app import create_app
import sqlite3, os
app = create_app()
uri = app.config['SQLALCHEMY_DATABASE_URI']
print('SQLALCHEMY_DATABASE_URI =', uri)
if uri.startswith('sqlite:///'):
    path = uri.replace('sqlite:///','')
    print('DB path:', os.path.abspath(path), 'Exists:', os.path.exists(path))
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA table_info('order')")
        cols = cur.fetchall()
        print('order table columns:')
        for c in cols:
            print(c)
    except Exception as e:
        print('Error reading schema:', e)
    conn.close()
else:
    print('Non-sqlite DB')
