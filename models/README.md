# Parking model setup and verification

## Current local checkpoint

The local `models/best.pt` was downloaded from the public Hugging Face model `dronefreak/pklot-yolov8s`. Its model card says it is a YOLOv8s detector fine-tuned on PKLot for the two classes `vacant` and `occupied`. The file is 22,533,226 bytes and its SHA-256 is:

`534895f702ad44a71c2baa8a60c6fbe5369d721dc26fed8196f1ce791c11f783`

The repository license is AGPL-3.0. Review the model and dataset terms before redistributing the checkpoint or a project that includes it. The checkpoint is excluded from Git by `.gitignore`, so a fresh clone needs to download it separately.

Source model card and download: <https://huggingface.co/dronefreak/pklot-yolov8s>

PowerShell download command, run from the project root:

```powershell
New-Item -ItemType Directory -Force .\models | Out-Null
curl.exe --fail --location --output .\models\best.pt https://huggingface.co/dronefreak/pklot-yolov8s/resolve/main/best.pt
.\.venv\Scripts\python.exe -c "from ultralytics import YOLO; print(YOLO(r'models\best.pt').names)"
```

Expected class mapping: `{0: 'vacant', 1: 'occupied'}`. ParkVision checks for those class meanings on startup. A generic COCO checkpoint is not an occupancy model and is not accepted.

## Smoke test performed

The checkpoint loaded in the project virtual environment and reported the expected class names. Inference was also run on the model publisher's `pklot_yolov8s_showcase.jpg`; the ParkVision detector adapter returned 272 slot boxes (169 vacant and 103 occupied). The temporary showcase image and generated result were removed after the check. This is a single-image smoke test using an image supplied by the model publisher, not an independent accuracy evaluation or a guarantee for a different camera.

## Training provenance and limitations

The publisher's model card identifies PKLot as the training dataset and reports YOLOv8s fine-tuning. ParkVision has not independently audited those training records or metrics. The model detects parking bays as vacant or occupied; it is not trained here to identify vehicle makes/models or to separately classify cars, motorcycles, vans, or buses.

PKLot-style fixed-camera images are the intended input. Validate on held-out images from the actual target lot before relying on results. Camera angle, lighting, weather, image resolution and occlusion can change performance.

If using your own checkpoint, it must be a compatible Ultralytics YOLO detector with a vacant/empty/free class and an occupied/full class. Configure `PARKVISION_WEIGHTS` to its path. Confidence threshold is controlled by `PARKVISION_CONFIDENCE`.
