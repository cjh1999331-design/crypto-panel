export const ROLES = { umi: 'umi 主席', tech: '技术', industry: '行业', news: '新闻政策', risk: '风控', trader: '操盘' };
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' })[c]);
const statuses = { '工作中':'working', '已完成':'done', '待命':'idle' };
const format = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Bangkok', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false});
export const teamTime = ts => Number.isFinite(Date.parse(ts)) ? format.format(Date.parse(ts)) + ' UTC+7' : '—';
export function validTeam(data) {
  const timestamp = ts => typeof ts === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(ts) && Number.isFinite(Date.parse(ts));
  const report = r => r && timestamp(r.ts) && typeof r.title === 'string' && Array.from(r.title).length <= 40 && typeof r.summary === 'string' && Array.from(r.summary).length <= 200 && (r.grade === null || /^[A-F]$/.test(r.grade));
  return data?.schema_version === 1 && data.status && typeof data.status.roles === 'object' && data.status.roles !== null && !Array.isArray(data.status.roles) &&
    Object.entries(data.status.roles).every(([role,r]) => Object.hasOwn(ROLES, role) && r && Object.hasOwn(statuses,r.status) && typeof r.task === 'string' && (r.last_report === null || report(r.last_report))) &&
    Array.isArray(data.log) && data.log.length <= 200 && data.log.every(r => report(r) && Object.hasOwn(ROLES,r.role) && /^P[0-7]$/.test(r.phase) && Object.hasOwn(statuses,r.status) && typeof r.meeting === 'string');
}
export function gradeMarkup(grade, large=false) {
  const value = /^[A-F]$/.test(grade) ? grade : '—';
  const tone = /[AB]/.test(value) ? 'grade-good' : value === 'C' ? 'grade-mid' : /[DEF]/.test(value) ? 'grade-bad' : 'grade-none';
  return `<strong class="team-grade ${tone}${large ? ' grade-large' : ''}" aria-label="评级 ${value}">${value}</strong>`;
}
export const CODES = {umi:'UMI',tech:'TECH',industry:'INDUSTRY',news:'NEWS',risk:'RISK',trader:'TRADER'};
export const ROLE_COLORS = {umi:'#eaeede',tech:'#74c5ff',industry:'#ccadff',news:'#ff88bb',risk:'#ffca6c',trader:'#b6ff3b'};
export function pixelRobot(role) {
  const heads = {
    umi:'M6 3h8v2h2v8H4V5h2z', tech:'M5 4h10v2h2v6H3V6h2z',
    industry:'M7 2h6v2h2v2h2v7H3V6h2V4h2z',news:'M9 2h2v2h2v2h2v2h2v5H3V8h2V6h2V4h2z',
    risk:'M7 2h6v2h3v8h-3v2H7v-2H4V4h3z',trader:'M4 4h12v8h-2v2H6v-2H4z'
  };
  return `<svg class="pixel-robot" viewBox="0 0 20 20" shape-rendering="crispEdges" aria-hidden="true"><path fill="currentColor" d="${heads[role] || heads.umi}"/><path fill="#080c0a" d="M6 7h2v3H6zm6 0h2v3h-2z"/><path fill="currentColor" d="M6 15h8v2h2v2h-4v-2H8v2H4v-2h2z"/>${role==='umi'?'<path fill="#b6ff3b" d="M6 1h2v1h4V1h2v2H6z"/>':''}</svg>`;
}
export function teamCards(data, details={}) {
  return Object.entries(ROLES).map(([role,name]) => {
    const state = data?.status?.roles?.[role];
    const latest = (data?.log || []).filter(r => r.role === role).sort((a,b) => Date.parse(b.ts)-Date.parse(a.ts))[0];
    const report = [state?.last_report, latest].filter(Boolean).sort((a,b) => Date.parse(b.ts)-Date.parse(a.ts))[0];
    const status = state?.status || latest?.status || '待命';
    return `<article class="role-card team-card" data-role="${role}" style="--role-color:${ROLE_COLORS[role]}"><div class="role-title">${pixelRobot(role)}<div><h2>${CODES[role]}</h2><span class="role-name">${name}</span></div><span class="team-badge ${statuses[status] || 'idle'}">${esc(status)}</span></div><p class="team-task" title="${esc(state?.task || '')}">${esc(state?.task || report?.title || '暂无任务')}</p>${details[role] ? `<p class="role-detail team-metric">${esc(details[role])}</p>` : `<p class="role-detail metric-placeholder">最新评级 ${esc(report?.grade || '—')}</p>`}<details class="team-report-fold"><summary>报告 ${gradeMarkup(report?.grade)}</summary><div class="team-report"><div><p class="team-report-title">${esc(report?.title || '暂无报告')}</p><p class="team-summary">${esc(report?.summary || '暂无')}</p></div></div><time class="team-time" datetime="${esc(report?.ts || '')}">${teamTime(report?.ts)}</time></details></article>`;
  }).join('');
}
export function workstationMarkup(data, roles) {
  return roles.map(role=>{
    const status=data?.status?.roles?.[role]?.status || '待命';
    return `<div class="workstation" style="--role-color:${ROLE_COLORS[role]}"><div class="desk-screen"><span>${CODES[role]}</span><span class="screen-grid" aria-hidden="true"></span></div><div class="desk-surface">${pixelRobot(role)}<span class="desk-keyboard" aria-hidden="true"></span></div><div class="desk-label"><span>${ROLES[role]}</span><span class="station-status ${statuses[status]}"><i></i>${esc(status)}</span></div></div>`;
  }).join('');
}
export function filteredLogs(data, role='', meeting='') {
  return (data?.log || []).filter(r => (!role || r.role === role) && (!meeting || r.meeting === meeting)).sort((a,b) => Date.parse(b.ts)-Date.parse(a.ts));
}
export function timelineMarkup(data, role='', meeting='') {
  const rows = filteredLogs(data,role,meeting);
  return rows.length ? rows.map(r => `<li class="team-entry"><div class="team-entry-meta"><time datetime="${esc(r.ts)}">${teamTime(r.ts)}</time><span>${ROLES[r.role]}</span><span class="pill">${esc(r.phase)}</span><span class="team-meeting">${esc(r.meeting)}</span></div><div class="team-entry-body"><div><h3>${esc(r.title)}</h3><p>${esc(r.summary)}</p></div>${gradeMarkup(r.grade)}</div></li>`).join('') : '<li class="empty">暂无记录</li>';
}
