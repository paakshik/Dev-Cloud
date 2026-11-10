import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, or_, select
from sqlalchemy.schema import CreateSchema
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from starlette.config import Config
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse

from cache import cache_get, cache_set, invalidate_cache, redis_health
from database import Base, engine, get_db
from models import (
    Feedback, FeedbackRecord, Message, MessageRecord, Project, ProjectRecord,
    User, UserRecord, utc_now,
)
from schema_migrations import apply_postgres_additive_migrations

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
config = Config(str(BASE_DIR / ".env"))
app = FastAPI(title="Dev Cloud")
oauth = OAuth(config)

PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "http://127.0.0.1:8000").rstrip("/")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
ALLOWED_ORIGINS = [origin.strip().rstrip("/") for origin in os.getenv(
    "CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
).split(",") if origin.strip()]
if FRONTEND_URL not in ALLOWED_ORIGINS:
    ALLOWED_ORIGINS.append(FRONTEND_URL)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "dev-only-change-this-session-secret"),
    session_cookie="collabrun_session",
    same_site="lax",
    https_only=os.getenv("COOKIE_HTTPS_ONLY", "false").lower() == "true",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_v1 = "/api/v1"
password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth is optional; add the provider credentials to backend/.env to enable it.
if os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"):
    oauth.register(
        name="google",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
if os.getenv("GITHUB_CLIENT_ID") and os.getenv("GITHUB_CLIENT_SECRET"):
    oauth.register(
        name="github",
        client_id=os.getenv("GITHUB_CLIENT_ID"),
        client_secret=os.getenv("GITHUB_CLIENT_SECRET"),
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={"scope": "user:email"},
    )


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def as_user(record: UserRecord) -> User:
    return User.model_validate(record)


def as_project(record: ProjectRecord) -> Project:
    return Project.model_validate(record)


def as_message(record: MessageRecord) -> Message:
    return Message.model_validate(record)


def as_feedback(record: FeedbackRecord) -> Feedback:
    return Feedback.model_validate(record)


@app.on_event("startup")
def initialize_database():
    with engine.begin() as connection:
        connection.execute(CreateSchema("collabrun_app", if_not_exists=True))
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        apply_postgres_additive_migrations(connection)
    # Import the bundled sample records once, only where their IDs are not present.
    seed_file = BASE_DIR / "mock_data.json"
    if not seed_file.exists():
        return
    with seed_file.open("r", encoding="utf-8") as file:
        seed = json.load(file)
    with Session(engine) as db:
        for user_id, data in seed.get("users", {}).items():
            if db.get(UserRecord, user_id) is None:
                linked = data.get("linked_accounts") or {}
                if hasattr(linked, "dict"):
                    linked = linked.dict()
                db.add(UserRecord(
                    id=user_id, name=data["name"], type=data.get("type", "individual"),
                    title=data.get("title", ""), skills=data.get("skills", []),
                    password=password_context.hash(data["password"]), linked_accounts=linked,
                    avatar_url=data.get("avatar_url", ""),
                    joined_on=data.get("joined_on") or utc_now(),
                ))
        db.flush()
        for project_id, data in seed.get("projects", {}).items():
            if db.get(ProjectRecord, project_id) is None and db.get(UserRecord, data.get("owner_id")):
                db.add(ProjectRecord(
                    id=project_id, title=data["title"], organization=data.get("organization", ""),
                    owner_id=data["owner_id"], description=data.get("description", ""),
                    required_skills=data.get("required_skills", data.get("skills", [])),
                    pay=data.get("pay"), benifits=data.get("benifits", data.get("benefits")),
                    goal=data.get("goal"), created_at=data.get("created_at") or utc_now(),
                ))
        db.flush()
        for message_id, data in seed.get("messages", {}).items():
            if db.get(MessageRecord, message_id) is None and db.get(UserRecord, data.get("sender_id")) and db.get(UserRecord, data.get("receiver_id")):
                timestamp = data.get("timestamp")
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp)
                db.add(MessageRecord(
                    id=message_id, sender_id=data["sender_id"], receiver_id=data["receiver_id"],
                    content=data["content"], timestamp=timestamp or utc_now(),
                    status=data.get("status", "pending"),
                ))
        db.commit()


@app.post(f"{api_v1}/users", response_model=User)
def create_user(user: User, db: Session = Depends(get_db)):
    record = UserRecord(
        id=user.id or new_id("user"), name=user.name, type=user.type or "individual",
        title=user.title or "", skills=user.skills or [], password=password_context.hash(user.password),
        linked_accounts=(user.linked_accounts.model_dump() if user.linked_accounts else {}),
        avatar_url=user.avatar_url or "", joined_on=user.joined_on,
    )
    if db.get(UserRecord, record.id):
        raise HTTPException(status_code=400, detail="User ID already exists")
    if db.scalar(select(UserRecord.id).where(UserRecord.name == record.name)):
        raise HTTPException(status_code=409, detail="Username is already taken")
    db.add(record)
    db.commit()
    db.refresh(record)
    invalidate_cache("users:list:*", "stats:*")
    return as_user(record)


@app.get(f"{api_v1}/users", response_model=List[User])
def get_all_users(
    limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    key = f"users:list:{limit}:{offset}"
    cached = cache_get(key)
    if cached is not None:
        return [{**item, "password": ""} for item in cached]
    records = db.scalars(
        select(UserRecord).order_by(UserRecord.joined_on, UserRecord.id).limit(limit).offset(offset)
    ).all()
    result = [{**as_user(item).model_dump(mode="json"), "password": ""} for item in records]
    cache_set(key, result)
    return result


@app.get(f"{api_v1}/users/{{user_id}}", response_model=User)
def get_user(user_id: str, db: Session = Depends(get_db)):
    record = db.get(UserRecord, user_id)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    return as_user(record)


@app.put(f"{api_v1}/users/{{user_id}}", response_model=User)
async def update_user(
    user_id: str, name: str = Form(...), title: str = Form(""),
    skills: str = Form("[]"), linked_accounts: str = Form("{}"),
    avatar: UploadFile = File(None), db: Session = Depends(get_db),
):
    record = db.get(UserRecord, user_id)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        record.skills = json.loads(skills)
        record.linked_accounts = json.loads(linked_accounts)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail="skills and linked_accounts must be valid JSON") from error
    record.name = name
    record.title = title
    if avatar and avatar.filename:
        record.avatar_data = await avatar.read()
        record.avatar_content_type = avatar.content_type or "application/octet-stream"
        record.avatar_url = f"{PUBLIC_API_URL}/api/v1/users/{user_id}/avatar"
    db.commit()
    db.refresh(record)
    invalidate_cache("users:list:*")
    return as_user(record)


@app.get(f"{api_v1}/users/{{user_id}}/avatar")
def get_user_avatar(user_id: str, db: Session = Depends(get_db)):
    record = db.get(UserRecord, user_id)
    if not record or not record.avatar_data:
        raise HTTPException(status_code=404, detail="Avatar not found")
    return Response(content=record.avatar_data, media_type=record.avatar_content_type or "application/octet-stream")


@app.get(f"{api_v1}/projects", response_model=List[Project])
def get_all_projects(
    limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    key = f"projects:list:{limit}:{offset}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    records = db.scalars(
        select(ProjectRecord).order_by(ProjectRecord.created_at.desc(), ProjectRecord.id.desc()).limit(limit).offset(offset)
    ).all()
    result = [as_project(item).model_dump(mode="json") for item in records]
    cache_set(key, result)
    return result


@app.post(f"{api_v1}/projects", response_model=Project, status_code=201)
def post_new_project(project_data: dict = Body(...), db: Session = Depends(get_db)):
    title = (project_data.get("title") or "Untitled Project").strip()
    desc = (project_data.get("description") or "").strip()
    owner_id = project_data.get("owner_id")
    if not desc:
        raise HTTPException(status_code=422, detail="Missing title or description")
    owner = db.get(UserRecord, owner_id) if owner_id else None
    if not owner:
        raise HTTPException(status_code=400, detail="Missing or invalid owner_id in request")
    record = ProjectRecord(
        id=new_id("proj"), title=title, organization=owner.name, owner_id=owner_id,
        description=desc, required_skills=project_data.get("skills") or project_data.get("required_skills") or [],
        goal=project_data.get("goal"), pay=project_data.get("pay"),
        benifits=project_data.get("benefits") or project_data.get("benifits"),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    invalidate_cache("projects:list:*", "stats:*")
    return as_project(record)


@app.get(f"{api_v1}/messages", response_model=List[Message])
def get_all_messages(
    user_id: Optional[str] = None, limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    if not user_id:
        return []
    key = f"messages:user:{user_id}:{limit}:{offset}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    records = db.scalars(select(MessageRecord).where(
        or_(MessageRecord.sender_id == user_id, MessageRecord.receiver_id == user_id)
    ).order_by(MessageRecord.timestamp, MessageRecord.id).limit(limit).offset(offset)).all()
    result = [as_message(item).model_dump(mode="json") for item in records]
    cache_set(key, result)
    return result


@app.post(f"{api_v1}/messages", response_model=Message)
def create_message(msg: Message, db: Session = Depends(get_db)):
    if not db.get(UserRecord, msg.sender_id) or not db.get(UserRecord, msg.receiver_id):
        raise HTTPException(status_code=400, detail="Sender or receiver does not exist")
    pair_match = or_(
        (MessageRecord.sender_id == msg.sender_id) & (MessageRecord.receiver_id == msg.receiver_id),
        (MessageRecord.sender_id == msg.receiver_id) & (MessageRecord.receiver_id == msg.sender_id),
    )
    existing_records = db.scalars(select(MessageRecord).where(pair_match)).all()
    is_application = msg.status == "application" or msg.content.lower().startswith("application for ")
    if any(item.status == "accepted" for item in existing_records) and is_application:
        raise HTTPException(status_code=400, detail="You have already been accepted for this project")
    if any(item.status == "rejected" for item in existing_records):
        raise HTTPException(status_code=400, detail="You cannot message since your application was rejected")
    record = MessageRecord(**msg.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    invalidate_cache("messages:user:*", "stats:*")
    return as_message(record)


@app.put(f"{api_v1}/messages/{{message_id}}")
def update_message_status(message_id: str, status: str = Body(...), db: Session = Depends(get_db)):
    record = db.get(MessageRecord, message_id)
    if not record:
        raise HTTPException(status_code=404, detail="Message not found")
    record.status = status
    db.commit()
    db.refresh(record)
    invalidate_cache("messages:user:*", "stats:*")
    return as_message(record)


@app.get(f"{api_v1}/feedbacks/{{user_id}}", response_model=List[Feedback])
def get_feedbacks(
    user_id: str, limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    key = f"feedback:user:{user_id}:{limit}:{offset}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    records = db.scalars(select(FeedbackRecord).where(FeedbackRecord.user_id == user_id)
        .order_by(FeedbackRecord.timestamp.desc(), FeedbackRecord.id).limit(limit).offset(offset)).all()
    result = [as_feedback(item).model_dump(mode="json") for item in records]
    cache_set(key, result)
    return result


@app.post(f"{api_v1}/feedbacks", response_model=Feedback)
def add_feedback(feedback: Feedback, db: Session = Depends(get_db)):
    record = FeedbackRecord(
        id=feedback.id or new_id("fb"), user_id=feedback.user_id,
        author_id=feedback.author_id, comment=feedback.comment,
        timestamp=feedback.timestamp, endorsed_skill=feedback.endorsed_skill,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    invalidate_cache(f"feedback:user:{record.user_id}:*")
    return as_feedback(record)


@app.put(f"{api_v1}/feedbacks/{{feedback_id}}", response_model=Feedback)
def update_feedback(feedback_id: str, feedback: Feedback, db: Session = Depends(get_db)):
    record = db.get(FeedbackRecord, feedback_id)
    if not record:
        raise HTTPException(status_code=404, detail="Feedback not found")
    previous_user_id = record.user_id
    record.user_id = feedback.user_id
    record.author_id = feedback.author_id
    record.comment = feedback.comment
    record.timestamp = feedback.timestamp
    record.endorsed_skill = feedback.endorsed_skill
    db.commit()
    db.refresh(record)
    invalidate_cache(f"feedback:user:{previous_user_id}:*", f"feedback:user:{record.user_id}:*")
    return as_feedback(record)


@app.delete(f"{api_v1}/feedbacks/{{feedback_id}}")
def delete_feedback(feedback_id: str, db: Session = Depends(get_db)):
    record = db.get(FeedbackRecord, feedback_id)
    if not record:
        raise HTTPException(status_code=404, detail="Feedback not found")
    user_id = record.user_id
    db.delete(record)
    db.commit()
    invalidate_cache(f"feedback:user:{user_id}:*")
    return {"message": "Feedback deleted successfully"}


@app.get(f"{api_v1}/stats")
def get_stats(response: Response, db: Session = Depends(get_db)):
    key = "stats:summary"
    cached = cache_get(key)
    if cached is not None:
        return cached
    result = {
        "projects": db.scalar(select(func.count()).select_from(ProjectRecord)) or 0,
        "users": db.scalar(select(func.count()).select_from(UserRecord)) or 0,
        "messages": db.scalar(select(func.count()).select_from(MessageRecord)) or 0,
    }
    cache_set(key, result)
    return result


@app.get(f"{api_v1}/users/{{user_id}}/collaborations")
def get_user_collaborations(user_id: str, db: Session = Depends(get_db)):
    accepted = db.scalars(select(MessageRecord).where(
        MessageRecord.status == "accepted",
        or_(MessageRecord.sender_id == user_id, MessageRecord.receiver_id == user_id),
    )).all()
    participant_ids = {person for message in accepted for person in (message.sender_id, message.receiver_id)}
    if not participant_ids:
        return []
    projects = db.scalars(select(ProjectRecord).where(ProjectRecord.owner_id.in_(participant_ids))).all()
    return [
        {"id": project.id, "title": project.title, "description": project.description,
         "goal": project.goal, "benifits": project.benifits, "pay": project.pay,
         "organization": project.organization}
        for project in projects
    ]


@app.post(f"{api_v1}/login")
def login_user(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    record = db.scalar(select(UserRecord).where(UserRecord.name == username))
    if not record or not password_context.verify(password, record.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return as_user(record)


@app.get("/auth/{provider}")
async def login_via_oauth(provider: str, request: Request):
    if provider not in ["google", "github", "linkedin"]:
        raise HTTPException(status_code=400, detail="Unsupported OAuth provider")
    client = oauth.create_client(provider)
    if client is None:
        raise HTTPException(status_code=400, detail=f"{provider} OAuth is not configured")
    redirect_uri = f"{PUBLIC_API_URL}/auth/{provider}/callback"
    return await client.authorize_redirect(request, redirect_uri)


@app.get("/auth/{provider}/callback")
async def auth_callback(provider: str, request: Request):
    client = oauth.create_client(provider)
    if client is None:
        raise HTTPException(status_code=400, detail=f"{provider} OAuth is not configured")
    try:
        token = await client.authorize_access_token(request)
    except Exception as error:
        raise HTTPException(status_code=400, detail="OAuth authentication failed") from error
    if provider == "google":
        user = token.get("userinfo", {})
    elif provider == "github":
        response = await client.get("user", token=token)
        user = response.json()
    else:
        raise HTTPException(status_code=400, detail="LinkedIn OAuth is not configured")
    name = user.get("name") or user.get("login") or ""
    frontend_url = FRONTEND_URL + "/profile?" + __import__("urllib.parse", fromlist=["urlencode"]).urlencode({
        "name": name, "email": user.get("email", ""), "avatar": user.get("avatar_url") or user.get("picture", "")
    })
    return RedirectResponse(url=frontend_url)


@app.get("/health")
def health():
    return {"status": "ok", "redis": "connected" if redis_health() else "disabled_or_unavailable"}


@app.get("/")
def root():
    return {"message": "CollabRun API active. Visit /docs for details."}
