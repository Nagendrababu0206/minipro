"""Strict adapter for custom YOLOv8 parking-space occupancy weights."""
from pathlib import Path
from occupancy import summarize

class ModelUnavailable(RuntimeError): pass

class ParkingDetector:
    def __init__(self, weights, confidence=.35):
        self.weights=Path(weights); self.confidence=float(confidence); self.model=None; self.status='Custom parking weights are not configured.'
        if not self.weights.is_file():
            self.status=f'Checkpoint file not found: {self.weights.resolve()}'
            return
        try:
            from ultralytics import YOLO
            self.model=YOLO(str(self.weights)); self.names={int(k):str(v).strip().lower() for k,v in self.model.names.items()}
            if not self._valid_names(): self.model=None; self.status='Weights must expose vacant/empty and occupied classes; generic COCO weights are unsupported.'
            else: self.status=f'Loaded custom weights: {self.weights.name} ({", ".join(self.names.values())}).'
        except Exception as exc: self.status=f'Could not load checkpoint ({type(exc).__name__}): {exc}'
    def _valid_names(self):
        vals=set(self.names.values()); return bool(vals & {'vacant','empty','free'}) and bool(vals & {'occupied','full'})
    @property
    def ready(self): return self.model is not None
    def analyze(self,path,out_path):
        if not self.ready: raise ModelUnavailable(self.status+' Add a compatible YOLOv8s parking checkpoint or set PARKVISION_WEIGHTS to its path.')
        import cv2
        image=cv2.imread(str(path))
        if image is None: raise ValueError('The uploaded file is not a readable image.')
        result=self.model.predict(source=image,conf=self.confidence,verbose=False)[0]
        slots=[]; annotated=image.copy()
        for box in result.boxes:
            cid=int(box.cls.item()); label=self.names.get(cid,'unknown'); conf=float(box.conf.item())
            xy=[int(v) for v in box.xyxy[0].tolist()]
            # Remove near-identical bay boxes even if the model emitted competing classes.
            if any(self._iou(xy, existing['bbox']) >= .75 for existing in slots): continue
            if label in ('vacant','empty','free'): state='VACANT'; color=(104,173,46)
            elif label in ('occupied','full'): state='OCCUPIED'; color=(74,74,217)
            else: state='UNCERTAIN'; color=(40,165,240)
            idx=len(slots)+1; slot_id=f'P{idx:02d}'
            slots.append({'slot_id':slot_id,'bbox':xy,'classification':state,'confidence':round(conf,4),'recommended':state=='VACANT'})
            cv2.rectangle(annotated,(xy[0],xy[1]),(xy[2],xy[3]),color,2)
            label_text=f'{slot_id} - {state} - {conf:.0%}'
            font=cv2.FONT_HERSHEY_SIMPLEX; scale=.55; thickness=2
            (tw,th),baseline=cv2.getTextSize(label_text,font,scale,thickness)
            tx=max(0,min(xy[0],annotated.shape[1]-tw-8)); ty=max(th+8,min(xy[1],annotated.shape[0]-baseline-2))
            cv2.rectangle(annotated,(tx,ty-th-8),(tx+tw+8,ty+baseline), (28,32,38),-1)
            cv2.putText(annotated,label_text,(tx+4,ty-3),font,scale,color,thickness,cv2.LINE_AA)
        Path(out_path).parent.mkdir(parents=True,exist_ok=True); cv2.imwrite(str(out_path),annotated)
        return summarize(slots)
    @staticmethod
    def _iou(a,b):
        x1=max(a[0],b[0]); y1=max(a[1],b[1]); x2=min(a[2],b[2]); y2=min(a[3],b[3])
        inter=max(0,x2-x1)*max(0,y2-y1); area_a=max(0,a[2]-a[0])*max(0,a[3]-a[1]); area_b=max(0,b[2]-b[0])*max(0,b[3]-b[1])
        union=area_a+area_b-inter
        return inter/union if union else 0.0
