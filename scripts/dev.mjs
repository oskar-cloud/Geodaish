import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const folder = resolve(root, process.argv.includes('--production') ? 'dist' : 'web');
const port = Number(process.env.PORT || 5173);
const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png' };

http.createServer(async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'GET') { res.writeHead(405); res.end(); return; }
  try {
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    if (pathname === '/api/training' || pathname === '/api/windows') {
      try {
        const data = await readFile(resolve(root, pathname === '/api/windows' ? 'runs/windows-live.json' : 'runs/live.json'));
        res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(data);
      } catch {
        res.writeHead(404, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'no_training_yet' }));
      }
      return;
    }
    const path = resolve(folder, `.${pathname === '/' ? '/index.html' : pathname}`);
    if (!path.startsWith(folder + sep)) { res.writeHead(403); res.end(); return; }
    const file = await readFile(path);
    res.writeHead(200, { 'Content-Type': types[extname(path)] || 'application/octet-stream' });
    res.end(file);
  } catch { res.writeHead(404); res.end('Not found'); }
}).listen(port, '127.0.0.1', () => console.log(`Geodaish dashboard: http://127.0.0.1:${port}`));
