from datetime import datetime, timedelta, timezone

from alternatives import occupancy_status, facility_availability, rank_facilities
from app import create_app


def test_primary_is_full_only_when_recent_and_reliable():
    now = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
    row = {'timestamp': now.isoformat(), 'total_spaces': 10, 'vacant_spaces': 0,
           'occupied_spaces': 10, 'uncertain_spaces': 0, 'occupancy_percentage': 100.0}
    assert occupancy_status(row, now)['status'] == 'full'
    assert occupancy_status({**row, 'timestamp': (now-timedelta(minutes=16)).isoformat()}, now)['status'] == 'stale'
    assert occupancy_status({**row, 'uncertain_spaces': 5}, now)['status'] == 'unavailable'
    assert occupancy_status({**row, 'total_spaces': 0}, now)['status'] == 'unavailable'


def test_overflow_availability_requires_approval_and_fresh_count():
    now = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
    row = {'approved': True, 'vacant_spaces': 4, 'occupancy_updated_at': now.isoformat()}
    assert facility_availability(row, now)['status'] == 'available'
    assert facility_availability({**row, 'occupancy_updated_at': (now-timedelta(minutes=20)).isoformat()}, now)['status'] == 'stale'
    assert facility_availability({**row, 'approved': False}, now)['status'] == 'unauthorized'
    assert facility_availability({**row, 'vacant_spaces': 0}, now)['status'] == 'full'


def test_ranking_preferences_unknown_cost_and_exclusions():
    facilities = [
        {'id': 'approved', 'name': 'Approved lot', 'approved': True, 'availability_status': 'available', 'availability_reliable': True, 'drive_minutes': 20, 'walk_minutes': 5, 'price_value': 10},
        {'id': 'unknown', 'name': 'Unknown garage', 'approved': False, 'public_listing': True, 'availability_status': 'unknown', 'availability_reliable': False, 'drive_minutes': 5, 'walk_minutes': 3, 'price_value': None},
        {'id': 'full', 'name': 'Full lot', 'approved': True, 'availability_status': 'full', 'availability_reliable': True},
        {'id': 'private', 'name': 'Private lot', 'approved': False, 'availability_status': 'available', 'availability_reliable': True},
        {'id': 'closed', 'name': 'Closed garage', 'approved': True, 'availability_status': 'unknown', 'business_status': 'CLOSED_PERMANENTLY'},
    ]
    preferred = rank_facilities(facilities, 'availability')
    assert [f['id'] for f in preferred] == ['approved', 'unknown']
    fastest = rank_facilities(facilities, 'fastest_drive')
    assert fastest[0]['id'] == 'unknown'
    assert next(f for f in preferred if f['id'] == 'unknown')['price_value'] is None
    assert rank_facilities([facilities[2], facilities[3]]) == []


def test_authenticated_admin_can_add_authorized_overflow_and_api_hides_unapproved(tmp_path):
    app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'ADMIN_USERNAME': 'admin',
                      'WEIGHTS': str(tmp_path/'missing.pt'), 'DATA_DIR': tmp_path/'data',
                      'UPLOAD_DIR': tmp_path/'uploads', 'RESULT_DIR': tmp_path/'results',
                      'GOOGLE_MAPS_BROWSER_KEY': ''})
    c = app.test_client()
    import re
    page = c.get('/register'); csrf = re.search(rb'name="_csrf" value="([^"]+)', page.data).group(1).decode()
    c.post('/register', data={'_csrf': csrf, 'username': 'admin', 'email': 'admin@example.com', 'password': 'long-password'})
    page = c.get('/login'); csrf = re.search(rb'name="_csrf" value="([^"]+)', page.data).group(1).decode()
    c.post('/login', data={'_csrf': csrf, 'identity': 'admin', 'password': 'long-password'})
    page = c.get('/admin/overflow'); assert page.status_code == 200
    csrf = re.search(rb'name="_csrf" value="([^"]+)', page.data).group(1).decode()
    c.post('/admin/overflow', data={'_csrf': csrf, 'name': 'Authorized lot', 'address': '1 Main St',
        'latitude': '12.5', 'longitude': '77.5', 'capacity': '20', 'vacant_spaces': '4',
        'operating_status': 'open', 'approved': 'on'})
    # An unapproved lot stays out of the public alternatives endpoint.
    csrf = re.search(rb'name="_csrf" value="([^"]+)', c.get('/admin/overflow').data).group(1).decode()
    c.post('/admin/overflow', data={'_csrf': csrf, 'name': 'Private lot', 'address': '2 Main St', 'latitude': '12.6', 'longitude': '77.6', 'operating_status': 'open'})
    data = c.get('/api/parking/alternatives').get_json()
    assert data['maps_configured'] is False
    assert len(data['overflow_facilities']) == 1
    assert data['overflow_facilities'][0]['availability']['status'] == 'available'



def test_map_fallback_copy_and_radius_limit_are_present():
    from pathlib import Path
    js = (Path(__file__).parents[1] / 'static' / 'parking_map.js').read_text(encoding='utf-8-sig')
    css = (Path(__file__).parents[1] / 'static' / 'style.css').read_text(encoding='utf-8-sig')
    dashboard = (Path(__file__).parents[1] / 'templates' / 'dashboard.html').read_text(encoding='utf-8-sig')
    assert 'No nearby facilities were returned' in js
    assert 'Directions failed. Check Routes API access.' in js
    assert '50 km maximum' in js and '50000' in dashboard
    assert '.verified' in css and '.unknown' in css and '.unavailable' in css
