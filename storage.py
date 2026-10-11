"""Small JSON persistence layer with atomic replacement and per-file locks."""
import json, threading, os
from pathlib import Path

class JsonStore:
    def __init__(self, root):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True); self.lock=threading.RLock()
        for file in ('users.json','analyses.json','overflow_facilities.json'):
            p=self.root/file
            if not p.exists(): self._write(file,[])
    def _read(self,name):
        try:
            with (self.root/name).open(encoding='utf-8') as f: data=json.load(f)
            return [item for item in data if isinstance(item,dict)] if isinstance(data,list) else []
        except (OSError,json.JSONDecodeError): return []
    def _write(self,name,data):
        p=self.root/name; temp=p.with_suffix('.tmp')
        with temp.open('w',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2); f.flush(); os.fsync(f.fileno())
        os.replace(temp,p)
    def _change(self,name,fn):
        with self.lock:
            data=self._read(name); result=fn(data); self._write(name,data); return result
    def users(self): return self._read('users.json')
    def user_by_name(self,v): return next((x for x in self.users() if x.get('username','').casefold()==v.casefold()),None)
    def user_by_email(self,v): return next((x for x in self.users() if x.get('email','').casefold()==v.casefold()),None)
    def add_user(self,u): return self._change('users.json',lambda d:d.append(u))
    def add_analysis(self,a,keep=500):
        removed=[]
        def insert(data):
            data.insert(0,a)
            owned=[x for x in data if x.get('user_id')==a.get('user_id')]
            for old in owned[max(1,int(keep)):]:
                data.remove(old); removed.append(old)
        self._change('analyses.json',insert)
        return removed
    def analyses(self,user_id): return [x for x in self._read('analyses.json') if x.get('user_id')==user_id]
    def analysis_for_user(self,ident,user_id): return next((x for x in self.analyses(user_id) if x.get('id')==ident),None)
    def analysis_by_media(self,filename,user_id): return next((x for x in self.analyses(user_id) if filename in (x.get('original_image'),x.get('annotated_image'))),None)
    def overflow_facilities(self): return self._read('overflow_facilities.json')
    def save_overflow_facility(self, facility):
        def save(data):
            for index, current in enumerate(data):
                if current.get('id') == facility.get('id'):
                    data[index] = facility
                    return
            data.append(facility)
        self._change('overflow_facilities.json', save)
        return facility
    def delete_overflow_facility(self, ident):
        removed=[]
        def delete(data):
            for facility in list(data):
                if facility.get('id') == ident:
                    data.remove(facility); removed.append(facility)
        self._change('overflow_facilities.json', delete)
        return bool(removed)
