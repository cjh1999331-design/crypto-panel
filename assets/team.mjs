import { roleState, animationClasses } from './state.mjs';
export const ROLES = { umi: 'umi 主席', tech: '技术', industry: '行业', news: '新闻政策', risk: '风控', trader: '操盘' };
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' })[c]);
const statuses = { '工作中':'working', '已完成':'done', '待命':'idle', '离线':'offline' };
const format = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Bangkok', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false});
export const teamTime = ts => Number.isFinite(Date.parse(ts)) ? format.format(Date.parse(ts)) + ' UTC+7' : '—';
export function validTeam(data) {
  const timestamp = ts => typeof ts === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(ts) && Number.isFinite(Date.parse(ts));
  const report = r => r && timestamp(r.ts) && typeof r.title === 'string' && Array.from(r.title).length <= 40 && typeof r.summary === 'string' && Array.from(r.summary).length <= 200 && (r.grade === null || /^[A-F][+-]?$/.test(r.grade));
  return data?.schema_version === 1 && data.status && typeof data.status.roles === 'object' && data.status.roles !== null && !Array.isArray(data.status.roles) &&
    Object.entries(data.status.roles).every(([role,r]) => Object.hasOwn(ROLES, role) && r && Object.hasOwn(statuses,r.status) && typeof r.task === 'string' && (r.last_report === null || report(r.last_report))) &&
    Array.isArray(data.log) && data.log.length <= 200 && data.log.every(r => report(r) && Object.hasOwn(ROLES,r.role) && /^P[0-7]$/.test(r.phase) && Object.hasOwn(statuses,r.status) && typeof r.meeting === 'string');
}
export function gradeMarkup(grade, large=false) {
  const value = /^[A-F][+-]?$/.test(grade) ? grade : '—';
  const tone = /[AB]/.test(value) ? 'grade-good' : value[0] === 'C' ? 'grade-mid' : /[DEF]/.test(value) ? 'grade-bad' : 'grade-none';
  return `<strong class="team-grade ${tone}${large ? ' grade-large' : ''}" aria-label="评级 ${value}">${value}</strong>`;
}
export const CODES = {umi:'UMI',tech:'TECH',industry:'INDUSTRY',news:'NEWS',risk:'RISK',trader:'TRADER'};
export const ROLE_COLORS = {umi:'#22d3ee',tech:'#60a5fa',industry:'#34d399',news:'#fbbf24',risk:'#fb7185',trader:'#ec4899'};
export function robotSVG(role) {
  const accessories={
    umi:'<path d="m40 28-6-16 13 7 9-14 9 14 13-7-6 16Z" fill="#f5cf75" stroke="#fff0b1" stroke-width="2"/><circle cx="56" cy="17" r="3" fill="white"/>',
    tech:'<g fill="none" stroke="#a5d6ff" stroke-width="3"><rect x="28" y="43" width="24" height="18" rx="7"/><rect x="60" y="43" width="24" height="18" rx="7"/><path d="M52 49h8"/></g>',
    industry:'<path d="M56 31V17" stroke="currentColor" stroke-width="4"/><g stroke="#c8ffe9" fill="#168566" stroke-width="1.5"><circle cx="56" cy="13" r="11"/><ellipse cx="56" cy="13" rx="5" ry="11"/><path d="M45 13h22M48 7h16M48 19h16"/></g>',
    news:'<g transform="rotate(13 86 84)"><rect x="76" y="75" width="9" height="27" rx="4" fill="#c7b895"/><rect x="71" y="65" width="19" height="19" rx="9" fill="#ffe6a8" stroke="#b4893e" stroke-width="2"/><path d="M76 71h9m-9 4h9" stroke="#94631d"/></g>',
    risk:'<path d="m56 76 18 6-3 18-15 10-15-10-3-18Z" fill="#9c2848" stroke="#ffa3b5" stroke-width="2"/><path d="m47 90 6 6 12-13" fill="none" stroke="#ffdfdf" stroke-width="3"/>',
    trader:'<path d="M23 52V43a33 30 0 0 1 66 0v15" fill="none" stroke="#ffc0ee" stroke-width="5"/><rect x="19" y="43" width="12" height="22" rx="6" fill="#ca438f"/><rect x="81" y="43" width="12" height="22" rx="6" fill="#ca438f"/><path d="M86 63q0 10-16 10" fill="none" stroke="#ffc0ee" stroke-width="3"/><circle cx="68" cy="73" r="4" fill="#ffc0ee"/>'
  };
  return `<svg class="robot" viewBox="0 0 112 140" role="img" aria-label="${ROLES[role]}机器人"><defs><linearGradient id="shell-${role}" x2="1" y2="1"><stop stop-color="#e6f7ff"/><stop offset=".4" stop-color="currentColor"/><stop offset="1" stop-color="#172546"/></linearGradient><clipPath id="screen-${role}"><rect x="26" y="102" width="60" height="27" rx="6"/></clipPath></defs><ellipse class="robot-shadow" cx="56" cy="132" rx="35" ry="4" fill="currentColor" opacity=".16"/><g class="robot-body"><g class="robot-legs" fill="#a2b9d3"><rect x="38" y="106" width="12" height="18" rx="6"/><rect x="62" y="106" width="12" height="18" rx="6"/></g><rect x="32" y="74" width="48" height="40" rx="19" fill="url(#shell-${role})" stroke="#ffffff55"/><circle cx="56" cy="89" r="6" fill="currentColor" stroke="#e4ffff"/><g class="robot-head"><rect x="22" y="29" width="68" height="43" rx="20" fill="url(#shell-${role})" stroke="#ffffff77" stroke-width="1.5"/><rect x="29" y="36" width="54" height="29" rx="13" fill="#0c1834"/><g class="robot-eyes" fill="currentColor"><rect x="38" y="44" width="7" height="12" rx="3.5"/><rect x="67" y="44" width="7" height="12" rx="3.5"/></g><path d="M51 56q5 4 10 0" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>${accessories[role] || ''}</g><g class="robot-arm arm-left"><rect x="21" y="79" width="13" height="27" rx="6.5" fill="url(#shell-${role})"/><circle cx="28" cy="105" r="7" fill="#c3e5f1"/></g><g class="robot-arm arm-right"><rect x="78" y="79" width="13" height="27" rx="6.5" fill="url(#shell-${role})"/><circle cx="84" cy="105" r="7" fill="#c3e5f1"/></g>${role==='news'?'<g fill="#fff1c5" stroke="#b99450"><rect x="38" y="86" width="32" height="23" rx="3"/><path d="M43 92h22m-22 5h8m4 0h10m-22 5h22"/></g>':''}<g class="report-file"><rect x="76" y="61" width="18" height="23" rx="3" fill="#e6f7ff"/><path d="M80 68h10m-10 5h10m-10 5h7" stroke="currentColor" stroke-width="2"/></g></g><g class="robot-screen"><rect x="26" y="102" width="60" height="27" rx="6" fill="#10233c" stroke="currentColor" opacity=".95"/><path d="m33 120 8-6 8 3 9-8 10 6 11-6" fill="none" stroke="currentColor" stroke-width="2"/><g clip-path="url(#screen-${role})"><path class="screen-shine" d="m10 98 10 0 35 34H45Z" fill="#fff" opacity=".25"/></g></g><g class="warning-sign"><path d="M58 83v42" stroke="#fdd4dd" stroke-width="3"/><rect x="33" y="68" width="50" height="26" rx="7" fill="#72243e" stroke="#ff96ae"/><text class="warning-label" x="58" y="86" text-anchor="middle" fill="#fff" font-size="13">止损</text></g><text class="robot-zzz" x="78" y="25" fill="#a8b0c7" font-size="17">zzz</text></svg>`;
}
export function teamCards(data, details={}, options={}) {
  return Object.entries(ROLES).map(([role,name]) => {
    const state = data?.status?.roles?.[role];
    const latest = (data?.log || []).filter(r => r.role === role).sort((a,b) => Date.parse(b.ts)-Date.parse(a.ts))[0];
    const report = [state?.last_report, latest].filter(Boolean).sort((a,b) => Date.parse(b.ts)-Date.parse(a.ts))[0];
    const resolved=roleState(data,role,options), motion=animationClasses(resolved.state,options);
    return `<article class="role-card team-card state-${resolved.state} ${motion}" data-role="${role}" style="--role-color:${ROLE_COLORS[role]}"><div class="role-title"><div><span class="role-code">${CODES[role]}</span><h2>${name}</h2></div><span class="team-badge ${resolved.state}">${resolved.state==='done'?'✓ ':''}${resolved.status}${resolved.state==='working'?'<span class="typing-dots"><i></i><i></i><i></i></span>':''}</span></div><div class="robot-stage"><div class="avatar-halo"></div>${robotSVG(role)}</div><p class="team-task" title="${esc(resolved.reason)}">${esc(resolved.state==='offline'?resolved.reason:state?.task || '暂无任务')}</p><p class="role-detail team-metric">${esc(details[role] || '最新评级 '+(report?.grade || '—'))}</p><div class="report-heading"><span>最新报告</span>${gradeMarkup(report?.grade)}</div><p class="team-report-title">${esc(report?.title || '暂无报告')}</p><p class="team-summary">${esc(report?.summary || '暂无报告数据')}</p><time class="team-time" datetime="${esc(report?.ts || '')}">${teamTime(report?.ts)}</time></article>`;
  }).join('');
}
export function filteredLogs(data, role='', meeting='') {
  return (data?.log || []).filter(r => (!role || r.role === role) && (!meeting || r.meeting === meeting)).sort((a,b) => Date.parse(b.ts)-Date.parse(a.ts));
}
export function timelineMarkup(data, role='', meeting='') {
  const rows = filteredLogs(data,role,meeting);
  return rows.length ? rows.map(r => `<li class="team-entry"><div class="team-entry-meta"><time datetime="${esc(r.ts)}">${teamTime(r.ts)}</time><span>${ROLES[r.role]}</span><span class="pill">${esc(r.phase)}</span><span class="team-meeting">${esc(r.meeting)}</span></div><div class="team-entry-body"><div><h3>${esc(r.title)}</h3><p>${esc(r.summary)}</p></div>${gradeMarkup(r.grade)}</div></li>`).join('') : '<li class="empty">暂无记录</li>';
}
