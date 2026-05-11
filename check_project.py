#!/usr/bin/env python3
import sqlite3
import json

conn = sqlite3.connect('app/nestify.db')
cursor = conn.cursor()

# Get project info
cursor.execute("SELECT id, name, status, pipeline_state FROM projects WHERE id = 38 LIMIT 1")
project = cursor.fetchone()
print("PROJECT INFO:")
print(f"  ID: {project[0]}")
print(f"  Name: {project[1]}")
print(f"  Status: {project[2]}")
if project[3]:
    try:
        state = json.loads(project[3])
        print(f"  Pipeline State: {json.dumps(state, indent=2)[:500]}")
    except:
        print(f"  Pipeline State: {project[3][:500]}")

# Get deployment info  
cursor.execute("SELECT id, provider, status, deployment_url FROM deployments WHERE project_id = 38")
deployments = cursor.fetchall()
print("\nDEPLOYMENTS:")
if deployments:
    for d in deployments:
        print(f"  Provider: {d[1]}, Status: {d[2]}, URL: {d[3]}")
else:
    print("  (No deployments yet)")

conn.close()
