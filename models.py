# models.py
from pydantic import BaseModel
from typing import List, Optional
import datetime
# Important classes
class LinkedAccounts(BaseModel):
    linkedin: Optional[str] = ""
    codeforces: Optional[str] = ""
    github: Optional[str] = ""

class User(BaseModel):
    id: str
    name: str
    type: Optional[str] = "individual"
    title: Optional[str] = ""
    skills: Optional[List[str]] = []
    password: str 
    linked_accounts: Optional[LinkedAccounts] = LinkedAccounts()
    avatar_url: Optional[str] = ""
    joined_on: datetime.datetime = datetime.datetime.now()

class Project(BaseModel):
    id: str
    title: str
    organization: str
    owner_id: str
    description: str
    required_skills: Optional[List[str]] = []
    pay: Optional[str] = None
    benifits: Optional[str] = None
    goal: Optional[str] = None
    created_at: datetime.datetime = datetime.datetime.now()

class Message(BaseModel):
    id: str
    sender_id: str
    receiver_id: str
    content: str
    timestamp: datetime.datetime = datetime.datetime.now()
    status: Optional[str] = "pending"

class Feedback(BaseModel):
    id: Optional[str] = None  # make id optional
    user_id: str
    author_id: str
    comment: str
    timestamp: datetime.datetime = datetime.datetime.now()
    endorsed_skill: Optional[str] = None 
