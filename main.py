# All the import statements
from fastapi import FastAPI, Body, HTTPException, UploadFile, File,Form,Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import timedelta
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config
from mock_db import DB_USERS, DB_PROJECTS, DB_MESSAGES, DB_FEEDBACKS
from models import User, Project, Message, Feedback 
import os,json

load_dotenv()
config = Config(".env")
app = FastAPI()
oauth = OAuth(config)

app = FastAPI(title="Dev Cloud")


app.add_middleware(
    SessionMiddleware,
    secret_key="supersecretkey123",     # any random string works for local dev
    session_cookie="collabrun_session", # custom cookie name
    same_site="lax",                    # 👈 MUST be "lax" for local http:// testing
    https_only=False,                   # 👈 keep False for localhost
)

# For the coord policy
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000",
                   "http://127.0.0.1:3000"
                   ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

api_v1 = "/api/v1"

# for registering 
oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

oauth.register(
    name='github',
    client_id=os.getenv("GITHUB_CLIENT_ID"),
    client_secret=os.getenv("GITHUB_CLIENT_SECRET"),
    access_token_url='https://github.com/login/oauth/access_token',
    authorize_url='https://github.com/login/oauth/authorize',
    api_base_url='https://api.github.com/',
    client_kwargs={'scope': 'user:email'},
)

# for saving the image uploaded by the user during edit profile
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# User Endpoints
@app.post(f"{api_v1}/users", response_model=User)
def create_user(user: User):
    next_id = f"user_{len(DB_USERS) + 1}"
    user.id = next_id
    if user.id in DB_USERS:
        raise HTTPException(status_code=400, detail="User ID already exists")
    DB_USERS[user.id] = user
    return user

@app.get(f"{api_v1}/users", response_model=List[User])
def get_all_users():
    return list(DB_USERS.values())

@app.get(f"{api_v1}/users/{{user_id}}", response_model=User)
def get_user(user_id: str):
    user = DB_USERS.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.put(f"{api_v1}/users/{{user_id}}", response_model=User)
async def update_user(
    user_id: str,
    name: str = Form(...),
    title: str = Form(""),
    skills: str = Form("[]"),
    linked_accounts: str = Form("{}"),
    avatar: UploadFile = File(None),
):
    if user_id not in DB_USERS:
        raise HTTPException(status_code=404, detail="User not found")

    user = DB_USERS[user_id]
    user.name = name
    user.title = title
    user.skills = json.loads(skills)
    user.linked_accounts = json.loads(linked_accounts)

    if avatar:
        os.makedirs("uploads", exist_ok=True)
        ext = os.path.splitext(avatar.filename)[1]
        file_path = f"uploads/{user_id}{ext}"
        with open(file_path, "wb") as f:
            f.write(await avatar.read())
        user.avatar_url = f"http://127.0.0.1:8000/uploads/{user_id}{ext}"

    DB_USERS[user_id] = user
    return user



# 💼 Project Endpoints
@app.get(f"{api_v1}/projects", response_model=List[Project])
def get_all_projects():
    return list(DB_PROJECTS.values())

@app.post(f"{api_v1}/projects", response_model=Project, status_code=201)
def post_new_project(project_data: dict = Body(...)):
    title = project_data.get("title") or "Untitled Project"
    desc = project_data.get("description") or ""
    skills = project_data.get("skills") or []
    owner_id = project_data.get("owner_id")  # ✅ Read from frontend
    if not title or not desc:
        raise HTTPException(status_code=422, detail="Missing title or description")
    if not owner_id:
        raise HTTPException(status_code=400, detail="Missing owner_id in request")
    new_id = f"proj_{int(datetime.datetime.now().timestamp())}"
    owner_name = (DB_USERS.get(owner_id).name if owner_id in DB_USERS else "Unknown User")

    new_project = Project(
        id=new_id,
        title=title,
        organization=owner_name,
        owner_id=owner_id,
        description=desc,
        required_skills=skills,
        goal=project_data.get("goal"),
        pay=project_data.get("pay"),
        benifits=project_data.get("benifits"),
    )

    DB_PROJECTS[new_id] = new_project
    print(f"✅ New project created: {new_project.dict()}")
    return new_project




# 💬 Message Endpoint
@app.get(f"{api_v1}/messages", response_model=List[Message])
def get_all_messages(user_id: Optional[str] = None):
    """Return messages where the given user is sender or receiver."""
    if not user_id:
        return []
    return [
        msg
        for msg in DB_MESSAGES.values()
        if msg.sender_id == user_id or msg.receiver_id == user_id]

@app.post(f"{api_v1}/messages", response_model=Message)
def create_message(msg: Message):
    pair = {msg.sender_id, msg.receiver_id}

    for existing in DB_MESSAGES.values():
        existing_pair = {existing.sender_id, existing.receiver_id}
        if existing_pair != pair:
            continue
        # If an accepted application already exists, block re-applying
        if existing.status == "accepted" and msg.status == "application":
            raise HTTPException(
                status_code=400,
                detail="You have already been accepted for this project"
            )
        # If any rejection exists between the pair, block further messaging
        if existing.status == "rejected":
            raise HTTPException(
                status_code=400,
                detail="You cannot message since your application was rejected"
            )

    # ✅ Always save the message, even if loop doesn't run
    DB_MESSAGES[msg.id] = msg
    print(f"✅ New message created: {msg.dict()}")
    return msg

@app.put(f"{api_v1}/messages/{{message_id}}")
def update_message_status(message_id: str, status: str = Body(...)):
    """✅ Update message/application status (accept/reject)."""
    if message_id not in DB_MESSAGES:
        raise HTTPException(status_code=404, detail="Message not found")

    DB_MESSAGES[message_id].status = status
    return DB_MESSAGES[message_id]

# 🗣️ Feedback Endpoints
@app.get(f"{api_v1}/feedbacks/{{user_id}}", response_model=List[Feedback])
def get_feedbacks(user_id: str):
    """Get all feedback for a specific user."""
    return [fb for fb in DB_FEEDBACKS.values() if fb.user_id == user_id]

@app.post(f"{api_v1}/feedbacks", response_model=Feedback)
def add_feedback(feedback: Feedback):
    """Add feedback for a user."""
    feedback.id = f"fb_{len(DB_FEEDBACKS) + 1}"  # ✅ generate ID
    DB_FEEDBACKS[feedback.id] = feedback
    return feedback

@app.put(f"{api_v1}/feedbacks/{{feedback_id}}", response_model=Feedback)
def update_feedback(feedback_id: str, feedback: Feedback):
    """Edit existing feedback."""
    if feedback_id not in DB_FEEDBACKS:
        raise HTTPException(status_code=404, detail="Feedback not found")
    DB_FEEDBACKS[feedback_id] = feedback
    return feedback

@app.delete(f"{api_v1}/feedbacks/{{feedback_id}}")
def delete_feedback(feedback_id: str):
    """Delete feedback."""
    if feedback_id not in DB_FEEDBACKS:
        raise HTTPException(status_code=404, detail="Feedback not found")
    del DB_FEEDBACKS[feedback_id]
    return {"message": "Feedback deleted successfully"}

# Stats Endpoints
@app.get(f"{api_v1}/stats")
def get_stats():
    """Return counts for homepage metrics."""
    return {
        "projects": len(DB_PROJECTS),
        "users": len(DB_USERS),
        "messages": len(DB_MESSAGES),
    }

# Collaboration Endpoints
@app.get(f"{api_v1}/users/{{user_id}}/collaborations")
def get_user_collaborations(user_id: str):
    """
    Return all projects in which the user is involved through accepted messages.
    Ensures no duplicate projects are returned.
    """
    collab_projects = []
    seen_project_ids = set()  # ✅ track unique project IDs

    for msg in DB_MESSAGES.values():
        # ✅ Only accepted messages involving this user
        if msg.status == "accepted" and (msg.sender_id == user_id or msg.receiver_id == user_id):
            
            # ✅ Find the project related to this collaboration
            for proj in DB_PROJECTS.values():
                # ensure project owner matches one of the participants
                if proj.owner_id in (msg.sender_id, msg.receiver_id):
                    
                    # ✅ Only add if not already in the list
                    if proj.id not in seen_project_ids:
                        seen_project_ids.add(proj.id)
                        collab_projects.append({
                            "id": proj.id,
                            "title": proj.title,
                            "description": proj.description,
                            "goal": proj.goal,
                            "benifits": proj.benifits,
                            "pay": proj.pay,
                            "organization": proj.organization,
                        })

    return collab_projects

# for checking the user and logging him in
@app.post(f"{api_v1}/login")
def login_user(username: str = Form(...), password: str = Form(...)):
    """
    Authenticate user by username and password.
    """
    for user in DB_USERS.values():
        if user.name == username and user.password == password:
            return user
    raise HTTPException(status_code=401, detail="Invalid username or password")

# ✅ Login redirect (start OAuth)
@app.get("/auth/{provider}")
async def login_via_oauth(provider: str, request: Request):
    if provider not in ["google", "github", "linkedin"]:
        raise HTTPException(status_code=400, detail="Unsupported OAuth provider")

    redirect_uri = f"http://127.0.0.1:8000/auth/{provider}/callback"
    oauth_client = oauth.create_client(provider)
    print("🔹 Starting OAuth flow for:", provider)
    print("🔹 Session ID before redirect:", id(request.session))
    return await oauth_client.authorize_redirect(request, redirect_uri)


# ✅ OAuth callback (after user authorizes)
@app.get("/auth/{provider}/callback")
async def auth_callback(provider: str, request: Request):
    oauth_client = oauth.create_client(provider)
    print("🔹 Callback session ID:", id(request.session))
    try:
        token = await oauth_client.authorize_access_token(request)
    except Exception as e:
        print("❌ OAuth error:", e)
        raise HTTPException(status_code=400, detail=str(e))

    user = {}
    if provider == "google":
        user = token.get("userinfo", {})
    elif provider == "github":
        resp = await oauth_client.get("user", token=token)
        user = resp.json()
    elif provider == "linkedin":
        user_info = await oauth_client.get(
            "me?projection=(id,localizedFirstName,localizedLastName)", token=token
        )
        email_info = await oauth_client.get(
            "emailAddress?q=members&projection=(elements*(handle~))", token=token
        )
        user = user_info.json()
        user["email"] = email_info.json()["elements"][0]["handle~"]["emailAddress"]

    profile_data = {
        "name": user.get("name")
        or f"{user.get('localizedFirstName', '')} {user.get('localizedLastName', '')}".strip(),
        "email": user.get("email"),
        "avatar": user.get("avatar_url") or user.get("picture"),
        "provider": provider,
    }

    # ✅ Redirect to frontend profile
    frontend_url = f"http://localhost:3000/profile?name={profile_data['name']}&email={profile_data['email']}"
    print("✅ OAuth success, redirecting to frontend:", frontend_url)
    return RedirectResponse(url=frontend_url)

# For checking if ther server is running
@app.get("/")
def root():
    return {"message": "CollabRun API active. Visit /docs for details."}





