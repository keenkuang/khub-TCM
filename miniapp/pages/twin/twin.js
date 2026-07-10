const api = require('../../utils/api');
Page({
  data: { summary: '', timeline: [], loading: true },
  onLoad(opts) {
    const pid = opts.pid || getApp().globalData.user?.user_id || 0;
    api.getTwin(pid).then(r => {
      this.setData({summary: r.summary||'', timeline: r.timeline||[], loading: false});
    });
  },
});
