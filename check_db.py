import sqlite3
try:
    conn = sqlite3.connect('data_cache/quant_history.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM monthly_factor')
    count = cursor.fetchone()[0]
    with open('db_count.txt', 'w') as f:
        f.write(str(count))
    conn.close()
except Exception as e:
    with open('db_count.txt', 'w') as f:
        f.write(str(e))
