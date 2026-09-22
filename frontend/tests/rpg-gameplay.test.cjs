const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const ts = require('typescript')

function loadSource(relative, overrides = {}) {
  const source = fs.readFileSync(path.join(__dirname, '..', relative), 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
      jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
    },
  }).outputText
  const exports = {}
  new Function('require', 'exports', compiled)(name => overrides[name] ?? require(name), exports)
  return exports
}

const condition = loadSource('src/pages/Rpg/condition.ts')
const feedback = loadSource('src/pages/Rpg/actionFeedback.ts')
const turns = loadSource('src/store/rpgTurnStore.ts')
const SkillTab = loadSource('src/pages/Rpg/sidebar/SkillTab.tsx', {
  '../condition': condition, '../rpgUi': { PANEL: '' }, './Empty': { default: () => null },
}).default
// rpgUi 整块在 node 里跑不起来（它 import '@/api/client' 和 react-hot-toast）。
// 只有 WaitBar 用得上，替一个同形状的桩进去，同 SkillTab 那行 PANEL
const rpgUi = { WaitBar: () => null }
const SettlementReport = loadSource('src/pages/Rpg/SettlementReport.tsx', {
  './rpgUi': rpgUi,
}).default
const TweakPanel = loadSource('src/pages/Rpg/TweakPanel.tsx', {
  '@/api/client': { rpgApi: {} }, './condition': condition,
}).default

const npcs = [{ id: 1, name: 'Alice', role: 'npc', relation_enabled: true }]
const moduleDefinition = { play_style: 'sim', stat_defs: [{ name: 'money', min: 0 }] }
const session = {
  npc_states: { '1': { trust: 80 } }, stats: { money: 10 },
  flags: {}, inventory: [], location: 'office',
}
const relation = { relations: [{ npc: 'Alice', stat: 'trust', op: '>=', value: 50 }] }

test('location tweaker includes unmet NPCs and shows their actual session position', () => {
  const React = require('react')
  const render = require('react-dom/server').renderToStaticMarkup
  const html = render(React.createElement(TweakPanel, {
    sessionId: 1,
    sess: { ...session, slot: 'noon', npc_places: { '2': 'pond' } },
    module: moduleDefinition,
    npcs: [
      { id: 2, name: 'Unmet NPC', role: 'npc', location: 'workshop', relation_enabled: false },
      { id: 3, name: 'Protagonist template', role: 'protagonist', relation_enabled: false },
    ],
    locations: [{ name: 'workshop' }, { name: 'pond' }],
    locked: false, onApplied() {},
  }))
  assert.match(html, /Unmet NPC/)
  assert.match(html, /当前位置：pond/)
  assert.match(html, /value="pond" selected/)
  assert.match(html, /value="workshop"/)
  assert.doesNotMatch(html, /Protagonist template/)
})

function buttons(element) {
  if (Array.isArray(element)) return element.flatMap(buttons)
  if (!element || typeof element !== 'object') return []
  return element.type === 'button' ? [element] : buttons(element.props?.children)
}

test('remote relationship action opens picker when a valid candidate exists', () => {
  const action = { needs_target: true, target_anywhere: true, requires: relation }
  assert.equal(condition.actionBlocked(action, session, npcs, '', moduleDefinition), '')
  assert.equal(condition.actionBlocked(action, session, npcs, 'Alice', moduleDefinition), '')
  assert.notEqual(condition.actionBlocked(action, { ...session, npc_states: {} }, npcs, '', moduleDefinition), '')
})

test('untargeted relationship gate and exact resource costs agree', () => {
  assert.equal(condition.actionBlocked({ needs_target: false, requires: relation }, session, npcs), '')
  assert.notEqual(condition.actionBlocked({ effects: { money: -50, reward: 10 } }, session, npcs), '')
  assert.equal(condition.actionBlocked({ effects: { money: -10 } }, session, npcs), '')
})

test('action time preview follows budget, direct advancement, rollover and session overrides', () => {
  const definition = { time_slots: ['早', '晚'], slot_budget: 3 }
  const current = { day: 1, slot: '早', slot_actions: 0, time_slots: [] }
  assert.equal(feedback.actionTimeHint({}, current, definition), '消耗 1 次行动')
  assert.match(feedback.actionTimeHint({}, { ...current, slot_actions: 2 }, definition), /第 1 天 · 晚/)
  assert.match(feedback.actionTimeHint({ cost_slot: true }, current, definition), /推进 1 个时段.*第 1 天 · 晚/)
  assert.match(feedback.actionTimeHint({}, { ...current, slot: '晚', slot_actions: 2 }, definition), /第 2 天 · 早/)
  assert.match(feedback.actionTimeHint({ cost_slot: true }, { ...current, time_slots: ['白天', '夜晚'], slot: '白天' }, definition), /夜晚/)
  assert.equal(feedback.actionTimeHint({}, current, { ...definition, slot_budget: 0 }), '不自动推进时间')
  assert.equal(feedback.actionTimeHint({ cost_slot: true }, { ...current, time_slots: [] }, { time_slots: [] }), '不推进时间')
})

test('effect previews show the clamped benefit and distinguish unknown target effects', () => {
  const definitions = [{ name: 'energy', min: 0, max: 100 }]
  assert.equal(feedback.effectPreview('energy', 10, definitions, { energy: 98 }), 'energy+2')
  assert.equal(feedback.effectPreview('energy', 10, definitions, { energy: 100 }), 'energy不变')
  assert.equal(feedback.effectPreview('energy', -30, definitions, { energy: 50 }), 'energy-30')
  assert.match(feedback.effectPreview('unknown', 10, definitions, {}), /未生效/)
  assert.match(feedback.effectPreview('energy', 10, definitions), /基础效果/)
})

test('settlement presents action cost and daily recovery separately from the net change', () => {
  const render = require('react-dom/server').renderToStaticMarkup
  const html = render(SettlementReport({
    report: {
      status: 'done', changes: ['energy +20'],
      engine_facts: ['行动效果：energy-30（50 → 20）', '跨天恢复：energy+50（20 → 70）'],
    },
    latest: true, busy: false, disabled: false, npcs: [], onRetry() {},
  }))
  assert.match(html, /行动效果：energy-30/)
  assert.match(html, /跨天恢复：energy\+50/)
  assert.match(html, /最终变化：energy \+20/)
})

test('skill button allows the next turn when its cooldown expires at turn start', () => {
  for (const [left, disabled] of [[2, true], [1, false], [0, false]]) {
    const view = SkillTab({
      sess: { ...session, skills: [{ name: 'magic', cooldown_left: left }] },
      skills: [{ name: 'magic', usable: true, category: 'active', effects: {}, requires: {} }],
      npcs, locked: false, onUseSkill() {},
    })
    assert.equal(buttons(view)[0].props.disabled, disabled)
  }
})

test('skill with insufficient resources stays disabled', () => {
  const view = SkillTab({
    sess: { ...session, skills: [{ name: 'magic', cooldown_left: 0 }] },
    skills: [{ name: 'magic', usable: true, effects: { money: -50 }, requires: {} }],
    npcs, locked: false, onUseSkill() {},
  })
  assert.equal(buttons(view)[0].props.disabled, true)
})

test('starting a turn preserves history and unresolved task prompts', () => {
  const store = turns.useRpgTurnStore
  store.getState().update(1, () => ({ bubbles: [{ id: 10, content: 'history' }], taskAsk: [{ id: 20 }] }))
  store.getState().start(1, 'Game', '/game')
  assert.equal(store.getState().turns[1].bubbles[0].id, 10)
  assert.equal(store.getState().turns[1].taskAsk[0].id, 20)
  store.getState().end(1)
})

test('loaded messages preserve every replay option', () => {
  const request = { item_name: 'potion', item_qty: 2, mode: 'private', private_with: 1, attr: 'energy' }
  const bubble = turns.toBubble({ id: 1, role: 'user', content: 'Use potion', turn_request: request })
  assert.deepEqual(bubble.turn_request, request)
})

test('partial settlement explains continuation and keeps retry optional', () => {
  const render = require('react-dom/server').renderToStaticMarkup
  const report = { status: 'partial', retryable: true, warnings: ['A change was rejected'] }
  const view = latest => SettlementReport({ report, latest, busy: false, disabled: false, npcs: [], onRetry() {} })
  const latestView = view(true)
  assert.match(render(latestView), /可以继续游玩/)
  assert.match(render(latestView), /未通过核对的变化没有写入/)
  assert.equal(buttons(latestView).length, 1)
  assert.equal(buttons(latestView)[0].props.disabled, false)
  const historicalView = view(false)
  assert.match(render(historicalView), /不影响继续游玩/)
  assert.equal(buttons(historicalView).length, 0)
  const editedHistory = SettlementReport({ report: { ...report, status: 'stale' }, latest: false, busy: false, disabled: false, npcs: [], onRetry() {} })
  assert.match(render(editedHistory), /修改后尚未重算/)
  assert.doesNotMatch(render(editedHistory), /不影响继续游玩/)
})
