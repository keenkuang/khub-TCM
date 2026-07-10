const app = getApp();
function request(method, path, data) {
  return new Promise((resolve, reject) => {
    const token = app.globalData.token;
    const header = { 'Content-Type': 'application/json' };
    if (token) header['Authorization'] = 'Bearer ' + token;
    wx.request({
      url: app.globalData.baseUrl + path, method, data,
      header,
      success: r => { if (r.statusCode >= 400) reject(r.data); else resolve(r.data); },
      fail: reject,
    });
  });
}
module.exports = {
  login: (u, p) => request('POST', '/auth/login', {username: u, password: p}),
  getAppointments: (params) => request('GET', '/ops/appointments?' + obj2params(params)),
  getTwin: (pid) => request('GET', '/twin/' + pid),
  getTrends: (pid) => request('GET', '/clinical/trends/' + pid),
  getConsultations: (pid) => request('GET', '/clinical/consultations?patient_id=' + pid),
  getPatients: () => request('GET', '/clinical/patients'),
};
function obj2params(o) { return Object.keys(o).map(k => k + '=' + encodeURIComponent(o[k])).join('&'); }
