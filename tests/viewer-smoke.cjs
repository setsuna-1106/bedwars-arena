// Execute the offline viewer against a small DOM/Canvas stand-in, without a browser.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
class Element {
  constructor(id = '') {
    this.id=id; this.children=[]; this.style={}; this.listeners={}; this.attributes={};
    this.value=id==='speed'?'1':id==='filter'?'all':'';
    this.width=1280; this.height=640; this.tagName='DIV'; this.textContent='';
    this.classList={add(){},remove(){}};
  }
  appendChild(value){this.children.push(value);return value}
  replaceChildren(){this.children=[]}
  setAttribute(key,value){this.attributes[key]=value}
  addEventListener(name,callback){this.listeners[name]=callback}
  setPointerCapture(){}
  getBoundingClientRect(){return {left:0,top:0,width:1280,height:640}}
  getContext(){return new Proxy({}, {get:(o,k)=>k in o?o[k]:(()=>{}),set:(o,k,v)=>(o[k]=v,true)})}
}
const elements=new Map(),document={
  getElementById(id){if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id)},
  createElement(tag){const e=new Element();e.tagName=tag.toUpperCase();return e}
};
const keyboard={};
const context={document,window:{addEventListener(name,fn){keyboard[name]=fn}},requestAnimationFrame(){},structuredClone,console};
vm.createContext(context);
let html=fs.readFileSync(process.argv[2]||path.join(__dirname,'../src/bedwars_arena/replay/viewer.html'),'utf8');
const makePlayer=(id,team,x)=>({player_id:id,team_id:team,life_index:1,cooldowns:{attack:4},
  progression:{armor_tier:0},stats:{kills:0},life:{kind:'alive',spatial:{x,z:0,facing_x:1,facing_z:0},
    vitality:{health:20},inventory:{wooden_sword:1},held_item:'wooden_sword',effects:[],movement:null,interaction:null}});
const state={tick:0,terrain:{'0,-1,0':{kind:'original'},'1,0,0':{kind:'wool'}},entities:{},result:null,
  teams:{red:{bed_state:{status:'present'}},blue:{bed_state:{status:'present'}}},
  players:{red_1:makePlayer('red_1','red',0),red_2:makePlayer('red_2','red',-2),
           blue_1:makePlayer('blue_1','blue',5),blue_2:makePlayer('blue_2','blue',7)}};
const data={manifest:{match_id:'fixture',seed_hex:'0001',summary:{failure:null,truncated:true}},
  definitions:{map:{bounds:{min_x:-10,max_x:10,min_z:-5,max_z:5},generators:[],teams:[
     {team_id:'red',bed:{x:-4,z:0}},{team_id:'blue',bed:{x:4,z:0}}]},
   profile:{game:{ticks_per_second:20},combat:{max_hp:20}},
   scenario:{players:[{player_id:'red_1',team_id:'red'},{player_id:'red_2',team_id:'red'},
                      {player_id:'blue_1',team_id:'blue'},{player_id:'blue_2',team_id:'blue'}]}},
  initial_state:state,
  frames:[{tick:0,changes:[]},{tick:1,changes:[{op:'set',path:['tick'],value:1},
          {op:'set',path:['players','red_1','life','spatial','x'],value:0.2}]},
          {tick:2,changes:[{op:'set',path:['tick'],value:2},{op:'set',path:['players','blue_1','life'],
           value:{kind:'eliminated',eliminated_at:2,reason:'melee'}}]}],
  events:[{id:'i1',kind:'movement_collision',happened_at:1,payload:{player_id:'red_1'}},
          {id:'i2',kind:'bed_destroyed',happened_at:1,payload:{team_id:'blue'}},
          {id:'i3',kind:'player_died',happened_at:2,payload:{player_id:'blue_1',final:true}},
          {id:'i4',kind:'block_broken',happened_at:2,payload:{player_id:'red_1',recovery:{received:1,dropped:0,destroyed:0}}}]};
if(!process.argv[2])html=html.replace('/*__REPLAY_DATA__*/',JSON.stringify(data));
const match=html.match(/<script>([\s\S]*?)<\/script>/);
assert(match,'viewer script is present');
const checks=process.argv[2] ? `
  for(const [filter,expected] of [['final',1],['movement_collision',16],['block_broken',27]]){
    el('filter').value=filter;filterEvents();if(!el('events').children.length)throw Error('missing '+filter);
    el('events').children[0].onclick();if(state.tick!==expected)throw Error('bad event '+filter);
    if(!el('event-detail').textContent.includes('payload'))throw Error('missing event detail');
  }
  seek(frames.length-1);seek(5);if(state.tick!==frames[5].tick)throw Error('reverse seek');
` : `
  if(el('red-bed').textContent!=='床仍在'||el('markers').children.length!==3)throw Error('initial scoreboard/markers');
  const before=JSON.stringify(state);zoomBy(2);if(view.zoom!==2||JSON.stringify(state)!==before)throw Error('zoom changed recorded state');
  el('follow').onclick();if(!view.follow)throw Error('follow toggle');
  seek(1);if(state.tick!==1||state.players.red_1.life.spatial.x!==0.2)throw Error('forward seek');
  el('filter').value='final';filterEvents();if(el('events').children.length!==1)throw Error('event filter');
  el('events').children[0].onclick();if(state.tick!==2||!el('event-detail').textContent.includes('blue_1'))throw Error('event jump');
  if(el('match-status').textContent!=='达到外部时限')throw Error('truncation status');
  selected='blue_1';render();if(!el('player-detail').children.length)throw Error('eliminated inspector');
  seek(0);if(state.tick!==0||state.players.red_1.life.spatial.x!==0)throw Error('reverse seek');
  const fixtureCanvas=el('field'),origin=transform();fixtureCanvas.listeners.pointerdown({clientX:origin.X(0),clientY:origin.Z(0),pointerId:1});
  fixtureCanvas.listeners.pointerup({clientX:origin.X(0),clientY:origin.Z(0)});if(selected!=='red_1')throw Error('map player selection');
  el('next-event').onclick();if(state.tick!==1)throw Error('next event');
  el('previous-event').onclick();if(state.tick!==1)throw Error('no earlier key event');
  el('forward').onclick();if(state.tick!==2)throw Error('single step');
`;
vm.runInContext(match[1]+checks,context,{timeout:15000});
console.log('Viewer controls, event navigation and recorded state checks passed.');
