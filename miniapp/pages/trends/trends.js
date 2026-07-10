const api = require('../../utils/api');
Page({
  data: { constitution: {}, evolution: [], treatments: [], loading: true },
  onLoad(opts) {
    const pid = opts.pid || getApp().globalData.user?.user_id || 0;
    api.getTrends(pid).then(r => {
      const t = r.trends || r;
      this.setData({
        constitution: t.body_constitution || {},
        evolution: t.syndrome_evolution || [],
        treatments: t.treatment_sequence || [],
        loading: false,
      });
    });
  },
});
