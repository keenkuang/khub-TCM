// charts.js - SVG 图表渲染
(function() {
'use strict';

// 调色板
const COLORS = ['#4e79a7','#f28e2b','#e15759','#76b7b2','#59a14f','#edc948','#b07aa1','#ff9da7','#9c755f','#bab0ac'];

function getColor(i) { return COLORS[i % COLORS.length]; }

/**
 * 渲染柱状图 SVG
 * @param {object} chartData - {labels: string[], datasets: [{label, data}]}
 * @param {HTMLElement} container - 挂载点
 */
window.renderBarChart = function(chartData, container) {
    if (!chartData || !chartData.labels || chartData.labels.length === 0) {
        container.innerHTML = '<div class="empty-chart">暂无数据</div>';
        return;
    }
    const w = Math.max(container.clientWidth || 400, 300);
    const h = 250;
    const pad = {top: 20, right: 20, bottom: 50, left: 50};
    const iw = w - pad.left - pad.right;
    const ih = h - pad.top - pad.bottom;
    
    const allValues = chartData.datasets.flatMap(d => d.data);
    const maxVal = Math.max(...allValues, 1);
    const barW = iw / chartData.labels.length * 0.6;
    const gapW = iw / chartData.labels.length * 0.4;
    
    let svg = `<svg width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg">
        <text x="${pad.left}" y="15" font-size="13" fill="#333">${chartData.datasets[0]?.label || ''}</text>`;
    
    chartData.labels.forEach((label, i) => {
        const x = pad.left + i * (barW + gapW) + gapW / 2;
        chartData.datasets.forEach((ds, di) => {
            const val = ds.data[i] || 0;
            const bh = (val / maxVal) * ih;
            const barX = x + di * (barW / chartData.datasets.length);
            svg += `<rect x="${barX}" y="${pad.top + ih - bh}" width="${barW / chartData.datasets.length - 1}" 
                height="${bh}" fill="${getColor(di)}" rx="2">
                <title>${label}: ${val}</title></rect>`;
        });
        svg += `<text x="${x + barW / 2}" y="${pad.top + ih + 16}" font-size="10" text-anchor="middle" 
            transform="rotate(-30,${x + barW / 2},${pad.top + ih + 16})">${label}</text>`;
    });
    
    // Y轴
    svg += `<line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${pad.top + ih}" stroke="#ccc"></line>`;
    for (let v = 0; v <= maxVal; v += Math.max(1, Math.ceil(maxVal / 5))) {
        const y = pad.top + ih - (v / maxVal) * ih;
        svg += `<text x="${pad.left - 5}" y="${y + 3}" font-size="10" text-anchor="end" fill="#666">${v}</text>`;
        svg += `<line x1="${pad.left}" y1="${y}" x2="${w - pad.right}" y2="${y}" stroke="#eee" stroke-dasharray="2,2"></line>`;
    }
    svg += '</svg>';
    container.innerHTML = svg;
};

/**
 * 渲染饼图 SVG
 */
window.renderPieChart = function(chartData, container) {
    if (!chartData || !chartData.labels || chartData.labels.length === 0) {
        container.innerHTML = '<div class="empty-chart">暂无数据</div>';
        return;
    }
    const w = 300, h = 300, cx = w/2, cy = h/2, r = 100;
    const ds = chartData.datasets[0];
    if (!ds) { container.innerHTML = '<div class="empty-chart">暂无数据</div>'; return; }
    const total = ds.data.reduce((a,b) => a + Math.abs(b), 0);
    if (total === 0) { container.innerHTML = '<div class="empty-chart">暂无数据</div>'; return; }
    
    let svg = `<svg width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg">`;
    let startAngle = -Math.PI / 2;
    ds.data.forEach((val, i) => {
        if (!val) return;
        const slice = (val / total) * Math.PI * 2;
        const endAngle = startAngle + slice;
        const x1 = cx + r * Math.cos(startAngle);
        const y1 = cy + r * Math.sin(startAngle);
        const x2 = cx + r * Math.cos(endAngle);
        const y2 = cy + r * Math.sin(endAngle);
        const large = slice > Math.PI ? 1 : 0;
        svg += `<path d="M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${large},1 ${x2},${y2} Z" 
            fill="${getColor(i)}" stroke="#fff" stroke-width="2">
            <title>${chartData.labels[i]}: ${val}</title></path>`;
        startAngle = endAngle;
    });
    // 图例
    const legendY = h - 30;
    const itemW = Math.min(120, (w - 20) / chartData.labels.length);
    chartData.labels.forEach((label, i) => {
        const lx = 10 + (i % 5) * itemW;
        const ly = legendY + Math.floor(i / 5) * 18;
        svg += `<rect x="${lx}" y="${ly - 10}" width="10" height="10" fill="${getColor(i)}" rx="1"></rect>`;
        svg += `<text x="${lx + 14}" y="${ly}" font-size="10" fill="#333">${label}</text>`;
    });
    svg += '</svg>';
    container.innerHTML = svg;
};

/**
 * 渲染折线图 SVG
 */
window.renderLineChart = function(chartData, container) {
    if (!chartData || !chartData.labels || chartData.labels.length === 0) {
        container.innerHTML = '<div class="empty-chart">暂无数据</div>';
        return;
    }
    const w = Math.max(container.clientWidth || 400, 300);
    const h = 250;
    const pad = {top: 20, right: 20, bottom: 40, left: 50};
    const iw = w - pad.left - pad.right;
    const ih = h - pad.top - pad.bottom;
    
    const allValues = chartData.datasets.flatMap(d => d.data);
    const maxVal = Math.max(...allValues, 1);
    const stepX = iw / Math.max(chartData.labels.length - 1, 1);
    
    let svg = `<svg width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg">`;
    
    chartData.datasets.forEach((ds, di) => {
        if (!ds.data.length) return;
        const points = ds.data.map((val, i) => ({
            x: pad.left + i * stepX,
            y: pad.top + ih - (val / maxVal) * ih
        }));
        
        // 填充区域
        let areaPath = `M${points[0].x},${pad.top + ih} L`;
        points.forEach(p => { areaPath += `${p.x},${p.y} L`; });
        areaPath += `${points[points.length-1].x},${pad.top + ih} Z`;
        svg += `<path d="${areaPath}" fill="${getColor(di)}" fill-opacity="0.1"></path>`;
        
        // 线条
        let linePath = `M${points[0].x},${points[0].y}`;
        points.slice(1).forEach(p => { linePath += ` L${p.x},${p.y}`; });
        svg += `<path d="${linePath}" fill="none" stroke="${getColor(di)}" stroke-width="2"></path>`;
        
        // 圆点
        points.forEach(p => {
            svg += `<circle cx="${p.x}" cy="${p.y}" r="3" fill="${getColor(di)}" stroke="#fff" stroke-width="1">
                <title>${chartData.labels[points.indexOf(p)]}: ${ds.data[points.indexOf(p)]}</title></circle>`;
        });
    });
    
    // X轴标签
    const labelStep = Math.max(1, Math.floor(chartData.labels.length / 10));
    chartData.labels.forEach((label, i) => {
        if (i % labelStep !== 0 && i !== chartData.labels.length - 1) return;
        svg += `<text x="${pad.left + i * stepX}" y="${pad.top + ih + 16}" font-size="10" text-anchor="middle" fill="#666">${label}</text>`;
    });
    
    svg += '</svg>';
    container.innerHTML = svg;
};

/**
 * 渲染表格
 */
window.renderTable = function(chartData, container) {
    if (!chartData || !chartData.rows || chartData.rows.length === 0) {
        container.innerHTML = '<div class="empty-chart">暂无数据</div>';
        return;
    }
    let html = '<table class="report-table"><thead><tr>';
    chartData.columns.forEach(c => { html += `<th>${c}</th>`; });
    html += '</tr></thead><tbody>';
    chartData.rows.forEach(r => {
        html += '<tr>';
        chartData.columns.forEach(c => { html += `<td>${r[c] !== null && r[c] !== undefined ? r[c] : ''}</td>`; });
        html += '</tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
};

/**
 * 根据 chart_type 自动选择渲染器
 */
window.renderChart = function(chartData, container) {
    if (!chartData) { container.innerHTML = '<div class="empty-chart">暂无数据</div>'; return; }
    const type = chartData.type || 'table';
    if (type === 'bar') window.renderBarChart(chartData, container);
    else if (type === 'pie') window.renderPieChart(chartData, container);
    else if (type === 'line') window.renderLineChart(chartData, container);
    else window.renderTable(chartData, container);
};

})();
