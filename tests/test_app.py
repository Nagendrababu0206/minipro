import json
import io
from app import create_app
from storage import JsonStore
from detector import ParkingDetector
from occupancy import summarize

def client(tmp_path, **extra):
    config={'TESTING':True,'SECRET_KEY':'test-secret','DATA_DIR':tmp_path/'data','UPLOAD_DIR':tmp_path/'uploads','RESULT_DIR':tmp_path/'results','WEIGHTS':str(tmp_path/'missing.pt')}
    config.update(extra)
    return create_app(config).test_client()

def token(c, path='/register'):
    page=c.get(path)
    assert page.status_code==200
    import re
    return re.search(rb'name="_csrf" value="([^"]+)"',page.data).group(1).decode()

def test_registration_hash_and_login(tmp_path):
    c=client(tmp_path); csrf=token(c)
    r=c.post('/register',data={'_csrf':csrf,'username':'driver1','email':'d@example.com','password':'a-long-password'},follow_redirects=True)
    assert r.status_code==200 and b'Account created' in r.data
    users=json.loads((tmp_path/'data'/'users.json').read_text())
    assert users[0]['password_hash']!='a-long-password'
    csrf=token(c,'/login'); r=c.post('/login',data={'_csrf':csrf,'identity':'driver1','password':'a-long-password'},follow_redirects=True)
    assert b'Your parking intelligence workspace' in r.data or b'Good to see you' in r.data

def test_protected_and_csrf(tmp_path):
    c=client(tmp_path)
    assert c.get('/dashboard').status_code==302
    assert c.post('/login',data={'identity':'nobody','password':'x'}).status_code==400

def test_empty_dashboard_and_user_scoped_history(tmp_path):
    c=client(tmp_path); csrf=token(c)
    c.post('/register',data={'_csrf':csrf,'username':'driver','email':'d@example.com','password':'long-password'})
    csrf=token(c,'/login'); c.post('/login',data={'_csrf':csrf,'identity':'driver','password':'long-password'})
    dashboard=c.get('/dashboard')
    assert dashboard.status_code==200 and b'Google Maps is not configured' in dashboard.data
    assert c.get('/history').status_code==200
    assert c.get('/analysis/not-real').status_code==404

def test_configured_maps_key_and_settings_help(tmp_path):
    c=client(tmp_path,GOOGLE_MAPS_BROWSER_KEY='demo-browser-key')
    csrf=token(c);c.post('/register',data={'_csrf':csrf,'username':'mapdriver','email':'maps@example.com','password':'long-password'})
    csrf=token(c,'/login');c.post('/login',data={'_csrf':csrf,'identity':'mapdriver','password':'long-password'})
    page=c.get('/dashboard')
    assert b'demo-browser-key' in page.data and b'parking_map.js' in page.data
    assert b'Set my location for drive times' in page.data and b'Find alternatives' in page.data and b'Expand search radius' in page.data and b'Verified availability' in page.data
    assert b'Google Maps' in c.get('/settings').data

def test_analysis_detail_exposes_controls_for_actual_slot_boxes(tmp_path):
    c=client(tmp_path);csrf=token(c)
    c.post('/register',data={'_csrf':csrf,'username':'slotdriver','email':'slot@example.com','password':'long-password'})
    csrf=token(c,'/login');c.post('/login',data={'_csrf':csrf,'identity':'slotdriver','password':'long-password'})
    with c.session_transaction() as sess:user_id=sess['user_id']
    c.application.extensions['pv_store'].add_analysis({'id':'analysis1','user_id':user_id,'timestamp':'2026-10-11T12:00:00+00:00','processing_time':.5,'original_image':'original.jpg','annotated_image':'result.jpg','total_spaces':1,'vacant_spaces':1,'occupied_spaces':0,'uncertain_spaces':0,'vacancy_percentage':100,'occupancy_percentage':0,'average_confidence':.91,'detected_slots':[{'slot_id':'P01','bbox':[4,5,80,90],'classification':'VACANT','confidence':.91,'recommended':True}]})
    page=c.get('/analysis/analysis1')
    assert page.status_code==200 and b'toggle-boxes' in page.data and b'P01 - VACANT' in page.data and b'slot_guidance.js' in page.data

def test_storage_recovers_bad_json_and_filters_invalid_rows(tmp_path):
    store=JsonStore(tmp_path)
    (tmp_path/'analyses.json').write_text('{broken')
    assert store.analyses('u')==[]
    (tmp_path/'users.json').write_text('[null, {"username":"valid"}]')
    assert store.user_by_name('valid')=={'username':'valid'}

def test_duplicate_box_iou():
    assert ParkingDetector._iou([0,0,100,100],[5,5,95,95])>.75
    assert ParkingDetector._iou([0,0,10,10],[50,50,70,70])==0

def test_occupancy_math_excludes_uncertain_and_handles_zero():
    slots=[{'slot_id':'S001','classification':'VACANT','confidence':.9},{'slot_id':'S002','classification':'OCCUPIED','confidence':.8},{'slot_id':'S003','classification':'UNCERTAIN','confidence':.5}]
    result=summarize(slots)
    assert (result['total_spaces'],result['vacant_spaces'],result['occupied_spaces'],result['uncertain_spaces'])==(3,1,1,1)
    assert result['vacancy_percentage']==50 and result['occupancy_percentage']==50
    empty=summarize([])
    assert empty['total_spaces']==0 and empty['vacancy_percentage'] is None and empty['occupancy_percentage'] is None

def test_invalid_image_is_rejected_before_inference(tmp_path):
    c=client(tmp_path); csrf=token(c)
    c.post('/register',data={'_csrf':csrf,'username':'driver','email':'d@example.com','password':'long-password'})
    csrf=token(c,'/login'); c.post('/login',data={'_csrf':csrf,'identity':'driver','password':'long-password'})
    csrf=token(c,'/analyze')
    r=c.post('/analyze',data={'_csrf':csrf,'image':(io.BytesIO(b'not an image'),'lot.jpg')},content_type='multipart/form-data',follow_redirects=True)
    assert r.status_code==200 and b'not a readable JPG or PNG image' in r.data

def test_moving_average_uses_five_real_observations(tmp_path):
    c=client(tmp_path); csrf=token(c)
    c.post('/register',data={'_csrf':csrf,'username':'driver','email':'d@example.com','password':'long-password'})
    csrf=token(c,'/login'); c.post('/login',data={'_csrf':csrf,'identity':'driver','password':'long-password'})
    store=c.application.extensions['pv_store']
    # Use the authenticated session's account ID for test observations.
    with c.session_transaction() as sess: user_id=sess['user_id']
    for i,value in enumerate([10,20,30,40,50]):
        store.add_analysis({'id':f'ok{i}','user_id':user_id,'occupancy_percentage':value,'timestamp':f'2026-01-0{i+1}T00:00:00+00:00'})
    page=c.get('/analytics?future=2100-01-01T12%3A00')
    assert page.status_code==200 and b'Moving-average estimate' in page.data and b'30.0%' in page.data
