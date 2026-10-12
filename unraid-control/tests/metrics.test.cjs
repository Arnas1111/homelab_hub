const {test} = require('node:test');
const assert = require('node:assert/strict');
const {memorySummary, cpuSeries} = require('../static/metrics.js');
test('memory bytes, percent and meter use total minus available, not cache-inclusive used', () => {
  const GiB = 1024**3;
  const summary = memorySummary({total:15.4*GiB, used:15.2*GiB, available:15.4*GiB*.648, percentTotal:35.2, buffcache:9*GiB}, [{size:16*GiB}]);
  assert.ok(Math.abs(summary.percentage-35.2)<1e-9);
  assert.ok(Math.abs(summary.used/GiB-5.4208)<1e-9);
  assert.equal(summary.installed,16*GiB);
  assert.equal(summary.available+summary.used,summary.total);
});
test('missing or invalid memory data does not become zero or include cache silently', () => {
  assert.equal(memorySummary().percentage,null);
  assert.equal(memorySummary({total:100, used:99}).used,null);
  assert.equal(memorySummary({total:100,available:101,percentTotal:20}).used,null);
  assert.equal(memorySummary({total:100,available:0}).percentage,100);
  assert.equal(memorySummary({total:100,percentTotal:20}).used,20);
  assert.equal(memorySummary({},[{size:null}]).installed,null);
  assert.equal(memorySummary({total:'100',available:'80'}).percentage,20);
});
test('CPU chart uses real timestamps, fixed percentage scale and separates sampling outages', () => {
  const series=cpuSeries([{stamp:700,value:0},{stamp:710,value:100},{stamp:710,value:90},{stamp:780,value:50},{stamp:1000,value:25},{stamp:699,value:5}],1000);
  assert.equal(series.count,4);
  assert.equal(series.segments.length,3);
  assert.equal(series.segments[0][0].x,40);
  assert.equal(series.segments[0][0].y,138);
  assert.equal(series.segments[0][1].y,12);
  assert.equal(series.latest.value,25);
});
test('constant CPU readings stay flat and a single real sample remains a point', () => {
  const series=cpuSeries([{stamp:990,value:25},{stamp:1000,value:25}],1000);
  assert.equal(series.segments[0][0].y,series.segments[0][1].y);
  assert.equal(cpuSeries([{stamp:1000,value:25}],1000).count,1);
  assert.equal(cpuSeries([{stamp:1000,value:null},{stamp:1000,value:NaN}],1000).count,0);
});
