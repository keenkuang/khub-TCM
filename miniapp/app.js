App({
  globalData: { token: '', user: null, baseUrl: 'http://127.0.0.1:8765' },
  onLaunch() {
    const token = wx.getStorageSync('khub_token');
    const user = wx.getStorageSync('khub_user');
    if (token) { this.globalData.token = token; this.globalData.user = user; }
  }
});
