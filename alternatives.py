"""Honest occupancy status and transparent alternative-facility ranking."""
from datetime import datetime, timezone

FRESHNESS_SECONDS = 15 * 60
MIN_CLASSIFIED_SPACES = 8
MAX_UNCERTAIN_RATIO = 0.20


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def occupancy_status(observation, now=None, freshness_seconds=FRESHNESS_SECONDS):
    """Classify one image observation; never infer live availability from old/weak data."""
    if not observation:
        return {'status': 'unavailable', 'reliable': False, 'reason': 'No parking analysis is available.', 'age_seconds': None}
    timestamp = _timestamp(observation.get('timestamp'))
    if timestamp is None:
        return {'status': 'unavailable', 'reliable': False, 'reason': 'The observation has no valid timestamp.', 'age_seconds': None}
    now = now or datetime.now(timezone.utc)
    age = max(0, int((now.astimezone(timezone.utc) - timestamp).total_seconds()))
    if age > freshness_seconds:
        return {'status': 'stale', 'reliable': False, 'source': observation.get('source', 'unknown'), 'reason': 'The last image observation is stale; analyze a fresh image.', 'age_seconds': age, 'observed_at': timestamp.isoformat()}
    total = int(observation.get('total_spaces') or 0)
    vacant = int(observation.get('vacant_spaces') or 0)
    occupied = int(observation.get('occupied_spaces') or 0)
    uncertain = int(observation.get('uncertain_spaces') or 0)
    classified = vacant + occupied
    ratio = uncertain / total if total else 1
    if classified < MIN_CLASSIFIED_SPACES or total <= 0 or ratio > MAX_UNCERTAIN_RATIO:
        return {'status': 'unavailable', 'reliable': False, 'source': observation.get('source', 'unknown'), 'reason': 'The image result does not contain enough reliable classified spaces.', 'age_seconds': age, 'observed_at': timestamp.isoformat()}
    base = {'reliable': True, 'source': observation.get('source', 'uploaded_image'), 'age_seconds': age, 'observed_at': timestamp.isoformat(), 'vacant_spaces': vacant, 'occupied_spaces': occupied, 'uncertain_spaces': uncertain, 'occupancy_percentage': observation.get('occupancy_percentage')}
    if vacant == 0:
        return {**base, 'status': 'full', 'reason': 'A fresh, sufficiently reliable analysis found no confirmed vacant spaces.'}
    return {**base, 'status': 'available', 'reason': f'{vacant} confirmed vacant space(s) in the latest image analysis.'}


def facility_availability(facility, now=None, freshness_seconds=FRESHNESS_SECONDS):
    """Return status for an explicitly approved facility with manually verified counts."""
    if not facility.get('approved'):
        return {'status': 'unauthorized', 'reliable': False, 'reason': 'This facility is not approved for public overflow parking.'}
    if facility.get('operating_status') == 'closed':
        return {'status': 'closed', 'reliable': True, 'reason': 'The administrator marked this facility closed.'}
    stamp = _timestamp(facility.get('occupancy_updated_at'))
    vacant = facility.get('vacant_spaces')
    if stamp is None or vacant is None:
        return {'status': 'unknown', 'reliable': False, 'reason': 'No verified occupancy count is available.'}
    now = now or datetime.now(timezone.utc)
    age = max(0, int((now.astimezone(timezone.utc) - stamp).total_seconds()))
    if age > freshness_seconds:
        return {'status': 'stale', 'reliable': False, 'reason': 'The verified occupancy count is stale.', 'age_seconds': age, 'observed_at': stamp.isoformat()}
    vacant = max(0, int(vacant))
    return {'status': 'available' if vacant > 0 else 'full', 'reliable': True, 'source': 'administrator_verified', 'vacant_spaces': vacant, 'age_seconds': age, 'observed_at': stamp.isoformat(), 'reason': 'Verified recent capacity report.'}


PREFERENCE_WEIGHTS = {
    'availability': {'availability': .60, 'drive': .15, 'walk': .10, 'cost': .15},
    'fastest_drive': {'availability': .10, 'drive': .70, 'walk': .10, 'cost': .10},
    'shortest_walk': {'availability': .25, 'drive': .10, 'walk': .55, 'cost': .10},
    'cheapest': {'availability': .25, 'drive': .10, 'walk': .10, 'cost': .55},
}


def rank_facilities(facilities, preference='availability'):
    """Score approved/open candidates only; missing measurements stay neutral and visible."""
    weights = PREFERENCE_WEIGHTS.get(preference, PREFERENCE_WEIGHTS['availability'])
    eligible = []
    for facility in facilities:
        if (not facility.get('approved', True) and not facility.get('public_listing', False)) or facility.get('business_status') in ('CLOSED_PERMANENTLY', 'CLOSED_TEMPORARILY') or facility.get('operating_status') == 'closed':
            continue
        availability = facility.get('availability_status', 'unknown')
        if availability == 'full':
            continue
        av = 1.0 if availability == 'available' and facility.get('availability_reliable') else (0.45 if facility.get('approved') else 0.2)
        drive = facility.get('drive_minutes')
        walk = facility.get('walk_minutes')
        cost = facility.get('price_value')
        # Normalize with broad, documented comparison ranges; null values are neutral.
        drive_score = max(0, 1 - float(drive) / 60) if drive is not None else .5
        walk_score = max(0, 1 - float(walk) / 30) if walk is not None else .5
        cost_score = max(0, 1 - float(cost) / 50) if cost is not None else .5
        score = 100 * (weights['availability'] * av + weights['drive'] * drive_score + weights['walk'] * walk_score + weights['cost'] * cost_score)
        eligible.append({**facility, 'recommendation_score': round(score, 1), 'recommendation_reason': _reason(facility, availability)})
    return sorted(eligible, key=lambda x: (-x['recommendation_score'], x.get('drive_minutes') is None, x.get('drive_minutes') or 0, x.get('name', '').casefold()))


def _reason(facility, availability):
    if facility.get('approved') and availability == 'available' and facility.get('availability_reliable'):
        return 'Approved overflow location with a recent verified vacant-space count.'
    if facility.get('approved'):
        return 'Administrator-approved overflow location; current availability is not verified.'
    return 'Nearby parking facility; availability, permission, and pricing are unknown.'
