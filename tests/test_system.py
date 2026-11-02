import base64
import io
import os
import secrets
import struct
import tempfile
import time
import json
from pathlib import Path
import pytest
import cv2
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
TEST_DATA=Path(tempfile.mkdtemp(prefix='emotherm-test-'))
os.environ['DATA_DIR']=str(TEST_DATA)
os.environ['DATABASE_URL']='sqlite:///'+(TEST_DATA/'test.db').as_posix()
os.environ['JWT_SECRET']=secrets.token_urlsafe(48)
os.environ['AES_MASTER_KEY']=base64.b64encode(secrets.token_bytes(32)).decode()
os.environ['MODEL_PATH']=str(ROOT/'ml/artifacts/model.pt')
os.environ['METRICS_PATH']=str(ROOT/'ml/artifacts/metrics.json')
from backend import main
from backend.models import User,Upload,Prediction,Block
from blockchain.chain import mine,is_chain_valid,canonical
from camera.bridge import Camera
from ml.data import discover


@pytest.fixture
def client():
    main.limits.clear()
    with TestClient(main.app) as c:
        yield c


def account(client,role='user'):
    email=secrets.token_hex(8)+'@example.com'
    password='Demo-'+secrets.token_hex(12)
    result=client.post('/api/auth/signup',json={'name':'Test Researcher','email':email,'password':password})
    assert result.status_code==201,result.text
    body=result.json()
    if role=='admin':
        with main.DB.begin() as db:
            db.get(User,body['user']['id']).role='admin'
    return {'Authorization':'Bearer '+body['access_token']},body,email,password


def image_bytes():
    array=np.tile(np.arange(96,dtype=np.uint8),(96,1))*2
    stream=io.BytesIO()
    Image.fromarray(array).save(stream,format='PNG')
    return stream.getvalue()


def prediction(client,headers,source='upload'):
    result=client.post('/api/predictions',headers=headers,data={'source':source},files={'file':('thermal.png',image_bytes(),'image/png')})
    assert result.status_code==201,result.text
    return result.json()


def test_auth_and_role_boundary(client):
    headers,body,email,password=account(client)
    assert body['user']['role']=='user'
    assert client.get('/api/me',headers=headers).status_code==200
    assert client.get('/api/admin/users',headers=headers).status_code==403
    assert client.get('/api/predictions').status_code==401
    assert client.post('/api/auth/login',json={'email':email,'password':'wrong'}).status_code==401
    assert client.post('/api/auth/login',json={'email':email,'password':password}).status_code==200


def test_refresh_rotation_and_logout_revocation(client):
    headers,_,_,_=account(client)
    old_cookie=client.cookies.get('emotherm_refresh')
    refreshed=client.post('/api/auth/refresh')
    assert refreshed.status_code==200
    assert client.cookies.get('emotherm_refresh')!=old_cookie
    with TestClient(main.app) as other:
        other.cookies.set('emotherm_refresh',old_cookie)
        assert other.post('/api/auth/refresh').status_code==401
    new={'Authorization':'Bearer '+refreshed.json()['access_token']}
    assert client.post('/api/auth/logout',headers=new).status_code==200
    assert client.get('/api/me',headers=headers).status_code==401
    assert client.get('/api/me',headers=new).status_code==401


def test_preprocess_inference_encryption_and_verification(client):
    headers,body,_,_=account(client)
    preview=client.post('/api/preprocess',headers=headers,files={'file':('test.png',image_bytes(),'image/png')})
    assert preview.status_code==200
    assert preview.json()['preview'].startswith('data:image/png;base64,')
    record=prediction(client,headers)
    assert record['emotion'] in ['disgust','happy','neutral','sad','surprise']
    assert abs(sum(record['probabilities'].values())-1)<1e-5
    with main.DB() as db:
        upload=db.get(Upload,record['id'])
        p=db.get(Prediction,record['id'])
        assert upload.ciphertext!=image_bytes()
        assert not upload.ciphertext.startswith(b'\x89PNG')
        assert canonical({k:record[k] for k in ['emotion','confidence','probabilities','model']})!=p.ciphertext
    verify=client.post('/api/predictions/'+record['id']+'/verify',headers=headers).json()
    assert verify['record_valid'] and verify['chain_valid']
    image=client.get('/api/predictions/'+record['id']+'/image',headers=headers)
    assert image.content==image_bytes()
    assert client.get('/api/predictions?emotion='+record['emotion'],headers=headers).json()[0]['id']==record['id']


def test_signed_certificate_export_qr_and_tamper_rejection(client):
    headers,_,_,_=account(client)
    record=prediction(client,headers)
    exported=client.get('/api/predictions/'+record['id']+'/certificate.json',headers=headers)
    assert exported.status_code==200
    assert 'attachment' in exported.headers['content-disposition']
    certificate=exported.json()
    assert certificate['signature']['algorithm']=='RSA-PSS-SHA256'
    verified=client.post('/api/certificates/verify',files={
        'file':('certificate.json',json.dumps(certificate).encode(),'application/json')}).json()
    assert verified['overall_valid']
    assert all(verified[key] for key in [
        'digital_signature_valid','report_content_unchanged',
        'blockchain_record_verified','model_version_confirmed'])
    qr=client.get('/api/certificates/scan/'+record['id']).json()
    assert qr['overall_valid']
    pdf=client.get('/api/predictions/'+record['id']+'/certificate.pdf',headers=headers)
    assert pdf.status_code==200 and pdf.content.startswith(b'%PDF') and len(pdf.content)>5000
    certificate['prediction']['emotion']='tampered'
    rejected=client.post('/api/certificates/verify',files={
        'file':('certificate.json',json.dumps(certificate).encode(),'application/json')}).json()
    assert not rejected['overall_valid']
    assert not rejected['digital_signature_valid']
    assert not rejected['report_content_unchanged']
    assert not rejected['blockchain_record_verified']
    public_key=client.get('/api/certificates/public-key')
    assert public_key.content.startswith(b'-----BEGIN PUBLIC KEY-----')


def test_other_user_cannot_read_or_verify(client):
    first,_,_,_=account(client)
    record=prediction(client,first)
    second,_,_,_=account(client)
    for suffix in ['', '/image']:
        assert client.get('/api/predictions/'+record['id']+suffix,headers=second).status_code==404
    assert client.post('/api/predictions/'+record['id']+'/verify',headers=second).status_code==404
    assert client.get('/api/predictions/'+record['id']+'/certificate.json',headers=second).status_code==404
    assert client.get('/api/predictions/'+record['id']+'/certificate.pdf',headers=second).status_code==404
    assert client.get('/api/predictions',headers=second).json()==[]


def test_ciphertext_and_block_tamper_detected(client):
    headers,_,_,_=account(client)
    record=prediction(client,headers)
    with main.DB.begin() as db:
        upload=db.get(Upload,record['id'])
        original=upload.ciphertext
        upload.ciphertext=bytes([original[0]^1])+original[1:]
    verify=client.post('/api/predictions/'+record['id']+'/verify',headers=headers).json()
    assert not verify['record_valid']
    with main.DB.begin() as db:
        db.get(Upload,record['id']).ciphertext=original
        b=db.get(Block,record['block_index'])
        old_hash=b.hash
        b.hash='a'*64
    try:
        verify=client.post('/api/predictions/'+record['id']+'/verify',headers=headers).json()
        assert not verify['chain_valid']
        result=client.post('/api/predictions',headers=headers,files={'file':('test.png',image_bytes(),'image/png')})
        assert result.status_code==409
    finally:
        with main.DB.begin() as db:
            db.get(Block,record['block_index']).hash=old_hash


def test_input_validation(client):
    headers,_,_,_=account(client)
    assert client.post('/api/predictions',headers=headers,files={'file':('bad.png',b'not an image','image/png')}).status_code==422
    assert client.post('/api/predictions',headers=headers,files={'file':('x.png',image_bytes(),'application/octet-stream')}).status_code==415
    assert client.post('/api/predictions',headers=headers,files={'file':('x.png',image_bytes(),'image/jpeg')}).status_code==422
    assert client.post('/api/predictions',headers=headers,data={'source':'bridge'},files={'file':('x.png',image_bytes(),'image/png')}).status_code==422
    assert client.post('/api/camera/capture',headers=headers).status_code==409


def test_origin_rate_limit_and_settings(client):
    headers,body,_,_=account(client)
    result=client.patch('/api/me',headers=headers,json={'name':'Updated Name','camera_mode':'bridge','theme':'light'})
    assert result.status_code==200
    assert client.get('/api/me',headers=headers).json()['camera_mode']=='bridge'
    assert client.post('/api/auth/refresh',headers={'Origin':'https://untrusted.example'}).status_code==403
    for _ in range(10):
        assert client.post('/api/auth/login',json={'email':'none@example.com','password':'bad'}).status_code==401
    assert client.post('/api/auth/login',json={'email':'none@example.com','password':'bad'}).status_code==429


def test_admin_management_metrics_and_safe_tamper_demo(client):
    normal,body,_,_=account(client)
    record=prediction(client,normal)
    admin,_,_,_=account(client,'admin')
    overview=client.get('/api/admin/overview',headers=admin)
    assert overview.status_code==200 and overview.json()['scans']>0
    metrics=client.get('/api/admin/metrics',headers=admin).json()
    assert metrics['ready'] and len(metrics['confusion_matrix'])==5
    demo=client.post('/api/chain/tamper-demo',headers=admin).json()
    assert demo['before'] and not demo['after'] and not demo['persisted']
    assert client.get('/api/chain',headers=normal).json()['valid']
    update=client.patch('/api/admin/users/'+body['user']['id'],headers=admin,json={'role':'researcher','active':True})
    assert update.status_code==200
    assert client.get('/api/me',headers=normal).json()['role']=='researcher'
    assert client.patch('/api/admin/users/'+body['user']['id'],headers=admin,json={'role':'researcher','active':False}).status_code==200
    assert client.get('/api/me',headers=normal).status_code==401
    events=client.get('/api/admin/audit?action=user_updated',headers=admin).json()
    assert any(e['user_id'] for e in events)


def test_password_change_revokes_sessions(client):
    headers,_,email,password=account(client)
    assert client.post('/api/me/password',headers=headers,json={'current_password':password,'new_password':'New-Secure-Password-123'}).status_code==200
    assert client.get('/api/me',headers=headers).status_code==401
    assert client.post('/api/auth/login',json={'email':email,'password':password}).status_code==401
    assert client.post('/api/auth/login',json={'email':email,'password':'New-Secure-Password-123'}).status_code==200


def test_real_opencv_bridge_websocket_and_capture(client,tmp_path,monkeypatch):
    video=tmp_path/'camera.avi'
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),8,(96,96))
    assert writer.isOpened()
    for i in range(20):
        frame=np.repeat((np.indices((96,96))[1]+i).astype(np.uint8)[:,:,None],3,axis=2)
        writer.write(frame)
    writer.release()
    monkeypatch.setenv('CAMERA_DRIVER','opencv')
    monkeypatch.setenv('CAMERA_SOURCE',str(video))
    monkeypatch.setattr(main,'camera',Camera())
    headers,_,_,_=account(client)
    ticket=client.post('/api/camera/ticket',headers=headers).json()['ticket']
    with client.websocket_connect('/api/camera/stream?ticket='+ticket,headers={'Origin':'http://localhost:5173'}) as ws:
        received=ws.receive_json()
        assert 'preview' in received
        assert base64.b64decode(received['preview']).startswith(b'\xff\xd8')
        result=client.post('/api/camera/capture',headers=headers)
        assert result.status_code==201,result.text
        assert result.json()['source']=='bridge'
        assert client.post('/api/predictions/'+result.json()['id']+'/verify',headers=headers).json()['record_valid']


def test_serial_parser_real_frame_decoding(monkeypatch):
    monkeypatch.setenv('CAMERA_DRIVER','serial')
    monkeypatch.setenv('CAMERA_WIDTH','16')
    monkeypatch.setenv('CAMERA_HEIGHT','16')
    sensor=np.arange(256,dtype='<u2').reshape(16,16)
    packet=b'noiseETH1'+struct.pack('<I',sensor.nbytes)+sensor.tobytes()
    driver=Camera()
    driver.device=io.BytesIO(packet)
    raw,preview=driver.frame()
    assert Image.open(io.BytesIO(raw)).size==(16,16)
    assert Image.open(io.BytesIO(preview)).mode=='RGB'
    driver.device=io.BytesIO(b'ETH1'+struct.pack('<I',9000000))
    with pytest.raises(RuntimeError,match='dimensions'):
        driver.frame()


def test_browser_capture_input_uses_same_pipeline(client):
    headers,_,_,_=account(client)
    record=prediction(client,headers,'uvc')
    assert record['source']=='uvc'
    assert client.post('/api/predictions/'+record['id']+'/verify',headers=headers).json()['record_valid']


def test_chain_detects_every_mutation():
    block=mine(0,'timestamp','b'*64,'0'*64)
    assert is_chain_valid([block])
    for field in ['index','timestamp','data_hash','previous_hash','nonce','hash']:
        altered=dict(block)
        altered[field]=altered[field]+1 if isinstance(altered[field],int) else 'changed'
        assert not is_chain_valid([altered])


def test_folder_ingestion_excludes_visible(tmp_path):
    for folder in ['1. SAD F/TI','1. SAD F/VI','2. HAPPY F/TI/TI','2. HAPPY F/VI']:
        path=tmp_path/folder
        path.mkdir(parents=True)
        (path/'img.png').write_bytes(image_bytes())
    rows=discover(tmp_path)
    assert len(rows)==2
    assert {label for _,label in rows}=={'sad','happy'}
    assert all('VI' not in str(path) for path,_ in rows)
