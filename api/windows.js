import { handleWindows } from '../server/windows.mjs';
import { MAX_BYTES } from '../server/training.mjs';

export default async function handler(req, res) {
  res.setHeader('Cache-Control','no-store');
  res.setHeader('Content-Type','application/json');
  res.setHeader('Allow','GET, POST');
  if (Number(req.headers['content-length']) > MAX_BYTES) return res.status(413).json({error:'snapshot_too_large'});
  let body = '';
  if (req.method === 'POST') {
    if (req.body !== undefined) body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
    else for await (const chunk of req) {
      body += chunk.toString();
      if (Buffer.byteLength(body)>MAX_BYTES) return res.status(413).json({error:'snapshot_too_large'});
    }
  }
  const result = await handleWindows({method:req.method,authorization:req.headers.authorization,body});
  return res.status(result.status).json(result.body);
}
