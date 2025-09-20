const http = require('http');
const fetch = require('node-fetch');  // 使用 node-fetch 替换 undici
const { Request, Response } = fetch;
const worker = require('./worker.js');

const server = http.createServer(async (req, res) => {
  try {
    // Construct the full URL
    const fullUrl = `http://${req.headers.host}${req.url}`;
    
    // Convert Node.js request body to a string for POST/PUT requests
    let body;
    if (req.method === 'POST' || req.method === 'PUT') {
      body = await new Promise((resolve) => {
        let data = '';
        req.on('data', chunk => data += chunk);
        req.on('end', () => resolve(data));
      });
    }

    // Create a Web API-compatible Request object
    const webRequest = new Request(fullUrl, {
      method: req.method,
      headers: req.headers,
      body: body || undefined,
    });

    // Call the worker's fetch handler
    const webResponse = await worker.default.fetch(webRequest, {}, {});

    // Convert Web API Response to Node.js response
    res.statusCode = webResponse.status;
    webResponse.headers.forEach((value, key) => {
      res.setHeader(key, value);
    });
    const responseText = await webResponse.text();
    res.end(responseText);
  } catch (error) {
    console.error('Server error:', error);
    res.statusCode = 500;
    res.end('Internal Server Error');
  }
});

server.listen(9321, '0.0.0.0', () => {
  console.log('Server running on http://0.0.0.0:9321');
});