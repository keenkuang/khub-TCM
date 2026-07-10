const api = require('./api');
function doLogin(username, password) {
  return api.login(username, password).then(data => {
    const app = getApp();
    app.globalData.token = data.token;
    app.globalData.user = data.user;
    wx.setStorageSync('khub_token', data.token);
    wx.setStorageSync('khub_user', data.user);
    return data;
  });
}
function doLogout() {
  wx.removeStorageSync('khub_token');
  wx.removeStorageSync('khub_user');
  getApp().globalData.token = '';
  getApp().globalData.user = null;
}
module.exports = { doLogin, doLogout };
