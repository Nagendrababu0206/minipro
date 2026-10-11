# ParkVision

Flask-based student project for parking occupancy analysis. The application stores accounts and successful analysis records in local JSON files and stores image files separately. Real inference uses a PKLot-tuned YOLOv8s parking-slot checkpoint, downloaded locally but excluded from Git; no predictions are bundled.

## Verified project status

The included runtime must be prepared before use. The checkpoint is excluded from Git, so a fresh checkout without `models/best.pt` runs in a clear model-unavailable state; it will not substitute generic COCO object weights. This working folder now has the PKLot-tuned checkpoint documented in [models/README.md](models/README.md). Percentages exclude uncertain classes and return no percentage if there are no classified bays. Historical charts require actual saved observations. A simple moving-average estimate is available only after five classified observations and is labeled with the sample range and its comparable-camera assumption.

## Windows PowerShell setup

Use Python 3.11 (recommended for broad PyTorch/Ultralytics wheel support) and run from this directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
curl.exe --fail --location --output .\models\best.pt https://huggingface.co/dronefreak/pklot-yolov8s/resolve/main/best.pt
$env:PARKVISION_SECRET = (python -c "import secrets; print(secrets.token_urlsafe(48))")
$env:PARKVISION_WEIGHTS = (Resolve-Path .\models\best.pt).Path
python app.py
```

Open `http://127.0.0.1:5000`, create the first account using Register, then sign in. If PowerShell blocks venv activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` for that terminal and activate again. Do not commit `.env`, model weights, uploads, results, or private user data.

To start without weights and inspect the model-unavailable UI, omit the `PARKVISION_WEIGHTS` assignment. To use another confidence threshold, set `$env:PARKVISION_CONFIDENCE = '0.35'` before starting. Review [models/README.md](models/README.md) for weight requirements and a fine-tuning outline.


## Smart alternative parking

The signed-in dashboard can search for a manually selected main destination, show nearby parking facilities on Google Maps, and expand the radius from 1 km up to Google's 50 km Nearby Search limit. Use the browser location button to set the driver's route origin. Nearby Google listings are always **Availability unknown**; a listing is not proof of public access or a vacant space. Known permanently/temporarily closed listings are excluded.

The primary lot is marked FULL only if a fresh uploaded-image observation is at most 15 minutes old, has at least 8 classified bays, and no more than 20% uncertain bays, with zero vacant bays. Stale or low-quality results are shown as stale/unavailable instead of full. The maximum age is configurable with `PARKVISION_OCCUPANCY_MAX_AGE_SECONDS` (PowerShell default: `$env:PARKVISION_OCCUPANCY_MAX_AGE_SECONDS = '900'`). A still image remains an observation from its upload time, not a live occupancy feed.

Administrators can approve overflow locations at **Settings ? Manage approved overflow lots**. Set `PARKVISION_ADMIN_USERNAME` to the username of an existing account before starting Flask. The admin form stores address/coordinates, capacity, manually verified vacant count and timestamp, operator-authorized approval, open/closed/unknown status, hours, cost notes, and restrictions in `data/overflow_facilities.json`. Only approved locations appear as overflow options. Counts older than the freshness window become unknown; current zero-vacancy facilities are omitted from navigation recommendations. The operator must explicitly authorize each facility; ordinary businesses are never assumed to allow public overflow parking.

Ranking weights are explicit: **verified availability** uses availability/drive/walk/cost weights of 60/15/10/15; **shortest drive** 10/70/10/10; **shortest walk** 25/10/55/10; **cheapest** 25/10/10/55. Route time is normalized over 60 minutes driving and 30 minutes walking; numeric known cost is normalized over 50 local-currency units. Missing travel time or cost gets a neutral score and is displayed as unknown. A recently verified vacant approved overflow lot receives the strongest availability score. Scores explain the preference but do not guarantee entry or a space on arrival.

Google Maps setup: enable **Maps JavaScript API**, **Places API (New)**, and **Routes API**, attach billing, and create a referrer-restricted browser key for `http://localhost:5000/*` and `http://127.0.0.1:5000/*`. Set `$env:GOOGLE_MAPS_BROWSER_KEY = 'your-restricted-browser-key'` and restart Flask. To enable the overflow admin for an existing account, also set `$env:PARKVISION_ADMIN_USERNAME = 'admin'` where `admin` is that account's username, then restart Flask. Nearby Search accepts radii up to 50,000 m; route estimates and Places requests may incur charges. Route estimates are requested for at most eight nearby candidates per search. Walking routes can omit sidewalks or pedestrian paths; Google requires this warning to be shown. [Places Nearby Search documentation](https://developers.google.com/maps/documentation/javascript/nearby-search), [Routes JavaScript documentation](https://developers.google.com/maps/documentation/javascript/reference/route), [walking-route notice](https://developers.google.com/maps/documentation/javascript/routes/routes-polylines).

Park-and-ride and passenger drop-off are not displayed unless verified transit-connected parking or an authorized drop-off zone is configured. This project currently has no transit or drop-off data source, so it does not invent either option. Without a valid Maps key, the dashboard explains that search and routes are unavailable; overflow occupancy rules and admin management still work.

Slot overlays are drawn from stored model boxes. A vacant bay can be selected for a dashed visual pointer on the source image. It is not an indoor driving route.

## Tests

```powershell
python -m pytest -q
```

Tests cover account security, occupancy saturation and freshness, overflow approval, recommendation scoring preferences, unknown prices, Google Maps key absence, and the existing authenticated routes. Live Places/Routes requests still require a valid restricted key and are not exercised without credentials.

## Viva walkthrough

1. Flask routes accept forms and keep pages behind a session login. Passwords use Werkzeug's salted hash functions; form POSTs require a session CSRF token.
2. `ParkingDetector` loads only the supplied YOLO checkpoint. It checks the model's class names, runs inference at the configured confidence threshold, and converts model boxes to pixel-coordinate slot records.
3. The detector paints green vacant, red occupied, and orange unknown boxes. The service counts known states; uncertain slots do not inflate either occupancy or vacancy percentage.
4. `JsonStore` owns persistence. It updates JSON through a temporary file and atomic replacement. Each analysis is linked to its owner, and image serving checks that ownership.
5. Alternative parking status is computed from timestamped observations and an explicit reliability threshold. Only administrator-approved overflow lots can have verified availability; public map listings remain unknown. Ranking weights make availability, driving time, walking time, and cost tradeoffs visible.

## Limitations

- The local PKLot checkpoint loaded with the expected class names and returned detections on one publisher showcase image; its training claims and accuracy have not been independently audited. The file is excluded from Git.
- Class-name inspection only checks the interface contract; it does not validate accuracy, calibration, or suitability for a different camera.
- This image model has not been accuracy-validated for every camera. Low-quality, stale, or zero-detection results must not be used as live availability.
- Park-and-ride, transit, and authorized drop-off suggestions are omitted until verified data is supplied.
- The Maps key must be configured and restricted; live integration cannot be verified in a no-key environment. Google API requests may incur charges.
- JSON locking is process-local. For a multi-process deployment, use a database with transactions. This project is intended for local demonstration, not public production hosting.
- Session login throttling is intentionally basic. Deploying publicly requires a stronger rate limiter, HTTPS, secret management, and operational hardening.
