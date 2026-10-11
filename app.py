"""ParkVision: local Flask parking occupancy demonstrator."""
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime, timezone
import os, uuid, time, secrets, hmac
from storage import JsonStore
from detector import ParkingDetector, ModelUnavailable
from alternatives import occupancy_status, facility_availability, rank_facilities

ROOT = Path(__file__).resolve().parent

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get('PARKVISION_SECRET', secrets.token_hex(32)), MAX_CONTENT_LENGTH=8*1024*1024,
        DATA_DIR=ROOT/'data', UPLOAD_DIR=ROOT/'uploads', RESULT_DIR=ROOT/'results', WEIGHTS=os.environ.get('PARKVISION_WEIGHTS', str(ROOT/'models'/'best.pt')),
        CONFIDENCE=float(os.environ.get('PARKVISION_CONFIDENCE', '.35')), GOOGLE_MAPS_BROWSER_KEY=os.environ.get('GOOGLE_MAPS_BROWSER_KEY',''), ADMIN_USERNAME=os.environ.get('PARKVISION_ADMIN_USERNAME',''), OCCUPANCY_MAX_AGE_SECONDS=int(os.environ.get('PARKVISION_OCCUPANCY_MAX_AGE_SECONDS','900')), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('PARKVISION_SECURE_COOKIE','0')=='1')
    if test_config: app.config.update(test_config)
    for key in ('DATA_DIR','UPLOAD_DIR','RESULT_DIR'):
        Path(app.config[key]).mkdir(parents=True, exist_ok=True)
    store=JsonStore(Path(app.config['DATA_DIR']))
    detector=ParkingDetector(app.config['WEIGHTS'], app.config['CONFIDENCE'])
    app.extensions['pv_store']=store; app.extensions['pv_detector']=detector
    @app.before_request
    def protect_posts():
        if request.method=='POST':
            expected=session.get('_csrf',''); actual=request.form.get('_csrf','')
            if not expected or not hmac.compare_digest(expected,actual): abort(400)
    @app.context_processor
    def csrf_context():
        if '_csrf' not in session: session['_csrf']=secrets.token_urlsafe(24)
        return {'csrf_token':session['_csrf']}

    def login_required(fn):
        @wraps(fn)
        def wrapped(*a,**kw):
            if 'user_id' not in session: return redirect(url_for('login', next=request.path))
            return fn(*a,**kw)
        return wrapped
    def admin_required(fn):
        @wraps(fn)
        @login_required
        def wrapped(*a,**kw):
            admin=app.config.get('ADMIN_USERNAME','')
            if not admin or session.get('username','').casefold()!=admin.casefold(): abort(403)
            return fn(*a,**kw)
        return wrapped
    app.jinja_env.globals['model_ready']=lambda: detector.ready
    app.jinja_env.globals['model_status']=lambda: detector.status
    @app.context_processor
    def maps_context(): return {'maps_configured':bool(app.config['GOOGLE_MAPS_BROWSER_KEY']), 'maps_browser_key':app.config['GOOGLE_MAPS_BROWSER_KEY'], 'is_admin':bool(app.config.get('ADMIN_USERNAME')) and session.get('username','').casefold()==app.config.get('ADMIN_USERNAME','').casefold()}

    @app.get('/')
    def home(): return redirect(url_for('dashboard') if 'user_id' in session else url_for('login'))
    @app.route('/register', methods=['GET','POST'])
    def register():
        if request.method=='POST':
            username=request.form.get('username','').strip(); email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
            if len(username)<3 or len(username)>40 or '@' not in email or len(password)<10:
                flash('Use a username (3–40 characters), valid email, and password of at least 10 characters.','error')
            elif store.user_by_name(username) or store.user_by_email(email): flash('That username or email is already registered.','error')
            else:
                store.add_user({'id':uuid.uuid4().hex,'username':username,'email':email,'password_hash':generate_password_hash(password),'created_at':now()})
                flash('Account created. Sign in to continue.','success'); return redirect(url_for('login'))
        return render_template('auth.html', register=True)
    @app.route('/login', methods=['GET','POST'])
    def login():
        if request.method=='POST':
            ident=request.form.get('identity','').strip(); user=store.user_by_name(ident) or store.user_by_email(ident.lower())
            if not user or not check_password_hash(user['password_hash'],request.form.get('password','')):
                session['failures']=session.get('failures',0)+1; flash('Sign-in failed. Check your details and try again.','error')
            elif session.get('failures',0)>=8: flash('Too many attempts in this session. Please restart your browser session.','error')
            else: session.clear(); session['user_id']=user['id']; session['username']=user['username']; return redirect(url_for('dashboard'))
        return render_template('auth.html', register=False)
    @app.get('/logout')
    def logout(): session.clear(); return redirect(url_for('login'))
    def user_records(): return store.analyses(session['user_id'])
    @app.get('/dashboard')
    @login_required
    def dashboard():
        rows=user_records(); latest=rows[0] if rows else None
        primary=occupancy_status(latest, freshness_seconds=app.config['OCCUPANCY_MAX_AGE_SECONDS'])
        return render_template('dashboard.html', rows=rows[:5], latest=latest, primary_parking=primary)
    @app.route('/analyze', methods=['GET','POST'])
    @login_required
    def analyze():
        if request.method=='POST':
            f=request.files.get('image')
            if not f or not f.filename: flash('Choose a parking image to analyze.','error'); return redirect(url_for('analyze'))
            name=secure_filename(f.filename)
            if Path(name).suffix.lower() not in ('.jpg','.jpeg','.png'): flash('Upload a JPG or PNG image.','error'); return redirect(url_for('analyze'))
            ident=uuid.uuid4().hex; target=Path(app.config['UPLOAD_DIR'])/(ident+Path(name).suffix.lower()); f.save(target)
            try:
                import cv2
                with target.open('rb') as image_file: signature=image_file.read(8)
                valid_signature=signature.startswith(b'\xff\xd8\xff') if Path(name).suffix.lower() in ('.jpg','.jpeg') else signature==b'\x89PNG\r\n\x1a\n'
                image=cv2.imread(str(target)) if valid_signature else None
                if image is None: raise ValueError('The uploaded file is not a readable JPG or PNG image.')
                if image.shape[0]*image.shape[1]>25_000_000: raise ValueError('Image dimensions exceed the 25-megapixel limit.')
                started=time.perf_counter(); inference=detector.analyze(target, Path(app.config['RESULT_DIR'])/(ident+'.jpg')); elapsed=round(time.perf_counter()-started,3)
            except (ModelUnavailable, ValueError) as e:
                target.unlink(missing_ok=True); flash(str(e),'error'); return redirect(url_for('analyze'))
            except Exception:
                target.unlink(missing_ok=True); app.logger.exception('Analysis failed'); flash('Image analysis failed. Check image and model configuration.','error'); return redirect(url_for('analyze'))
            record={'id':ident,'user_id':session['user_id'],'timestamp':now(),'source':'uploaded_image','original_image':ident+target.suffix,'annotated_image':ident+'.jpg','processing_time':elapsed,**inference}
            for old in store.add_analysis(record,keep=500):
                for key,folder in (('original_image',app.config['UPLOAD_DIR']),('annotated_image',app.config['RESULT_DIR'])):
                    if old.get(key): (Path(folder)/Path(old[key]).name).unlink(missing_ok=True)
            return redirect(url_for('detail', analysis_id=ident))
        return render_template('upload.html')
    @app.get('/analysis/<analysis_id>')
    @login_required
    def detail(analysis_id):
        row=store.analysis_for_user(analysis_id,session['user_id'])
        if not row: abort(404)
        return render_template('detail.html', row=row)
    @app.get('/history')
    @login_required
    def history(): return render_template('history.html', rows=user_records())
    @app.get('/recommendations')
    @login_required
    def recommendations():
        rows=user_records(); return render_template('recommendations.html', row=rows[0] if rows else None)
    @app.get('/analytics')
    @login_required
    def analytics():
        rows=list(reversed(user_records())); future=request.args.get('future',''); estimate=None; data_range=None
        try:
            selected=datetime.fromisoformat(future) if future else None
            valid=[r for r in rows if isinstance(r.get('occupancy_percentage'),(int,float))]
            if selected and selected>datetime.now() and len(valid)>=5:
                sample=valid[-5:]; estimate=round(sum(r['occupancy_percentage'] for r in sample)/len(sample),1)
                data_range=f"5 most recent classified observations ({sample[0]['timestamp'][:10]} to {sample[-1]['timestamp'][:10]} UTC)"
        except ValueError: future=''
        return render_template('analytics.html', rows=rows, future=future, estimate=estimate, data_range=data_range)
    @app.get('/settings')
    @login_required
    def settings(): return render_template('settings.html')
    @app.get('/api/parking/alternatives')
    @login_required
    def parking_alternatives():
        rows=user_records(); latest=rows[0] if rows else None
        primary=occupancy_status(latest, freshness_seconds=app.config['OCCUPANCY_MAX_AGE_SECONDS'])
        approved=[]
        for facility in store.overflow_facilities():
            if not facility.get('approved'): continue
            availability=facility_availability(facility, freshness_seconds=app.config['OCCUPANCY_MAX_AGE_SECONDS'])
            public_fields=('id','name','address','latitude','longitude','capacity','vacant_spaces','occupancy_updated_at','operating_hours','operating_status','price_label','price_value','vehicle_restrictions','approved')
            approved.append({**{key:facility.get(key) for key in public_fields}, 'availability': availability})
        ranks=rank_facilities([{**f,'availability_status':f['availability']['status'],'availability_reliable':f['availability'].get('reliable',False),'public_listing':False} for f in approved])
        score_by_id={f['id']:f['recommendation_score'] for f in ranks}
        approved.sort(key=lambda f:(f['id'] not in score_by_id,-score_by_id.get(f['id'],-1),f.get('name','').casefold()))
        for facility in approved: facility['recommendation_score']=score_by_id.get(facility['id'])
        return jsonify({'primary':primary,'analysis_id':latest.get('id') if latest else None,'overflow_facilities':approved,'maps_configured':bool(app.config['GOOGLE_MAPS_BROWSER_KEY']),'search_radius_max_meters':50000})
    @app.route('/admin/overflow', methods=['GET','POST'])
    @admin_required
    def admin_overflow():
        if request.method=='POST':
            action=request.form.get('action','save')
            ident=request.form.get('id','').strip()
            if action=='delete':
                if ident: store.delete_overflow_facility(ident)
                flash('Overflow facility removed.','success'); return redirect(url_for('admin_overflow'))
            try:
                name=request.form.get('name','').strip(); address=request.form.get('address','').strip()
                lat=float(request.form.get('latitude','')); lng=float(request.form.get('longitude',''))
                capacity_raw=request.form.get('capacity','').strip(); vacant_raw=request.form.get('vacant_spaces','').strip(); price_raw=request.form.get('price_value','').strip()
                capacity=int(capacity_raw) if capacity_raw else None; vacant=int(vacant_raw) if vacant_raw else None; price=float(price_raw) if price_raw else None
                if not name or not address or not (-90<=lat<=90 and -180<=lng<=180): raise ValueError
                if capacity is not None and capacity<1 or vacant is not None and vacant<0 or (capacity is not None and vacant is not None and vacant>capacity) or (price is not None and price<0): raise ValueError
            except (TypeError,ValueError):
                flash('Enter a name, address, valid coordinates, and non-negative capacity, vacancy, and price values.','error')
                return redirect(url_for('admin_overflow'))
            occupancy_stamp=request.form.get('occupancy_updated_at','').strip()
            if vacant is not None and not occupancy_stamp: occupancy_stamp=now()
            elif occupancy_stamp:
                try:
                    parsed=datetime.fromisoformat(occupancy_stamp.replace('Z','+00:00'))
                    parsed=parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
                    if parsed>datetime.now(timezone.utc): raise ValueError
                except ValueError:
                    flash('Use a valid ISO timestamp that is not in the future for the occupancy update.','error'); return redirect(url_for('admin_overflow'))
            facility={'id':ident or uuid.uuid4().hex,'name':name,'address':address,'latitude':lat,'longitude':lng,'capacity':capacity,'vacant_spaces':vacant,'occupancy_updated_at':occupancy_stamp or None,'operating_hours':request.form.get('operating_hours','').strip(),'operating_status':request.form.get('operating_status','unknown') if request.form.get('operating_status') in ('open','closed','unknown') else 'unknown','price_label':request.form.get('price_label','').strip(),'price_value':price,'vehicle_restrictions':request.form.get('vehicle_restrictions','').strip(),'approved':request.form.get('approved')=='on','updated_at':now(),'updated_by':session.get('username')}
            store.save_overflow_facility(facility); flash('Overflow facility saved.','success'); return redirect(url_for('admin_overflow'))
        facilities=store.overflow_facilities(); editing=next((f for f in facilities if f.get('id')==request.args.get('edit')),None)
        return render_template('admin_overflow.html',facilities=facilities,editing=editing)
    @app.get('/media/<kind>/<path:filename>')
    @login_required
    def media(kind,filename):
        row=store.analysis_by_media(filename,session['user_id'])
        if kind not in ('original','result') or not row: abort(404)
        return send_from_directory(app.config['UPLOAD_DIR'] if kind=='original' else app.config['RESULT_DIR'],filename)
    @app.get('/api/status')
    @login_required
    def status(): return jsonify({'model_ready':detector.ready,'model_message':detector.status,'analysis_count':len(user_records())})
    @app.errorhandler(413)
    def too_large(_): return render_template('error.html', message='Image exceeds the 8 MB upload limit.'),413
    @app.errorhandler(404)
    def not_found(_): return render_template('error.html', message='That page or analysis was not found.'),404
    @app.errorhandler(400)
    def bad_request(_): return render_template('error.html', message='The form expired or could not be verified. Reload and try again.'),400
    @app.errorhandler(403)
    def forbidden(_): return render_template('error.html', message='This page is restricted to the configured ParkVision administrator.'),403
    return app

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')

app=create_app()
if __name__=='__main__': app.run(host='127.0.0.1',port=5000,debug=False)
