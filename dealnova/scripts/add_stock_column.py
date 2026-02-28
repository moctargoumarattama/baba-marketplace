import sqlite3
p='instance/dealnova.db'
conn=sqlite3.connect(p)
cur=conn.cursor()
try:
    cur.execute("ALTER TABLE product ADD COLUMN stock INTEGER DEFAULT 0 NOT NULL")
    conn.commit()
    print('Added stock column')
except Exception as e:
    print('Error:', e)
finally:
    conn.close()
