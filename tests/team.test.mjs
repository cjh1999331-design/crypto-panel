import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { ROLES, validTeam, teamCards as cards, teamTime, filteredLogs, timelineMarkup, gradeMarkup } from '../assets/team.mjs';
const data = JSON.parse(execFileSync('python3',['-c', `import sys,json;sys.path.insert(0,'tools');from make_snapshot import build_team;print(json.dumps(build_team('tests/fixtures/team')))`],{encoding:'utf8'}));
data.generated_at=data.status.updated_at;
const teamCards=(d,details)=>cards(d,details,{now:Date.parse(data.status.updated_at),snapshotAt:data.status.updated_at});
test('成员白名单只包含 gork、claude、Codex、Grok，历史角色与 umi 不出现在卡片或时间线',()=>{
  assert.deepEqual(Object.keys(ROLES),['gork','claude','codex','grok']);
  assert.deepEqual(Object.values(ROLES),['gork 总指挥','claude','Codex','Grok']);
  const legacy=['umi','tech','industry','news','risk','trader'];
  const mixed=structuredClone(data);
  for(const role of legacy){
    mixed.status.roles[role]={status:'工作中',task:'旧成员任务',last_report:null};
    mixed.log.push({...data.log[0],role,title:'旧成员报告'});
  }
  const html=teamCards(mixed);
  assert.doesNotMatch(html,/旧成员|umi 主席|data-role="(?:umi|tech|industry|news|risk|trader)"/);
  assert.match(html,/data-role="gork"/);
  assert.match(html,/data-role="claude"/);
  assert.doesNotMatch(timelineMarkup(mixed),/旧成员报告|undefined|umi 主席/);
  assert.equal(filteredLogs(mixed).length,data.log.length);
});
test('快照新鲜、团队空数据：四张待命卡、无评级、暂无记录', () => {
  const empty = {schema_version:1,status:{roles:{}},log:[]};
  assert.equal(validTeam(empty),true);
  const cards=teamCards(empty);
  assert.equal((cards.match(/class="role-card/g)||[]).length,4);
  for (const name of Object.values(ROLES)) assert.ok(cards.includes(name));
  assert.equal((cards.match(/>待命</g)||[]).length,4);
  assert.equal((cards.match(/state-idle motion-idle/g)||[]).length,4);
  assert.doesNotMatch(cards,/state-offline|超过 .* 分钟未更新|umi/);
  assert.equal((cards.match(/grade-none/g)||[]).length,4);
  assert.match(timelineMarkup(empty),/暂无记录/);
  assert.equal(teamTime(null),'—');
});
test('团队示例：评级颜色、UTC+7、摘要和当前任务', () => {
  assert.equal(validTeam(data),true);
  const cards=teamCards(data,{codex:'六条件 4/6'});
  assert.match(cards,/工作中/);assert.match(cards,/已完成/);assert.match(cards,/待命/);
  assert.match(cards,/六条件 4\/6/);assert.match(cards,/审查代码与硬风控改动/);
  assert.match(teamTime('2026-11-02T13:35:00Z'),/20:35 UTC\+7/);
  for(const grade of ['A','B']) assert.match(gradeMarkup(grade),/grade-good/);
  assert.match(gradeMarkup('C'),/grade-mid/);
  for(const grade of ['D','E','F']) assert.match(gradeMarkup(grade),/grade-bad/);
  assert.match(gradeMarkup(null),/grade-none.*—/);
  const timeline=timelineMarkup(data);
  assert.match(timeline,/政策消息整理/);assert.match(timeline,/P7|P6/);
  assert.doesNotMatch(timeline,/umi/);
});
test('角色和会议筛选可组合，结果倒序，筛空显示暂无记录', () => {
  assert.equal(filteredLogs(data).length,9);
  assert.equal(filteredLogs(data,'codex').length,2);
  assert.equal(filteredLogs(data,'gork').length,2);
  assert.equal(filteredLogs(data,'claude').length,1);
  assert.equal(filteredLogs(data,'codex','示例会议乙').length,1);
  assert.match(timelineMarkup(data,'claude','示例会议乙'),/暂无记录/);
  const rows=filteredLogs({...data,log:[...data.log].reverse()});
  assert.ok(rows.every((r,i)=>!i||Date.parse(rows[i-1].ts)>=Date.parse(r.ts)));
});
test('所有文本转义，最新日志优先于较旧的状态报告，不接受非法团队结构', () => {
  const special='<img src=x onerror=alert(1)>';
  const changed=structuredClone(data);changed.status.roles.codex.task=special;
  changed.status.roles.codex.last_report=null;
  changed.log[1].title=special;changed.log[1].summary=special;changed.log[1].meeting=special;
  assert.ok(!teamCards(changed,{codex:special}).includes('<img'));
  assert.ok(!timelineMarkup(changed).includes('<img'));
  changed.status.roles.codex.last_report={...changed.log[1],ts:'2026-11-01T00:00:00Z',title:'过期报告'};
  assert.ok(!teamCards(changed).includes('过期报告'));
  assert.equal(validTeam({...data,log:[{...data.log[0],role:'bad'}]}),false);
  assert.equal(validTeam({...data,log:[{...data.log[0],role:'umi'}]}),false);
  assert.equal(validTeam({...data,log:[{...data.log[0],grade:'G'}]}),false);
  assert.equal(validTeam({...data,log:[{...data.log[0],ts:'2026-11-02T13:00:00'}]}),false);
  assert.equal(validTeam({...data,status:{roles:[]}}),false);
});
test('A–F 支持可选加减号，展示保留符号并按字母着色',()=>{
  for(const letter of 'ABCDEF') for(const sign of ['', '+', '-']) {
    const grade=letter+sign,changed=structuredClone(data);
    changed.log[0].grade=grade;changed.status.roles.codex.last_report.grade=grade;
    assert.equal(validTeam(changed),true);
    assert.ok(gradeMarkup(grade).includes(`>${grade}</strong>`));
    assert.ok(gradeMarkup(grade).includes('AB'.includes(letter)?'grade-good':letter==='C'?'grade-mid':'grade-bad'));
  }
  for(const grade of ['A++','A+-','G+','a-',' A','']) {
    assert.equal(validTeam({...data,log:[{...data.log[0],grade}]}),false);
    assert.match(gradeMarkup(grade),/grade-none/);
  }
});
