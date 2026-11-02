// 公开展示配置。请勿填写密钥、账户信息或其他私人内容。
export default Object.freeze({
  symbol: 'ZEC-USDT-SWAP',
  startDate: '2026-11-02', // DAY 1；以 UTC+7 日界递增。
  offlineMinutes: 15, // 超时阈值（分钟）：快照过期则离线，团队状态过期则待命。
  wsMaxFailures: 4, // 连续失败后回退公共 REST 轮询。
  newsNote: '', // 人工更新的新闻政策备注；空值显示“暂无人工备注”。
});
