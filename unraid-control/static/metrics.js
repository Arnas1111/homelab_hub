/* Pure metric calculations shared by the browser and regression checks. */
(function(root) {
  const number = value => value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
  function memorySummary(memory = {}, layout = []) {
    const total = number(memory.total), available = number(memory.available), reported = number(memory.percentTotal);
    let used = null, percentage = null, remaining = null;
    if (total > 0 && available !== null && available >= 0 && available <= total) {
      used = total - available; remaining = available; percentage = used / total * 100;
    } else if (total > 0 && available === null && reported !== null && reported >= 0 && reported <= 100) {
      used = total * reported / 100; remaining = total - used; percentage = reported;
    }
    const sizes = layout.map(dim => number(dim.size));
    const installed = sizes.length && sizes.every(size => size !== null && size >= 0) ? sizes.reduce((a,b) => a+b,0) || null : null;
    const cache = number(memory.buffcache);
    return {total:total > 0 ? total : null, used, available:remaining, percentage, installed,
      cache:cache !== null && cache >= 0 ? cache : null};
  }
  function cpuSeries(readings, now, windowSeconds = 300) {
    const points = readings.map(point => ({stamp:number(point.stamp), value:number(point.value)}))
      .filter(point => point.stamp !== null && point.value !== null && point.value >= 0 && point.value <= 100 && point.stamp >= now-windowSeconds && point.stamp <= now+2)
      .sort((a,b) => a.stamp-b.stamp);
    const unique = points.filter((point,index) => index === 0 || point.stamp !== points[index-1].stamp);
    const segments = [];
    for (const point of unique) {
      if (!segments.length || point.stamp - segments.at(-1).at(-1).stamp > 30) segments.push([]);
      segments.at(-1).push({...point, x:40+(point.stamp-(now-windowSeconds))/windowSeconds*700, y:12+(100-point.value)/100*126});
    }
    return {segments, count:unique.length, latest:unique.at(-1) || null};
  }
  const api = {number, memorySummary, cpuSeries};
  root.ControlMetrics = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
