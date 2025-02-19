/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_API_URL: 'http://localhost:9000',
    NEXT_PUBLIC_WS_URL: 'ws://localhost:9000/ws',
    NEXT_PUBLIC_FRONTEND_URL: 'http://localhost:3003'
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'Access-Control-Allow-Origin', value: '*' },
          { key: 'Access-Control-Allow-Methods', value: 'GET,POST,PUT,DELETE,OPTIONS' },
          { key: 'Access-Control-Allow-Headers', value: 'Content-Type, Authorization' },
          { key: 'Access-Control-Allow-Credentials', value: 'true' }
        ],
      },
      {
        source: '/ws',
        headers: [
          { key: 'Access-Control-Allow-Origin', value: '*' },
          { key: 'Access-Control-Allow-Methods', value: 'GET, OPTIONS' },
          { key: 'Access-Control-Allow-Headers', value: '*' },
          { key: 'Access-Control-Allow-Credentials', value: 'true' }
        ],
      }
    ]
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:9000/api/:path*'
      },
      {
        source: '/ws',
        destination: 'http://localhost:9000/ws'
      }
    ]
  }
}

module.exports = nextConfig
