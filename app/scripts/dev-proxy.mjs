// Web-preview only: beta.fiftyoff.app sends no CORS headers, so `expo start --web` on localhost can't call it.
// This forwards /api/v1/* to the API and adds CORS. The phone (Expo Go) calls the API directly and doesn't need it.
//   node scripts/dev-proxy.mjs  then  EXPO_PUBLIC_API_BASE=http://localhost:8787/api/v1 npx expo start --web
import http from 'node:http';

const TARGET = process.env.API_TARGET ?? 'https://beta.fiftyoff.app';
const PORT = Number(process.env.PORT ?? 8787);

http
  .createServer(async (req, res) => {
    const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Content-Type, Authorization', 'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS' };
    if (req.method === 'OPTIONS') return res.writeHead(204, cors).end();
    if (!req.url?.startsWith('/api/v1/')) return res.writeHead(404, cors).end();
    try {
      const body = req.method === 'GET' ? undefined : await new Response(req).arrayBuffer();
      const r = await fetch(TARGET + req.url, { method: req.method, headers: { 'Content-Type': req.headers['content-type'] ?? 'application/json' }, body });
      res.writeHead(r.status, { ...cors, 'Content-Type': r.headers.get('content-type') ?? 'application/json' });
      res.end(Buffer.from(await r.arrayBuffer()));
    } catch (e) {
      res.writeHead(502, cors).end(String(e));
    }
  })
  .listen(PORT, () => console.log(`dev proxy :${PORT} -> ${TARGET}`));
