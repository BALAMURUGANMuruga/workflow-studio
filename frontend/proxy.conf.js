const target = process.env.WORKFLOW_API_PROXY_TARGET || 'http://127.0.0.1:8000';

module.exports = {
  '/api': {
    target,
    secure: false,
    changeOrigin: true
  },
  '/operations-api/**': {
    target: 'http://127.0.0.1:9002',
    changeOrigin: true,
    ws: true,
    pathRewrite: { '^/operations-api': '' }
  },
  '/operations-workflows/api/ai/chat': {
    target: 'http://127.0.0.1:8081',
    changeOrigin: true,
    pathRewrite: { '^/operations-workflows': '' }
  },
  '/operations/**': {
    target: 'http://127.0.0.1:4300',
    changeOrigin: true
  }
};
