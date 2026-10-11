/* Draws the actual model boxes and a clearly non-navigational target pointer. */
(() => {
  const image=document.querySelector('#source-image'), canvas=document.querySelector('#slot-canvas');
  if(!image||!canvas)return;
  const slots=JSON.parse(document.querySelector('#slot-data').textContent);
  const context=canvas.getContext('2d');
  const colors={VACANT:'#2ead68',OCCUPIED:'#d94a4a',UNCERTAIN:'#f0a526'};
  const redraw=()=>{
    if(!image.naturalWidth)return;
    canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
    context.drawImage(image,0,0);
    const boxes=document.querySelector('#toggle-boxes').checked;
    const labels=document.querySelector('#toggle-labels').checked;
    const target=document.querySelector('#target-slot').value;
    const selected=slots.find(slot=>slot.slot_id===target&&slot.classification==='VACANT');
    if(boxes){
      slots.forEach(slot=>{
        const [x1,y1,x2,y2]=slot.bbox,color=colors[slot.classification]||'#aab1b8';
        context.lineWidth=slot===selected?Math.max(4,image.naturalWidth/350):Math.max(2,image.naturalWidth/700);
        context.strokeStyle=slot===selected?'#ffcf42':color;
        context.strokeRect(x1,y1,x2-x1,y2-y1);
        if(labels){
          const text=`${slot.slot_id} - ${slot.classification}${Number.isFinite(slot.confidence)?` - ${(slot.confidence*100).toFixed(0)}%`:''}`;
          const fontSize=Math.max(13,Math.min(24,image.naturalWidth/55));context.font=`600 ${fontSize}px Arial`;
          const pad=5,tw=context.measureText(text).width,tx=Math.max(0,Math.min(x1,image.naturalWidth-tw-pad*2));
          const ty=Math.max(fontSize+pad,Math.min(y1,image.naturalHeight));
          context.fillStyle='rgba(20,25,31,.86)';context.fillRect(tx,ty-fontSize-pad,tw+pad*2,fontSize+pad*2);
          context.fillStyle=color;context.fillText(text,tx+pad,ty);
        }
      });
    }
    if(selected){
      const [x1,y1,x2,y2]=selected.bbox,tx=(x1+x2)/2,ty=(y1+y2)/2;
      const sx=Math.max(0,Math.min(image.naturalWidth-1,image.naturalWidth*.04)),sy=Math.max(0,Math.min(image.naturalHeight-1,ty));
      context.save();context.strokeStyle='#ffd34d';context.fillStyle='#ffd34d';context.lineWidth=Math.max(4,image.naturalWidth/450);context.setLineDash([12,10]);
      context.beginPath();context.moveTo(sx,sy);context.lineTo(tx,ty);context.stroke();context.setLineDash([]);
      const angle=Math.atan2(ty-sy,tx-sx),head=Math.max(18,image.naturalWidth/45);
      context.beginPath();context.moveTo(tx,ty);context.lineTo(tx-head*Math.cos(angle-.45),ty-head*Math.sin(angle-.45));context.lineTo(tx-head*Math.cos(angle+.45),ty-head*Math.sin(angle+.45));context.closePath();context.fill();context.restore();
    }
  };
  image.addEventListener('load',redraw);if(image.complete)redraw();
  ['toggle-boxes','toggle-labels','target-slot'].forEach(id=>document.getElementById(id).addEventListener('change',redraw));
})();
