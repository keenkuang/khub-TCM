const auth = require('../../utils/auth');
Page({
  data: { username: '', password: '', error: '' },
  onUsername(e) { this.setData({username: e.detail.value}); },
  onPassword(e) { this.setData({password: e.detail.value}); },
  onLogin() {
    const { username, password } = this.data;
    if (!username || !password) { this.setData({error: '请输入用户名和密码'}); return; }
    wx.showLoading({title: '登录中'});
    auth.doLogin(username, password).then(() => {
      wx.hideLoading();
      wx.redirectTo({url: '/pages/index/index'});
    }).catch(e => {
      wx.hideLoading();
      this.setData({error: (e.error || '登录失败')});
    });
  },
});
