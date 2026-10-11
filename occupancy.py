"""Pure occupancy math, independent of OpenCV or model runtime."""
def summarize(slots):
    vacant=sum(s['classification']=='VACANT' for s in slots)
    occupied=sum(s['classification']=='OCCUPIED' for s in slots)
    uncertain=len(slots)-vacant-occupied
    classified=vacant+occupied
    return {
        'total_spaces':len(slots), 'vacant_spaces':vacant, 'occupied_spaces':occupied,
        'uncertain_spaces':uncertain,
        'occupancy_percentage':round(occupied/classified*100,1) if classified else None,
        'vacancy_percentage':round(vacant/classified*100,1) if classified else None,
        'average_confidence':round(sum(s['confidence'] for s in slots)/len(slots),4) if slots else None,
        'detected_slots':slots,
        'recommendations':[{'slot_id':s['slot_id'],'reason':'Vacant and ranked by detector confidence.'}
            for s in sorted((x for x in slots if x['classification']=='VACANT'),key=lambda z:z['confidence'],reverse=True)]
    }
