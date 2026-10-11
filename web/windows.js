import { liveState } from './windows-state.js';
const $ = id => document.getElementById(id);
const text = (id,value) => { $(id).textContent=value; };
let latest=null, networkError=false;
const ms = value => value === null || value === undefined ? '—' : `${Math.round(value)} ms`;

function status() {
  const s=liveState(latest,Date.now(),networkError);
  text('live-status',s.label); $('live-status').className=`status-pill ${s.kind}`;
  if (latest) text('live-age',`Senaste rapport: ${Math.max(0,Math.floor((Date.now()-Date.parse(latest.telemetry.updatedAt))/1000))} s sedan`);
}

function drawScene(s) {
  const canvas=$('live-scene'),ctx=canvas.getContext('2d');
  ctx.fillStyle='#101b20';ctx.fillRect(0,0,canvas.width,canvas.height);
  if (!s) return;
  ctx.save();ctx.scale(canvas.width/s.width,canvas.height/s.height);
  ctx.strokeStyle='#8ce8af';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(0,s.groundY);ctx.lineTo(s.width,s.groundY);ctx.stroke();
  const box=(b,fill)=>{ctx.fillStyle=fill;ctx.fillRect(b.left,b.top,b.right-b.left,b.bottom-b.top);ctx.strokeStyle='#ffda65';ctx.strokeRect(b.left,b.top,b.right-b.left,b.bottom-b.top);};
  box(s.cube,'#8ce8af');
  for(const b of s.spikes) {ctx.fillStyle='#ec8bac';ctx.beginPath();ctx.moveTo(b.left,b.bottom);ctx.lineTo((b.left+b.right)/2,b.top);ctx.lineTo(b.right,b.bottom);ctx.fill();ctx.strokeStyle='#ffda65';ctx.strokeRect(b.left,b.top,b.right-b.left,b.bottom-b.top);}
  ctx.restore();
}

function render(data) {
  latest=data;
  const t=data.telemetry;
  const stopped=data.run.status==='stopped';
  text('live-notice',stopped ? 'Körningen är stoppad. Bilden och värdena är den senaste sparade rapporten.' : 'Verkliga rapporter från Windows-datorn. Modellen körs lokalt och tränas inte av den här livekörningen.');
  text('live-mode',{preview:'BILDKONTROLL',probe:'HOPPMÄTNING',run:'PPO'}[data.run.mode]);
  text('live-model',data.run.model || 'Ingen PPO-styrning i detta läge');
  text('live-key',data.run.jumpKey === 'up' ? '↑' : 'SPACE');
  text('live-armed',t.armed ? 'Armerad' : 'Avstängd');
  text('live-count',`${t.validFrames} / ${t.frames}`);
  text('live-presses',t.presses);text('live-capture',ms(t.captureMs));text('live-pipeline',ms(t.pipelineMs));
  text('live-time',`${t.elapsedSeconds.toFixed(1)} s`);text('live-reason',t.reason);
  text('live-action',t.held ? 'Håll hopp' : 'Släppt');$('live-key').classList.toggle('active',t.held);
  const hasImage=typeof data.image==='string' && data.image.startsWith('data:image/jpeg;base64,');
  $('live-image').hidden=!hasImage;$('live-scene').hidden=hasImage;
  if(hasImage) $('live-image').src=data.image; else { $('live-image').removeAttribute('src');drawScene(data.scene); }
  $('live-empty').hidden=!!data.scene || hasImage;
  text('frame-label',hasImage ? 'Senaste beskurna spelbild · gula ramar visar upptäckten' : 'Upptäckta objekt från skärmbilder · schematisk visning');
  status();
}

async function refresh() {
  if(document.hidden) {setTimeout(refresh,2000);return;}
  try {
    const response=await fetch('/api/windows',{cache:'no-store',signal:AbortSignal.timeout(5000)});
    const data=await response.json();
    if(!response.ok) throw new Error(data.error || 'network');
    if(data.schemaVersion!==1 || data.source!=='geometry-dash-windows' || !data.telemetry || !data.run) throw new Error('invalid');
    networkError=false;render(data);
  } catch(error) {
    networkError=true;status();
    if(!latest) text('live-notice',error.message==='live_not_configured' ? 'Livekopplingen saknar Redis-inställningar på Vercel. Följ installationsguiden nedan.' : 'Ingen rapport har kommit från Windows-datorn ännu. Starta adaptern och kontrollera anslutningen.');
  } finally {setTimeout(refresh,2000);}
}
drawScene(null);refresh();setInterval(status,1000);
