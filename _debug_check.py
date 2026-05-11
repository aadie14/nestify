import sqlite3, json
conn = sqlite3.connect('app/nestify.db')
conn.row_factory = sqlite3.Row

# Check project 35 in detail
row = conn.execute('SELECT * FROM projects WHERE id=35').fetchone()
print(f"Status: {row['status']}")
print(f"Pipeline: {row['pipeline_state'][:500] if row['pipeline_state'] else 'None'}")
print(f"Provider: {row['preferred_provider']}")
print(f"Public URL: {row['public_url']}")

print("\n---ALL LOGS FOR P35---")
for log in conn.execute("SELECT stage, level, message FROM logs WHERE project_id=35 ORDER BY id"):
    print(f"  [{log['level']}] {log['stage']}: {log['message'][:250]}")
