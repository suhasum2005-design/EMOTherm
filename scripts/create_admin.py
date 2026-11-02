"""Explicit admin provisioning; public signup always creates a normal user."""
import argparse
import getpass
import uuid
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bcrypt
from sqlalchemy import select
from backend.main import DB, User, now

parser=argparse.ArgumentParser()
parser.add_argument('--email',required=True)
parser.add_argument('--name',default='Administrator')
args=parser.parse_args()
password=getpass.getpass('Admin password (10+ characters): ')
if not 10<=len(password.encode())<=72:
    raise SystemExit('Use 10–72 UTF-8 bytes.')
with DB.begin() as db:
    if db.scalar(select(User).where(User.email==args.email.lower())):
        raise SystemExit('Email exists. Use a different admin email.')
    db.add(User(id=str(uuid.uuid4()),email=args.email.lower(),name=args.name,password_hash=bcrypt.hashpw(password.encode(),bcrypt.gensalt()).decode(),role='admin',active=True,camera_mode='uvc',theme='dark',created_at=now()))
print('Administrator created.')
