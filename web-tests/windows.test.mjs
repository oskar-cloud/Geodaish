import test from 'node:test';
import assert from 'node:assert/strict';
import { handleWindows, validateWindows } from '../server/windows.mjs';
import { liveState } from '../web/windows-state.js';

const token='test-only-secret-at-least-32-characters';
const env={TRAINING_API_TOKEN:token,UPSTASH_REDIS_REST_URL:'https://example.upstash.io',UPSTASH_REDIS_REST_TOKEN:'test-redis'};
const report=()=>({schemaVersion:1,source:'geometry-dash-windows',
  run:{id:'test',label:'test run',startedAt:'2026-10-11T10:00:00Z',status:'running',mode:'run',model:'demo-normal.zip',jumpKey:'up'},
  telemetry:{sequence:1,updatedAt:'2026-10-11T10:00:01Z',elapsedSeconds:1,frames:20,validFrames:18,armed:true,held:true,presses:1,action:1,captureMs:20,pipelineMs:45,reason:'Armed'},
  scene:{width:1480,height:833,groundY:596,cube:{left:507,top:400,right:583,bottom:476},
    spikes:[{left:900,top:520,right:976,bottom:596}],observation:Array(16).fill(0),ready:true},image:null});

test('Windows live reports use separate persistent storage and discard unknown fields',async()=>{
  let stored;
  const fetcher=async(url,options)=>{
    const command=JSON.parse(options.body);
    assert.equal(command[command[0]==='GET'?1:3],'geodaish:windows:latest');
    if(command[0]==='EVAL') {stored=command.at(-1);return {ok:true,json:async()=>({result:1})};}
    return {ok:true,json:async()=>({result:stored})};
  };
  const body={...report(),token:'do not store'};
  body.run.localPath='private';body.scene.cube.private='private';
  assert.equal((await handleWindows({method:'POST',authorization:`Bearer ${token}`,body:JSON.stringify(body),env,fetcher})).status,200);
  const read=await handleWindows({method:'GET',env,fetcher});
  assert.equal(read.status,200);assert.equal(read.body.token,undefined);
  assert.equal(read.body.run.localPath,undefined);assert.equal(read.body.scene.cube.private,undefined);
});

test('Windows writes require auth; invalid data never reaches Redis',async()=>{
  const options={method:'POST',body:JSON.stringify(report()),env,fetcher:()=>assert.fail('storage called')};
  assert.equal((await handleWindows(options)).status,401);
  const bad=report();bad.scene.observation[3]=20;
  assert.equal((await handleWindows({...options,authorization:`Bearer ${token}`,body:JSON.stringify(bad)})).status,400);
  for(const image of ['https://tracking.example/image.jpg','data:image/svg+xml,<svg/>','data:image/jpeg;base64,!!!']) {
    assert.throws(()=>validateWindows({...report(),image}));
  }
  const missing=report();delete missing.scene;assert.throws(()=>validateWindows(missing));
});

test('stopped and stale game sessions cannot look live',()=>{
  const data=report(),now=Date.parse(data.telemetry.updatedAt);
  assert.equal(liveState(data,now).label,'STYR SPELET');
  assert.equal(liveState(data,now+7000).kind,'stale');
  assert.equal(liveState(data,now,true).kind,'stale');
  data.telemetry.armed=false;assert.equal(liveState(data,now).label,'FÖRHANDSVISNING');
  data.run.status='stopped';assert.equal(liveState(data,now+90000).label,'STOPPAD');
});

test('automatic retry remains visible and a stop always takes priority',()=>{
  const data=report(), now=Date.parse(data.telemetry.updatedAt);
  data.telemetry.armed=false; data.telemetry.held=false; data.telemetry.waitingForRetry=true;
  assert.equal(validateWindows(data).telemetry.waitingForRetry,true);
  assert.equal(liveState(data,now).label,'VÄNTAR PÅ NYTT FÖRSÖK');
  assert.equal(liveState(data,now+7000).kind,'stale');
  data.run.status='stopped';
  assert.equal(liveState(data,now).label,'STOPPAD');
  data.telemetry.waitingForRetry='true';
  assert.throws(()=>validateWindows(data));
  assert.equal(validateWindows(report()).telemetry.waitingForRetry,false);
});
