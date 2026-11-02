import { coinIcons } from './coins/manifest.mjs';
export function coinIdentity(symbol) {
  const name=String(symbol ?? '').split('-')[0].toUpperCase();
  const safe=/^[A-Z0-9]+$/.test(name)?name:'?';
  let hash=0;for(const letter of safe)hash=(hash*31+letter.charCodeAt(0))>>>0;
  return {symbol:safe,initial:safe[0],hue:hash%360,path:coinIcons.has(safe.toLowerCase())?`./assets/coins/${safe.toLowerCase()}.svg`:null};
}
export function coinIcon(symbol) {
  const c=coinIdentity(symbol);
  return `<span class="coin-icon" aria-hidden="true" style="--coin-hue:${c.hue}"><span>${c.initial}</span>${c.path?`<img src="${c.path}" alt="" width="26" height="26" loading="lazy" decoding="async">`:''}</span>`;
}
// A failed local asset exposes the initials underneath without layout changes.
if(typeof document!=='undefined')document.addEventListener('error',event=>{
  if(event.target.matches?.('.coin-icon img'))event.target.remove();
},true);
