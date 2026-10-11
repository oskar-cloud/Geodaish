export function liveState(data, now=Date.now(), error=false) {
  if (!data) return {label:'VÄNTAR PÅ DATORN',kind:'stale'};
  if (data.run.status === 'stopped') return {label:'STOPPAD',kind:'stopped'};
  if (error || now-Date.parse(data.telemetry.updatedAt)>6000) return {label:'KONTAKT SAKNAS',kind:'stale'};
  if (data.telemetry.waitingForRetry) return {label:'VÄNTAR PÅ NYTT FÖRSÖK',kind:'live'};
  return {label:data.telemetry.armed ? 'STYR SPELET' : 'FÖRHANDSVISNING',kind:'live'};
}
