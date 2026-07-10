const app = getApp();
Page({
  data: { isDoctor: false },
  onShow() {
    const user = app.globalData.user;
    if (!user) { wx.redirectTo({url: '/pages/login/login'}); return; }
    this.setData({isDoctor: user.role === 'doctor' || user.role === 'admin'});
  },
  goAppointments() { wx.navigateTo({url: '/pages/appointments/appointments'}); },
  goTwin() { wx.navigateTo({url: '/pages/twin/twin?pid=' + (app.globalData.user?.user_id || 0)}); },
  goTrends() { wx.navigateTo({url: '/pages/trends/trends?pid=' + (app.globalData.user?.user_id || 0)}); },
  goConsultations() { wx.navigateTo({url: '/pages/twin/twin?pid=' + (app.globalData.user?.user_id || 0)}); },
  goPatients() { wx.navigateTo({url: '/pages/appointments/appointments?mode=patients'}); },
  onLogout() { require('../../utils/auth').doLogout(); wx.redirectTo({url: '/pages/login/login'}); },
});
