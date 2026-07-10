const api = require('../../utils/api');
const app = getApp();
Page({
  data: { list: [], loading: true },
  onLoad(opts) {
    const user = app.globalData.user;
    let query = {};
    if (opts.mode === 'patients') {
      api.getPatients().then(r => this.setData({list: r.patients||r, loading: false}));
    } else {
      if (user.role === 'patient' || user.role === 'guardian') query.patient_id = user.user_id;
      api.getAppointments(query).then(r => this.setData({list: r.appointments||r||[], loading: false}));
    }
  },
});
