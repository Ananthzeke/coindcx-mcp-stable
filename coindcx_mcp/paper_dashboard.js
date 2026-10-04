'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const number = (v, digits = 2) => Number(v).toLocaleString(undefined, {maximumFractionDigits: digits, minimumFractionDigits: digits});
  const price = v => number(v, v < 1 ? 6 : 2);
  const when = ms => ms == null ? 'Open' : new Date(ms).toLocaleString();
  const percent = v => `${number(v)}%`;
  let paused = false;
  const text = (id, value) => { $(id).textContent = value; };
  function cell(row, value, detail) {
    const td = document.createElement('td'); td.textContent = value;
    if (detail) { const small = document.createElement('small'); small.textContent = detail; td.append(small); }
    row.append(td); return td;
  }
  function table(id, rows, columns, draw) {
    $(id).replaceChildren();
    if (!rows.length) { const tr = document.createElement('tr'); const td = cell(tr, id === 'positions' ? 'No open paper positions' : id === 'trades' ? 'No paper trades yet' : 'No observations yet'); td.colSpan = columns; td.className = 'empty'; $(id).append(tr); return; }
    for (const item of rows) { const tr = document.createElement('tr'); draw(tr, item); $(id).append(tr); }
  }
  function chart(history) {
    const svg = $('chart'); svg.replaceChildren();
    const ns = 'http://www.w3.org/2000/svg';
    const node = (name, attrs, label) => { const n = document.createElementNS(ns, name); for (const [k,v] of Object.entries(attrs)) n.setAttribute(k,v); if (label) n.textContent=label; svg.append(n); return n; };
    if (!history.length) { node('text',{x:20,y:90},'Waiting for observations'); return; }
    const values = history.map(r => r.value), low = Math.min(...values), high = Math.max(...values);
    const spread = Math.max(high-low, 0.02);
    const y = value => 138 - (value-low)/spread*105;
    for (const v of [low, high]) { node('line',{x1:10,y1:y(v),x2:600,y2:y(v),stroke:'#edf1f7'}); node('text',{x:610,y:y(v)+4},number(v)); }
    node('polyline',{points:history.map((r,i)=>`${12+i/Math.max(history.length-1,1)*580},${y(r.value)}`).join(' '),fill:'none',stroke:'#657cdb','stroke-width':2.5});
    node('text',{x:12,y:171},new Date(history[0].timestamp_ms).toLocaleTimeString());
    node('text',{x:500,y:171},new Date(history.at(-1).timestamp_ms).toLocaleTimeString());
  }
  function render(data) {
    const a = data.account, s = data.settings, scores = data.scores;
    paused = data.paused;
    text('equity',number(a.equity)); text('equity-detail',`Started with ${number(s.initial_cash)} virtual USDT`);
    text('return',percent(data.return_percent)); $('return').className=`value ${data.return_percent >= 0 ? 'positive' : 'negative'}`;
    text('return-detail',`${a.positions.length} open paper positions · ${number(a.exposure)} USDT exposure`);
    text('drawdown',percent(data.max_drawdown_percent)); text('risk-detail',`New entries stop at ${s.max_drawdown_percent}% observed drawdown`);
    text('trade-count',data.closed_trades); text('win-rate',data.win_rate == null ? 'No completed trades yet' : `${percent(data.win_rate*100)} net profitable closed trades`);
    text('costs',`Fees paid: ${number(a.fees,4)} USDT · funding charged: ${number(a.funding,4)} USDT · equity includes estimated closing costs`);
    text('model-error',scores.model_mape == null ? 'Pending' : `${number(scores.model_mape,4)}%`); text('baseline-error',scores.baseline_mape == null ? 'Pending' : `${number(scores.baseline_mape,4)}%`);
    text('score-detail',`${scores.evaluated_windows} completed forecast windows${scores.direction_accuracy == null ? '' : ` · ${percent(scores.direction_accuracy*100)} terminal direction accuracy`} · overlapping windows`);
    text('settings',`${s.context} completed ${s.interval} candles → ${s.horizon} forecast candles · futures data`);
    text('cadence',`Checks every ${s.poll_seconds}s`);
    const errors = data.health.filter(h => h.error || data.now_ms-h.checked_ms > s.poll_seconds*3000);
    const stale = !data.health.length || data.health.some(h=>data.now_ms-h.checked_ms>s.poll_seconds*3000);
    text('status',`${stale ? 'Agent has not checked recently' : paused ? 'New paper entries paused; existing positions still monitored' : 'Paper agent observing futures'} · ${new Date(data.now_ms).toLocaleTimeString()}`);
    $('error').hidden=!errors.length; text('error',errors.map(h=>`${h.symbol}: ${h.error || 'No recent worker check'}`).join(' · '));
    text('pause',paused?'Resume new paper trades':'Pause new paper trades'); $('pause').disabled=false;
    table('signals',data.signals,6,(tr,r)=>{
      const h=data.health.find(x=>x.symbol===r.symbol);
      cell(tr,r.symbol.replace(/^B-/,'').replace('_',' / '),`Candle closed ${when(r.end_ms)}`);
      cell(tr,price(r.last_close));cell(tr,price(r.forecast.at(-1)));cell(tr,`${price(r.p10)} – ${price(r.p90)}`);
      cell(tr,r.direction===1?'Simulated long':r.direction===-1?'Simulated short':'Wait',r.reason);
      cell(tr,`${number(r.timing.inference_batch_ms,0)} ms / ${number(h?.cycle_ms || 0,0)} ms`,h?.cache_hit?'Latest check reused candles and forecast':'Latest check included fresh data');
    });
    table('positions',a.positions,6,(tr,r)=>{cell(tr,r.symbol);cell(tr,r.direction===1?'Long':'Short');cell(tr,price(r.entry));cell(tr,price(r.mark));cell(tr,number(r.unrealized_pnl,4));cell(tr,when(r.expiry_ms));});
    table('trades',data.trades,6,(tr,r)=>{cell(tr,r.symbol);cell(tr,r.direction===1?'Long':'Short');cell(tr,when(r.opened_ms));cell(tr,when(r.closed_ms));cell(tr,r.closed_ms==null?'Pending':number(r.net_pnl,4));cell(tr,r.reason||'Position remains open');});
    const assumptions=[['Account & sizing',`${s.initial_cash} virtual USDT · ${s.order_notional} USDT per entry · 1× exposure`],['Costs',`${s.fee_bps} bp fee / side · ${s.slippage_bps} bp slippage / side · observed bid/ask spread`],['Funding assumption',`${s.funding_bps_per_8h} bp charged at each UTC 8-hour boundary · estimated, not actual exchange funding`],['Entry rule',`${s.signal_bps} bp forecast threshold plus assumed round-trip costs · P10/P90 must support the direction`],['Exit rule',`${s.stop_percent}% observed stop · ${s.target_percent}% observed target · ${s.horizon} candle maximum hold`],['Data & timing','Public CoinDCX futures only · local TimesFM model · one forecast per new completed candle']];
    $('assumptions').replaceChildren(); for(const [title,value] of assumptions){const div=document.createElement('div'),strong=document.createElement('strong'),span=document.createElement('span');strong.textContent=title;span.textContent=value;span.className='detail';div.append(strong,span);$('assumptions').append(div);}
    chart(data.equity_history);
  }
  async function refresh(){
    try {const r=await fetch('/api/status',{signal:AbortSignal.timeout(5000)}); if(!r.ok)throw new Error('Paper status is unavailable');render(await r.json());}
    catch(e){$('error').hidden=false;text('error',`Cannot reach the paper agent: ${e.message}. No new observations are being shown.`);text('status','Connection unavailable');$('pause').disabled=true;}
    finally{setTimeout(refresh,5000);}
  }
  $('pause').addEventListener('click',async()=>{
    $('pause').disabled=true;
    try{const r=await fetch('/api/pause',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({paused:!paused})});if(!r.ok)throw new Error('Pause setting could not be updated'); const status=await fetch('/api/status');render(await status.json());}
    catch(e){$('error').hidden=false;text('error',e.message);$('pause').disabled=false;}
  });
  refresh();
})();
