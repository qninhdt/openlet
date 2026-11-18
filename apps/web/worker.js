export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/v1' || url.pathname.startsWith('/v1/')) {
      url.protocol = 'https:';
      url.host = 'openlet-api.qninhdt.com';
      const upstream = new Request(url, new Request(request, { redirect: 'manual' }));
      upstream.headers.set('Host', url.host);
      const response = await fetch(upstream);
      const headers = new Headers(response.headers);
      headers.set('Cache-Control', 'no-store');
      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers,
      });
    }
    const response = await env.ASSETS.fetch(request);
    if (!response.headers.get('Content-Type')?.includes('text/html')) return response;
    const headers = new Headers(response.headers);
    headers.set('Cache-Control', 'no-store');
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
