import json
import datetime
from typing import Dict
from models import User, Project, Message, Feedback  

DB_USERS: Dict[str, User] = {}
DB_PROJECTS: Dict[str, Project] = {}
DB_MESSAGES: Dict[str, Message] = {}
DB_FEEDBACKS: Dict[str, Feedback] = {}

# 🧠 Load data from JSON file
with open("mock_data.json", "r") as f:
    data = json.load(f)

# 🔄 Convert JSON objects into model instances
for uid, u in data.get("users", {}).items():
    DB_USERS[uid] = User(**u)

for pid, p in data.get("projects", {}).items():
    DB_PROJECTS[pid] = Project(**p)

for mid, m in data.get("messages", {}).items():
    m["timestamp"] = datetime.datetime.fromisoformat(m["timestamp"])
    DB_MESSAGES[mid] = Message(**m)
