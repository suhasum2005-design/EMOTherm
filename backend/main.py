import asyncio
import base64
import hashlib
import io
import json
import os
import re
import secrets
import threading
import time
import uuid
from collections import Counter, defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import bcrypt
import jwt
import torch
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker, Session as DBSession
from backend.models import Base, User, Upload, Prediction, Block, Audit, Session, CameraTicket, ChainLock
from backend.crypto import Vault
from backend.certificates import signed_certificate, verify_signed_certificate, certificate_pdf, sha256
from blockchain.chain import canonical, mine, is_chain_valid, record_hash
from camera.bridge import Camera
from ml.data import preprocess
from ml.inference import Predictor

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
DATA = Path(os.getenv('DATA_DIR', str(ROOT / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
SECRET = os.getenv('JWT_SECRET', '')
if len(SECRET) < 32 or SECRET.startswith('GENERATE'):
    raise RuntimeError('Run python scripts/init_env.py to configure secure secrets.')
KEY = base64.b64decode(os.environ['AES_MASTER_KEY'])
if len(KEY) != 32:
    raise RuntimeError('AES_MASTER_KEY must decode to 32 bytes.')
ORIGINS = os.getenv('CORS_ORIGINS', 'http://localhost:5173,http://localhost:8080').split(',')
SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
DB_URL = os.getenv('DATABASE_URL', 'sqlite:///' + (DATA/'emotherm.db').as_posix())
engine = create_engine(DB_URL, connect_args={'check_same_thread':False} if DB_URL.startswith('sqlite') else {}, pool_pre_ping=True)
DB = sessionmaker(bind=engine, expire_on_commit=False)
Base.metadata.create_all(engine)
with DB.begin() as db:
    if db.get(ChainLock, 1) is None:
        db.add(ChainLock(id=1))
vault = Vault(KEY, DATA)
torch.set_num_threads(2)
predictor = Predictor(os.getenv('MODEL_PATH', str(ROOT/'ml/artifacts/model_v2.npz')))
camera = Camera()
chain_mutex = threading.Lock()
limits, rate_mutex = defaultdict(deque), threading.Lock()
frames, camera_clients = {}, set()
bearer = HTTPBearer(auto_error=False)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def db_session():
    with DB() as db:
        yield db


def audit(db, uid, action, request, detail=''):
    db.add(Audit(user_id=uid, action=action, timestamp=now(), ip=request.client.host if request.client else 'unknown', detail=detail))


def limit(request, category, maximum=20, uid=''):
    key = (category, uid or (request.client.host if request.client else 'unknown'))
    with rate_mutex:
        queue = limits[key]
        stamp = time.monotonic()
        while queue and queue[0] < stamp-60:
            queue.popleft()
        if len(queue) >= maximum:
            raise HTTPException(429, 'Too many requests. Try again in a minute.')
        queue.append(stamp)


def origin_check(request):
    if request.headers.get('origin') and request.headers['origin'] not in ORIGINS:
        raise HTTPException(403, 'Origin denied')


def get_user(creds: HTTPAuthorizationCredentials = Depends(bearer), db: DBSession = Depends(db_session)):
    if not creds:
        raise HTTPException(401, 'Sign in required')
    try:
        payload = jwt.decode(creds.credentials, SECRET, algorithms=['HS256'], audience='emotherm', issuer='emotherm')
        if payload.get('type') != 'access':
            raise ValueError()
        session = db.get(Session, payload['sid'])
        user = db.get(User, payload['sub'])
        if not session or session.revoked or session.expires < time.time() or session.user_id != user.id or not user.active:
            raise ValueError()
        return user
    except (jwt.PyJWTError, ValueError, KeyError, AttributeError):
        raise HTTPException(401, 'Session expired')


def admin(user: User = Depends(get_user)):
    if user.role != 'admin':
        raise HTTPException(403, 'Admin access required')
    return user


def user_view(u):
    return {k:getattr(u,k) for k in ['id','email','name','role','active','camera_mode','theme','created_at']}


def issue(db, user, response, session=None):
    refresh = secrets.token_urlsafe(48)
    if session is None:
        session = Session(id=str(uuid.uuid4()), user_id=user.id, refresh_hash='', expires=0, revoked=False)
        db.add(session)
    session.refresh_hash = sha(refresh)
    session.expires = int(time.time()) + 7*86400
    token = jwt.encode({'sub':user.id,'sid':session.id,'type':'access','iat':int(time.time()),'exp':int(time.time())+900,'aud':'emotherm','iss':'emotherm'}, SECRET, algorithm='HS256')
    response.set_cookie('emotherm_refresh', refresh, httponly=True, secure=SECURE, samesite='strict', path='/api/auth', max_age=7*86400)
    return {'access_token':token,'token_type':'bearer','user':user_view(user)}


class Signup(BaseModel):
    name: str = Field(min_length=2,max_length=80)
    email: str = Field(min_length=5,max_length=254)
    password: str = Field(min_length=10,max_length=72)


class Login(BaseModel):
    email: str
    password: str


class Settings(BaseModel):
    name: str = Field(min_length=2,max_length=80)
    camera_mode: str
    theme: str


class Password(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10,max_length=72)


class Role(BaseModel):
    role: str
    active: bool


@asynccontextmanager
async def lifespan(app):
    yield
    camera.close()


app = FastAPI(title='EmoTherm SecureChain API', version='1.0.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_credentials=True, allow_methods=['GET','POST','PATCH'], allow_headers=['Authorization','Content-Type'])


@app.middleware('http')
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store'
    return response


@app.get('/api/health')
def health():
    return {'status':'ok','model_ready':predictor.path.exists(),'camera_driver':camera.driver}


@app.post('/api/auth/signup', status_code=201)
def signup(body:Signup, request:Request, response:Response, db:DBSession=Depends(db_session)):
    origin_check(request)
    limit(request,'signup',5)
    email=body.email.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
        raise HTTPException(422,'Enter a valid email address')
    if len(body.password.encode())>72:
        raise HTTPException(422,'Password must be at most 72 UTF-8 bytes')
    if db.scalar(select(User).where(User.email==email)):
        raise HTTPException(409,'Email already registered')
    u=User(id=str(uuid.uuid4()),email=email,name=body.name.strip(),password_hash=bcrypt.hashpw(body.password.encode(),bcrypt.gensalt()).decode(),role='user',active=True,camera_mode='uvc',theme='dark',created_at=now())
    db.add(u)
    db.flush()
    result=issue(db,u,response)
    audit(db,u.id,'signup',request)
    db.commit()
    return result


@app.post('/api/auth/login')
def login(body:Login,request:Request,response:Response,db:DBSession=Depends(db_session)):
    origin_check(request)
    limit(request,'login',10)
    u=db.scalar(select(User).where(User.email==body.email.strip().lower()))
    if not u or not u.active or len(body.password.encode())>72 or not bcrypt.checkpw(body.password.encode(),u.password_hash.encode()):
        audit(db,None,'login_failed',request)
        db.commit()
        raise HTTPException(401,'Invalid email or password')
    result=issue(db,u,response)
    audit(db,u.id,'login',request)
    db.commit()
    return result


@app.post('/api/auth/refresh')
def refresh(request:Request,response:Response,db:DBSession=Depends(db_session)):
    origin_check(request)
    limit(request,'refresh',60)
    token=request.cookies.get('emotherm_refresh','')
    session=db.scalar(select(Session).where(Session.refresh_hash==sha(token)).with_for_update())
    if not session or session.revoked or session.expires < time.time():
        raise HTTPException(401,'Session expired')
    u=db.get(User,session.user_id)
    if not u or not u.active:
        raise HTTPException(401,'Account unavailable')
    result=issue(db,u,response,session)
    db.commit()
    return result


@app.post('/api/auth/logout')
def logout(request:Request,response:Response,u:User=Depends(get_user),db:DBSession=Depends(db_session)):
    origin_check(request)
    token=request.headers['authorization'].split()[1]
    payload=jwt.decode(token,SECRET,algorithms=['HS256'],audience='emotherm',issuer='emotherm')
    db.get(Session,payload['sid']).revoked=True
    response.delete_cookie('emotherm_refresh',path='/api/auth')
    audit(db,u.id,'logout',request)
    db.commit()
    return {'ok':True}


@app.get('/api/me')
def me(u:User=Depends(get_user)):
    return user_view(u)


@app.patch('/api/me')
def settings(body:Settings,request:Request,u:User=Depends(get_user),db:DBSession=Depends(db_session)):
    if body.camera_mode not in ('uvc','bridge') or body.theme not in ('light','dark'):
        raise HTTPException(422,'Invalid preference')
    u.name,u.camera_mode,u.theme=body.name.strip(),body.camera_mode,body.theme
    audit(db,u.id,'settings_changed',request)
    db.commit()
    return user_view(u)


@app.post('/api/me/password')
def password(body:Password,request:Request,u:User=Depends(get_user),db:DBSession=Depends(db_session)):
    limit(request,'password',5,u.id)
    if len(body.current_password.encode())>72 or not bcrypt.checkpw(body.current_password.encode(),u.password_hash.encode()):
        raise HTTPException(400,'Current password is incorrect')
    if len(body.new_password.encode())>72:
        raise HTTPException(422,'Password must be at most 72 UTF-8 bytes')
    u.password_hash=bcrypt.hashpw(body.new_password.encode(),bcrypt.gensalt()).decode()
    for session in db.scalars(select(Session).where(Session.user_id==u.id)):
        session.revoked=True
    audit(db,u.id,'password_changed',request)
    db.commit()
    return {'ok':True,'message':'Password changed. Sign in again.'}


async def validated_file(file):
    if file.content_type not in ('image/jpeg','image/png','image/bmp','image/tiff'):
        raise HTTPException(415,'Use PNG, JPEG, BMP or TIFF images')
    raw=await file.read(10*1024*1024+1)
    if len(raw)>10*1024*1024:
        raise HTTPException(413,'Maximum image size is 10 MB')
    try:
        with Image.open(io.BytesIO(raw)) as img:
            if img.width*img.height>20_000_000 or img.width<16 or img.height<16:
                raise ValueError('Image dimensions are outside supported limits')
            fmt=img.format
            img.verify()
        if fmt not in ('JPEG','PNG','BMP','TIFF'):
            raise ValueError('Unsupported image encoding')
        expected={'JPEG':'image/jpeg','PNG':'image/png','BMP':'image/bmp','TIFF':'image/tiff'}[fmt]
        if file.content_type!=expected:
            raise ValueError('File MIME type does not match its image encoding')
        return raw,expected
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError):
        raise HTTPException(422,'Invalid image or unsupported dimensions')


@app.post('/api/preprocess')
async def preview(request:Request,file:UploadFile=File(...),u:User=Depends(get_user)):
    limit(request,'preview',30,u.id)
    raw,_=await validated_file(file)
    a=(preprocess(raw)*255).astype('uint8')
    buffer=io.BytesIO()
    Image.fromarray(a).save(buffer,format='PNG')
    return {'preview':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()}


def block_view(b):
    return {key:getattr(b,key) for key in ['index','timestamp','data_hash','previous_hash','nonce','hash']}


def metadata(upload):
    return {'id':upload.id,'user_id':upload.user_id,'timestamp':upload.timestamp,'source':upload.source}


def result_view(upload,prediction):
    result=json.loads(vault.decrypt_record(prediction.ciphertext,upload.wrapped_key,upload.id.encode()))
    return {**result,**metadata(upload),'block_index':prediction.block_index,'data_hash':record_hash(upload.ciphertext,prediction.ciphertext,metadata(upload))}


def certificate_for(identifier,u,db,verify_url):
    if u is None:
        upload=db.get(Upload,identifier)
        prediction=db.get(Prediction,identifier) if upload else None
        if not upload or not prediction:
            raise HTTPException(404,'Certificate record not found')
    else:
        upload,prediction=owned(identifier,u,db)
    block=db.get(Block,prediction.block_index)
    blocks=[block_view(b) for b in db.scalars(select(Block).order_by(Block.index))]
    raw_image=vault.decrypt_record(upload.ciphertext,upload.wrapped_key,identifier.encode())
    result=json.loads(vault.decrypt_record(prediction.ciphertext,upload.wrapped_key,identifier.encode()))
    commitment=record_hash(upload.ciphertext,prediction.ciphertext,metadata(upload))
    model_path=Path(os.getenv('MODEL_PATH',str(ROOT/'ml/artifacts/model_v2.npz')))
    payload={
        'schema':'emotherm-verification-certificate/v1',
        'certificate_id':f"ESC-{upload.timestamp[:4]}-{prediction.block_index:06d}-{identifier[:8].upper()}",
        'issued_at':now(),
        'verification_url':verify_url,
        'scan':{'id':identifier,'timestamp':upload.timestamp,'source':upload.source,'mime':upload.mime},
        'prediction':{key:result[key] for key in ['emotion','confidence','probabilities','model']},
        'integrity':{
            'image_sha256':sha256(raw_image),
            'record_sha256':commitment,
            'model_sha256':sha256(model_path.read_bytes()) if model_path.exists() else '',
            'block_index':prediction.block_index,
            'block_hash':block.hash if block else '',
            'previous_block_hash':block.previous_hash if block else '',
            'record_valid':bool(block and block.data_hash==commitment),
            'chain_valid':is_chain_valid(blocks),
            'verified_at':now()
        },
        'cryptography':{
            'image_and_prediction_encryption':'AES-256-GCM',
            'key_wrapping':'RSA-3072-OAEP-SHA256',
            'certificate_signature':'RSA-PSS-SHA256',
            'record_hash':'SHA-256'
        },
        'notice':'Research estimate of a trained facial-expression class; not a determination of internal emotional state.'
    }
    return signed_certificate(payload,vault)


def certificate_status(document,db):
    signature_valid,hash_valid,message=verify_signed_certificate(document,vault)
    scan=document.get('scan') if isinstance(document,dict) else None
    identifier=scan.get('id') if isinstance(scan,dict) else None
    upload=db.get(Upload,identifier) if isinstance(identifier,str) else None
    prediction=db.get(Prediction,identifier) if upload else None
    block=db.get(Block,prediction.block_index) if prediction else None
    blocks=[block_view(b) for b in db.scalars(select(Block).order_by(Block.index))]
    record_valid=model_valid=prediction_matches=False
    if upload and prediction and block:
        commitment=record_hash(upload.ciphertext,prediction.ciphertext,metadata(upload))
        integrity=document.get('integrity',{})
        stored=json.loads(vault.decrypt_record(prediction.ciphertext,upload.wrapped_key,identifier.encode()))
        submitted=document.get('prediction',{})
        prediction_matches=all(submitted.get(k)==stored.get(k) for k in ['emotion','confidence','probabilities','model'])
        record_valid=(integrity.get('record_sha256')==commitment==block.data_hash
                      and integrity.get('block_index')==block.index
                      and integrity.get('block_hash')==block.hash
                      and integrity.get('previous_block_hash')==block.previous_hash)
        model_path=Path(os.getenv('MODEL_PATH',str(ROOT/'ml/artifacts/model_v2.npz')))
        model_valid=(submitted.get('model')==stored.get('model')
                     and model_path.exists() and integrity.get('model_sha256')==sha256(model_path.read_bytes()))
    chain_valid=is_chain_valid(blocks)
    blockchain_valid=bool(record_valid and chain_valid and prediction_matches)
    overall=bool(signature_valid and hash_valid and blockchain_valid and model_valid)
    return {
        'certificate_id':document.get('certificate_id') if isinstance(document,dict) else None,
        'scan_id':identifier,
        'digital_signature_valid':signature_valid,
        'report_content_unchanged':hash_valid,
        'blockchain_record_verified':blockchain_valid,
        'model_version_confirmed':model_valid,
        'overall_valid':overall,
        'message':'Certificate is authentic and all stored commitments match.' if overall else (message or 'One or more certificate checks failed.')
    }


def pipeline(raw,mime,source,u,request,db):
    try:
        result=predictor.predict(raw)
    except FileNotFoundError as exc:
        raise HTTPException(503,str(exc))
    identifier=str(uuid.uuid4())
    timestamp=now()
    encrypted,encrypted_result,wrapped=vault.encrypt_record(raw,canonical(result),identifier.encode())
    upload=Upload(id=identifier,user_id=u.id,source=source,timestamp=timestamp,wrapped_key=wrapped,ciphertext=encrypted,mime=mime)
    # Serializing block append keeps the image, prediction and chain write atomic.
    # PostgreSQL also takes a durable row lock; run one backend worker for the camera.
    with chain_mutex:
        db.scalar(select(ChainLock).where(ChainLock.id==1).with_for_update())
        existing=[block_view(b) for b in db.scalars(select(Block).order_by(Block.index))]
        if not is_chain_valid(existing):
            raise HTTPException(409,'Chain integrity failed. New records are paused.')
        commitment=record_hash(encrypted,encrypted_result,metadata(upload))
        b=mine(len(existing),timestamp,commitment,existing[-1]['hash'] if existing else '0'*64)
        prediction=Prediction(id=identifier,ciphertext=encrypted_result,block_index=b['index'])
        db.add(upload)
        db.flush()
        db.add(prediction)
        db.add(Block(**b))
        audit(db,u.id,'upload' if source=='upload' else 'capture',request,identifier)
        db.commit()
    return result_view(upload,prediction)


@app.post('/api/predictions',status_code=201)
async def predict(request:Request,file:UploadFile=File(...),source:str=Form('upload'),u:User=Depends(get_user),db:DBSession=Depends(db_session)):
    limit(request,'prediction',15,u.id)
    if source not in ('upload','uvc'):
        raise HTTPException(422,'Use the bridge capture endpoint for bridge frames')
    raw,mime=await validated_file(file)
    return await asyncio.to_thread(pipeline,raw,mime,source,u,request,db)


@app.get('/api/predictions')
def history(emotion:str='',source:str='',start:str='',end:str='',u:User=Depends(get_user),db:DBSession=Depends(db_session)):
    query=select(Upload).where(Upload.user_id==u.id).order_by(Upload.timestamp.desc())
    if source:
        query=query.where(Upload.source==source)
    if start:
        query=query.where(Upload.timestamp>=start)
    if end:
        query=query.where(Upload.timestamp<=end+'T23:59:59.999999+00:00')
    results=[result_view(upload,db.get(Prediction,upload.id)) for upload in db.scalars(query)]
    return [r for r in results if not emotion or r['emotion']==emotion]


def owned(identifier,u,db):
    upload=db.get(Upload,identifier)
    if not upload or (upload.user_id!=u.id and u.role!='admin'):
        raise HTTPException(404,'Record not found')
    return upload,db.get(Prediction,identifier)


@app.get('/api/predictions/{identifier}')
def result(identifier:str,u:User=Depends(get_user),db:DBSession=Depends(db_session)):
    upload,prediction=owned(identifier,u,db)
    return result_view(upload,prediction)


@app.get('/api/predictions/{identifier}/image')
def image(identifier:str,u:User=Depends(get_user),db:DBSession=Depends(db_session)):
    upload,_=owned(identifier,u,db)
    return Response(vault.decrypt_record(upload.ciphertext,upload.wrapped_key,identifier.encode()),media_type=upload.mime)


@app.post('/api/predictions/{identifier}/verify')
def verify(identifier:str,request:Request,u:User=Depends(get_user),db:DBSession=Depends(db_session)):
    upload,prediction=owned(identifier,u,db)
    blocks=[block_view(b) for b in db.scalars(select(Block).order_by(Block.index))]
    b=db.get(Block,prediction.block_index)
    commitment=record_hash(upload.ciphertext,prediction.ciphertext,metadata(upload))
    ciphertext_valid=True
    try:
        vault.decrypt_record(upload.ciphertext,upload.wrapped_key,identifier.encode())
        vault.decrypt_record(prediction.ciphertext,upload.wrapped_key,identifier.encode())
    except Exception:
        ciphertext_valid=False
    result={'chain_valid':is_chain_valid(blocks),'record_valid':bool(b and commitment==b.data_hash and ciphertext_valid),'block_hash':b.hash if b else None}
    audit(db,u.id,'verification',request,json.dumps(result))
    db.commit()
    return result


@app.get('/api/predictions/{identifier}/certificate.json')
def export_certificate_json(identifier:str,request:Request,u:User=Depends(get_user),db:DBSession=Depends(db_session)):
    verify_url=str(request.base_url).rstrip('/')+'/verify-certificate?scan='+identifier
    document=certificate_for(identifier,u,db,verify_url)
    audit(db,u.id,'certificate_export',request,identifier+':json')
    db.commit()
    filename=document['certificate_id']+'.json'
    return Response(json.dumps(document,indent=2).encode(),media_type='application/json',
                    headers={'Content-Disposition':f'attachment; filename="{filename}"'})


@app.get('/api/predictions/{identifier}/certificate.pdf')
def export_certificate_pdf(identifier:str,request:Request,u:User=Depends(get_user),db:DBSession=Depends(db_session)):
    verify_url=str(request.base_url).rstrip('/')+'/verify-certificate?scan='+identifier
    document=certificate_for(identifier,u,db,verify_url)
    rendered=certificate_pdf(document,verify_url)
    audit(db,u.id,'certificate_export',request,identifier+':pdf')
    db.commit()
    filename=document['certificate_id']+'.pdf'
    return Response(rendered,media_type='application/pdf',
                    headers={'Content-Disposition':f'attachment; filename="{filename}"'})


@app.post('/api/certificates/verify')
async def verify_certificate_upload(request:Request,file:UploadFile=File(...),db:DBSession=Depends(db_session)):
    origin_check(request)
    limit(request,'certificate_verify',20)
    raw=await file.read(1024*1024+1)
    if len(raw)>1024*1024:
        raise HTTPException(413,'Certificate JSON must be at most 1 MB')
    try:
        document=json.loads(raw)
    except (UnicodeDecodeError,json.JSONDecodeError):
        raise HTTPException(422,'Upload a valid EmoTherm certificate JSON file')
    return certificate_status(document,db)


@app.get('/api/certificates/scan/{identifier}')
def verify_certificate_qr(identifier:str,request:Request,db:DBSession=Depends(db_session)):
    limit(request,'certificate_qr',30)
    verify_url=str(request.base_url).rstrip('/')+'/verify-certificate?scan='+identifier
    return certificate_status(certificate_for(identifier,None,db,verify_url),db)


@app.get('/api/certificates/public-key')
def certificate_public_key():
    return Response(vault.public_key_pem(),media_type='application/x-pem-file',
                    headers={'Content-Disposition':'attachment; filename="emotherm-certificate-public-key.pem"'})


@app.get('/api/chain')
def chain(q:str='',u:User=Depends(get_user),db:DBSession=Depends(db_session)):
    blocks=[block_view(b) for b in db.scalars(select(Block).order_by(Block.index))]
    return {'valid':is_chain_valid(blocks),'total':len(blocks),'blocks':[b for b in blocks if not q or q.lower() in b['hash'] or q.lower() in b['data_hash']]}


@app.post('/api/chain/tamper-demo')
def tamper(request:Request,u:User=Depends(admin),db:DBSession=Depends(db_session)):
    blocks=[block_view(b) for b in db.scalars(select(Block).order_by(Block.index))]
    if not blocks:
        raise HTTPException(400,'Create a prediction first')
    before=is_chain_valid(blocks)
    blocks[-1]['data_hash']='f'*64
    after=is_chain_valid(blocks)
    audit(db,u.id,'tamper_demo',request,'In-memory copy only')
    db.commit()
    return {'before':before,'after':after,'persisted':False,'changed_block':blocks[-1]['index']}


@app.post('/api/camera/ticket')
def camera_ticket(request:Request,u:User=Depends(get_user),db:DBSession=Depends(db_session)):
    limit(request,'camera_ticket',10,u.id)
    ticket=secrets.token_urlsafe(32)
    payload=jwt.decode(request.headers['authorization'].split()[1],SECRET,algorithms=['HS256'],audience='emotherm',issuer='emotherm')
    db.add(CameraTicket(hash=sha(ticket),user_id=u.id,session_id=payload['sid'],expires=int(time.time())+60))
    db.commit()
    return {'ticket':ticket}


@app.websocket('/api/camera/stream')
async def camera_stream(websocket:WebSocket):
    if websocket.headers.get('origin') not in ORIGINS:
        await websocket.close(code=1008)
        return
    with DB() as db:
        ticket=db.get(CameraTicket,sha(websocket.query_params.get('ticket','')))
        if not ticket or ticket.expires<time.time():
            await websocket.close(code=1008)
            return
        uid,sid=ticket.user_id,ticket.session_id
        session=db.get(Session,sid)
        user=db.get(User,uid)
        db.delete(ticket)
        db.commit()
        if not session or session.revoked or not user.active or uid in camera_clients:
            await websocket.close(code=1008)
            return
    camera_clients.add(uid)
    await websocket.accept()
    try:
        while True:
            with DB() as db:
                session=db.get(Session,sid)
                user=db.get(User,uid)
                if not session or session.revoked or session.expires<time.time() or not user.active:
                    await websocket.close(code=1008)
                    break
            raw,preview=await asyncio.to_thread(camera.frame)
            frames[uid]=(time.monotonic(),raw)
            await websocket.send_json({'preview':base64.b64encode(preview).decode()})
            await asyncio.sleep(1/max(1,min(30,int(os.getenv('CAMERA_FPS','8')))))
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.send_json({'error':'Camera unavailable. Check the configured driver, device and serial protocol.'})
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        camera_clients.discard(uid)
        frames.pop(uid,None)
        if not camera_clients:
            await asyncio.to_thread(camera.close)


@app.post('/api/camera/capture',status_code=201)
def capture(request:Request,u:User=Depends(get_user),db:DBSession=Depends(db_session)):
    limit(request,'prediction',15,u.id)
    current=frames.get(u.id)
    if not current or time.monotonic()-current[0]>5:
        raise HTTPException(409,'Start the camera bridge and wait for a live frame')
    return pipeline(current[1],'image/png','bridge',u,request,db)


@app.get('/api/admin/overview')
def overview(u:User=Depends(admin),db:DBSession=Depends(db_session)):
    records=[result_view(upload,db.get(Prediction,upload.id)) for upload in db.scalars(select(Upload))]
    return {'users':db.scalar(select(func.count()).select_from(User)),'scans':len(records),
            'distribution':dict(Counter(r['emotion'] for r in records)), 'daily':dict(sorted(Counter(r['timestamp'][:10] for r in records).items()))}


@app.get('/api/admin/users')
def users(u:User=Depends(admin),db:DBSession=Depends(db_session)):
    return [user_view(user) for user in db.scalars(select(User).order_by(User.created_at.desc()))]


@app.patch('/api/admin/users/{identifier}')
def change_role(identifier:str,body:Role,request:Request,u:User=Depends(admin),db:DBSession=Depends(db_session)):
    if body.role not in ('admin','researcher','user'):
        raise HTTPException(422,'Invalid role')
    target=db.get(User,identifier)
    if not target:
        raise HTTPException(404,'User not found')
    if identifier==u.id and (body.role!='admin' or not body.active):
        raise HTTPException(400,'You cannot remove your own admin access')
    target.role,target.active=body.role,body.active
    if not body.active:
        for session in db.scalars(select(Session).where(Session.user_id==identifier)):
            session.revoked=True
    audit(db,u.id,'user_updated',request,identifier+':'+body.role)
    db.commit()
    return user_view(target)


@app.get('/api/admin/metrics')
def metrics(u:User=Depends(admin)):
    path=Path(os.getenv('METRICS_PATH',str(ROOT/'ml/artifacts/metrics_v2.json')))
    if not path.exists():
        return {'ready':False}
    data=json.loads(path.read_text())
    history=path.parent/'training_history.json'
    return {'ready':True,**data,'training_history':data.get('training_history', json.loads(history.read_text()) if history.exists() else [])}


@app.get('/api/admin/audit')
def audits(action:str='',q:str='',start:str='',end:str='',u:User=Depends(admin),db:DBSession=Depends(db_session)):
    query=select(Audit).order_by(Audit.id.desc()).limit(1000)
    if action:
        query=query.where(Audit.action==action)
    if q:
        query=query.where(Audit.detail.contains(q) | Audit.user_id.contains(q))
    if start:
        query=query.where(Audit.timestamp>=start)
    if end:
        query=query.where(Audit.timestamp<=end+'T23:59:59.999999+00:00')
    return [{k:getattr(a,k) for k in ['id','user_id','action','timestamp','ip','detail']} for a in db.scalars(query)]
