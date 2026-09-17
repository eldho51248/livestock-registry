#!/usr/bin/env node
/*
 * Teach the Staff Portal's widget runtime about two data-source keys the
 * pinned platform build has no code for at all:
 *
 *   - `"type": "sibling-table"` — populates a select from the rows of another
 *     table on the same intake form (Health Event / Vaccination / Breeding /
 *     Vital Event all pick a Livestock Ear Tag out of the Livestock Details
 *     table this way).
 *   - `"widget-autofill"` — once that ear tag is picked, copies fields off the
 *     matched row (Species, Age) into other widgets on the same row, so the
 *     user does not have to re-enter data already captured for that animal.
 *   - `"widget-age-from-date"` — recomputes a field from another field's date
 *     value on every change (Livestock Details derives Age from Date of Birth
 *     this way).
 *
 * WHY THIS PATCH EXISTS
 * The section UI schemas this registry ships declare four data-source keys that
 * the pinned platform build has no code for at all — `sibling-table`,
 * `sourceWidgetId`, `optionFilter` and `widget-autofill` appear in zero bytes of
 * the compiled bundle. The loader recognises exactly three source types:
 *
 *     let A=[];
 *     if("static"===G.type)A=et(G);
 *     else if("api"===G.type){...}
 *     else "schema"===G.type&&(A=er(G,r||{}));
 *
 * A `sibling-table` source matches none of those branches, so `A` stays `[]`,
 * the widget is handed an empty option list and the dropdown renders with only
 * its placeholder. Nothing errors and nothing is logged, which is why the field
 * looks like a data problem rather than a missing feature.
 *
 * WHY A GLOBAL BRIDGE RATHER THAN READING THE STORE
 * The obvious implementation — read the sibling table's rows out of Redux — does
 * not work from where the select actually lives. `WidgetProvider` builds its
 * store as `useMemo(()=>storeProp||createStore(),[storeProp])`, so a provider
 * mounted without an explicit store gets a *fresh* one. The "Add record" dialog
 * mounts its own provider, so a widget inside the dialog sees only the row being
 * edited, not the page's form state. (This is also why the Breed cascade never
 * fired: its `dependsOn:"species"` lookup read the dialog's store, found the
 * parent value empty and bailed out of the load effect before requesting
 * anything.)
 *
 * So the rows are bridged through `window.__g2pTableRows` instead:
 *
 *   - the publisher runs in `WidgetRenderer`, which renders on the page itself
 *     and therefore sits in the page's store, and mirrors every table widget's
 *     rows into that map keyed by `widget-id`;
 *   - the consumer runs in the load effect and reads the map by the source's
 *     `sourceWidgetId`.
 *
 * The publisher fires on each render of the page-level table, so the map is
 * already populated by the time a dialog is opened, and it refreshes whenever a
 * row is added or removed.
 *
 * KEY NAMING
 * `sibling-table` sources spell their keys `valueField`/`labelField`, while the
 * shared option mapper reads `valueKey`/`labelKey`. The consumer copies them
 * across on the config object before returning, because the loader computes
 *
 *     let{valueKey:a,labelKey:i}=t(),o=ea(A,a,i);
 *
 * *after* the branch that produces `A` — so the mapper picks the copies up
 * without needing its own patch.
 *
 * AUTOFILL
 * `widget-autofill` is spliced into the same onChange callback that already
 * dispatches the widget's own value and publishes `widget:change` — the last
 * comma-operand in
 *
 *     A&&l(f({...})),a&&a(d,e),s&&s.publish({type:"widget:change",...})
 *
 * so it fires exactly when a user (or a future patch) changes the ear-tag
 * widget's value, using the same `l` (dispatch) and `p` (setValue action) the
 * surrounding closure already has in scope — no new helper needs adding to the
 * module, avoiding any question of whether it would run before or after `p` is
 * defined at module scope. It reads the matched row off the same
 * `window.__g2pTableRows` bridge the sibling-table consumer reads, rather than
 * the store, for the identical reason: the "Add record" dialog mounts its own
 * store, so a lookup against `e.widget.values` inside the dialog would only
 * ever see the row being edited.
 *
 * Target widgets (Species, Age) are expected to sit in the same store as the
 * ear-tag widget doing the autofill — true for every current use, since they
 * are columns of the same dialog-table row — so plain `widgetId` values are
 * used without namespacing.
 *
 * AGE FROM DATE
 * Unlike autofill, this config lives on the *listening* widget (Age), pointing
 * at its `baseField` (Date of Birth) — the opposite direction from a normal
 * onChange. So there are two halves:
 *
 *   - a registration declarator added to every widget instance's own hook,
 *     which — when that widget's config carries `widget-age-from-date` — adds
 *     its own id under `window.__g2pAgeListeners[baseField]`;
 *   - a lookup added to the same onChange tail as autofill, keyed by the
 *     field that just changed (`d`), which recomputes and dispatches into
 *     every widget id registered against it.
 *
 * The registration runs on every render rather than once, matching how the
 * table-row publisher above behaves — cheap, idempotent (de-duplicated by id)
 * and needs no dedicated mount/unmount handling.
 *
 * SCOPE
 * All edits target one webpack module in a single client chunk (verified to
 * contain no module boundary between the anchors, so the injected helpers
 * share the scope that holds the path getter and the onChange callback they
 * extend). The header is the only component that also needs its server copy
 * patched to avoid a hydration mismatch; both features here only run in a
 * client effect/callback that never fires during SSR, so the server chunk is
 * deliberately left alone.
 *
 * Exits non-zero if any anchor fails to match, so a platform bump fails the
 * build here rather than silently restoring the empty dropdown.
 */
const fs = require("fs");
const path = require("path");

// Overridable so the patch can be exercised against a copy of the build output
// without a full image build; the Dockerfile never sets it.
const ROOT = process.env.STAFF_UI_ROOT || "/app/.next";

// ,v=(e,t,A)=>{if(!t)return e[A];if("string"==typeof t)return I(e,t);
// The path getter: (values, dataPath, widgetIdFallback). Helpers are injected as
// extra declarators ahead of it so they land in the same scope and can call it.
const PATH_GETTER =
  /,(\w+)=\(e,t,A\)=>\{if\(!t\)return e\[A\];if\("string"==typeof t\)return \w+\(e,t\);/;

// let d=(0,o.d4)(e=>e.widget.values),g=eC({config:e,dataSourceRequestHandler:...})
const RENDERER =
  /let (\w+)=\(0,(\w+)\.d4\)\(e=>e\.widget\.values\),(\w+)=(\w+)\(\{config:e,dataSourceRequestHandler:n,schemaData:s,onValueChange:r\}\)/;

// if("static"===G.type)A=et(G);else if("api"===G.type){
const LOADER =
  /if\("static"===(\w+)\.type\)A=(\w+)\(\1\);else if\("api"===\1\.type\)\{/;

// The exact, verified tail of the onChange callback (confirmed against the
// pinned build's own source, not guessed): the confirmed-value branch, the
// validation dispatch, the parent onValueChange call and the widget:change
// publish. Every identifier here — l (dispatch), p (setValue action), d
// (this widget's id), e (the new value), t (this widget's own config) — is
// already in scope, so the injected autofill call needs no new closure vars.
// A literal match rather than a capturing regex: if a platform bump renames
// any of them, this stops matching and the build fails loudly instead of
// silently skipping the autofill wiring.
const ON_CHANGE_TAIL =
  'l(p({widgetId:d,value:e}))}A&&l(f({widgetId:d,errors:j(e,t["widget-data-validation"],T(r))})),a&&a(d,e),s&&s.publish({type:"widget:change",widgetId:d,value:e,timestamp:Date.now()})}';

// Runs after the widget's own value is committed. Reads the sibling row via
// the same window bridge the sibling-table consumer uses (the dialog's store
// cannot see it either — see AUTOFILL in the header) and copies the mapped
// fields onto the target widgets with the same setValue action `p` already
// used two lines up, which writes `state.widget.values[widgetId]` directly.
//
// Target widgetIds are NOT plain column-keys at runtime: the dialog-table row
// editor namespaces every cell as `${tableWidgetId}-dlg-${slot}-${column-key}`
// (see the `L=(e,t)=>\`${N}-dlg-${e}-${t}\`` cell-id builder in the compiled
// table component), and that slot number changes every time the dialog is
// opened. `af.fields` values are plain column-keys straight out of the static
// schema config, so writing to them directly lands in a redux key nothing
// reads. The fix: derive the *current* namespace prefix from this widget's own
// id (`d`) by stripping its own column-key (`t["column-key"]`, preserved
// unmodified through the cell-id override and so still the plain schema
// value) off the end, then prepend that prefix to each target key.
const AUTOFILL_CALL =
  ',(t["widget-autofill"]&&(function(af,val,own,base){' +
  "try{" +
  "var rows=(window.__g2pTableRows||{})[af.sourceWidgetId];" +
  "if(!Array.isArray(rows))return;" +
  "var row=rows.find(function(rr){return rr&&String(rr[af.matchField])===String(val)});" +
  "if(!row)return;" +
  "var pre=(own&&base&&base.slice(-own.length)===own)?base.slice(0,base.length-own.length):\"\";" +
  "Object.keys(af.fields).forEach(function(tf){l(p({widgetId:pre+tf,value:row[af.fields[tf]]}))});" +
  "}catch(err){}" +
  "})(t[\"widget-autofill\"],e,t[\"column-key\"],d))";

// Companion to AUTOFILL_CALL in the same onChange tail. Registration (see
// AGE_REGISTRATION) keys listeners by the *plain* `baseField` straight out of
// the static schema config, so the lookup here must use this widget's own
// plain `t["column-key"]` rather than its namespaced runtime id `d` — for the
// same dialog-table cell-id-namespacing reason AUTOFILL_CALL above works
// around. The listener ids themselves ARE already the correct namespaced
// runtime ids (each widget registered its own `t["widget-id"]`, not its
// column-key), so no prefix math is needed on the write side here.
const AGE_FROM_DATE_CALL =
  ",(function(fromId,val){" +
  "try{" +
  "var ids=(window.__g2pAgeListeners||{})[fromId];" +
  "if(!ids||!ids.length)return;" +
  "var bd=new Date(val);" +
  "if(isNaN(bd.getTime()))return;" +
  "var now=new Date();" +
  "var months=(now.getFullYear()-bd.getFullYear())*12+(now.getMonth()-bd.getMonth());" +
  "if(now.getDate()<bd.getDate())months--;" +
  "if(months<0)months=0;" +
  "var yrs=Math.floor(months/12),rem=months%12;" +
  "var txt=yrs+(1===yrs?' year, ':' years, ')+rem+(1===rem?' month':' months');" +
  "ids.forEach(function(id){l(p({widgetId:id,value:txt}))});" +
  "}catch(err){}" +
  "})(t[\"column-key\"],e)";

// let{config:t,dataSourceRequestHandler:A,schemaData:r,onValueChange:a}=e,l=(0,o.wA)(),
// n=em(),s=ei(),d=t["widget-id"],g=A||n.dataSourceRequestHandler,c=(0,o.d4)(e=>e.widget.values),
// The exact, verified head of useBaseWidget — every widget instance runs this
// once per render, so it is where an age-from-date widget registers itself.
const HOOK_ENTRY =
  'd=t["widget-id"],g=A||n.dataSourceRequestHandler,c=(0,o.d4)(e=>e.widget.values),';

// Uses `t["widget-id"]` rather than `d` for the widget's own id: this whole
// expression is itself one declarator in the same `let` chain that assigns
// `d=t["widget-id"]` two names later, so `d` is still in its TDZ here — reading
// it would throw "Cannot access 'd' before initialization" on every render of
// any widget carrying `widget-age-from-date` (i.e. the Age field itself).
// `t` (the widget's own config) is bound earlier in the same chain and safe.
const AGE_REGISTRATION =
  '__g2pAgeReg=(t["widget-age-from-date"]&&(function(bf,id){' +
  "try{" +
  "var m=window.__g2pAgeListeners=window.__g2pAgeListeners||{};" +
  "m[bf]=m[bf]||[];" +
  "if(m[bf].indexOf(id)===-1)m[bf].push(id);" +
  "}catch(err){}" +
  '})(t["widget-age-from-date"].baseField,t["widget-id"])),';

// Reads the bridged rows, drops deleted/blank ones, applies `optionFilter`, and
// normalises the field names the shared mapper expects.
//
// A filter carrying a `when` clause is conditional on another field's value and
// is skipped rather than guessed at: showing the full list is recoverable, while
// wrongly hiding the row a user needs is not.
function consumer() {
  return (
    `function __g2pSib(s){try{` +
    `var reg=("undefined"!=typeof window&&window.__g2pTableRows)||{};` +
    `var rows=reg[s.sourceWidgetId];if(!Array.isArray(rows))return[];` +
    `var vf=s.valueField||s.valueKey,lf=s.labelField||s.labelKey||vf;` +
    `if(!vf)return[];` +
    `if(!s.valueKey)s.valueKey=vf;if(!s.labelKey)s.labelKey=lf;` +
    `var f=s.optionFilter,seen={},out=[];` +
    `for(var i=0;i<rows.length;i++){var r=rows[i];` +
    `if(!r||"DELETE"===r.edit_action)continue;` +
    `var val=r[vf];if(null==val||""===val)continue;` +
    `if(f&&f.field&&!f.when){var rv=r[f.field],op=f.operator||"equals";` +
    `if("equals"===op&&rv!==f.value)continue;` +
    `if("notEquals"===op&&rv===f.value)continue;` +
    `if("in"===op&&!(Array.isArray(f.value)&&f.value.indexOf(rv)>-1))continue;}` +
    `var k=String(val);if(seen[k])continue;seen[k]=1;out.push(r);}` +
    `return out;}catch(e){return[];}}`
  );
}

// Mirrors a table widget's rows onto window, keyed by widget-id. `get` is the
// module's path getter, passed by name so the minified identifier is not baked
// into this file twice.
function publisher(get) {
  return (
    `function __g2pPub(c,vals){try{` +
    `if("undefined"==typeof window||!c)return;` +
    `if("table"!==c.widget&&"dialog-table"!==c.widget&&"table"!==c["widget-type"])return;` +
    `var id=c["widget-id"];if(!id)return;` +
    `var rows=${get}(vals,c["widget-data-path"],id);` +
    `if(!Array.isArray(rows))return;` +
    `(window.__g2pTableRows=window.__g2pTableRows||{})[id]=rows;` +
    `}catch(e){}}`
  );
}

function* walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else if (entry.name.endsWith(".js")) yield full;
  }
}

let patched = 0;
const renamed = [];

for (const file of walk(ROOT)) {
  // Only the client chunk carries the widget runtime; skip everything else
  // cheaply rather than running three regexes over the whole build output.
  if (!file.includes(`${path.sep}static${path.sep}`)) continue;
  const before = fs.readFileSync(file, "utf8");
  if (!LOADER.test(before)) continue;

  const getter = before.match(PATH_GETTER);
  const renderer = before.match(RENDERER);
  const onChangeCount = before.split(ON_CHANGE_TAIL).length - 1;
  const hookEntryCount = before.split(HOOK_ENTRY).length - 1;
  if (!getter) {
    console.error(`FATAL: ${path.basename(file)} has the data-source loader but no path getter`);
    process.exit(1);
  }
  if (!renderer) {
    console.error(`FATAL: ${path.basename(file)} has the data-source loader but no WidgetRenderer`);
    process.exit(1);
  }
  if (onChangeCount !== 1) {
    console.error(
      `FATAL: ${path.basename(file)} has the data-source loader but the onChange callback ` +
        `tail matched ${onChangeCount} time(s) (expected 1) — autofill would be silently disabled`
    );
    process.exit(1);
  }
  if (hookEntryCount !== 1) {
    console.error(
      `FATAL: ${path.basename(file)} has the data-source loader but the widget hook entry ` +
        `matched ${hookEntryCount} time(s) (expected 1) — age-from-date would be silently disabled`
    );
    process.exit(1);
  }

  // The five anchors must share one webpack module, or the injected helpers
  // land in a scope the call sites cannot see.
  const onChangeIdx = before.indexOf(ON_CHANGE_TAIL);
  const hookEntryIdx = before.indexOf(HOOK_ENTRY);
  const positions = [getter.index, renderer.index, before.search(LOADER), onChangeIdx, hookEntryIdx];
  const span = before.slice(Math.min(...positions), Math.max(...positions));
  if (/\},\d{4,6}:\(e,t,A\)=>\{/.test(span)) {
    console.error("FATAL: loader, renderer, path getter, onChange callback and hook entry are no longer in one module");
    process.exit(1);
  }

  let after = before;

  // 1. helpers, as extra declarators in the chain that defines the path getter
  after = after.replace(
    PATH_GETTER,
    (m, get) => `,__g2pSib=${consumer()},__g2pPub=${publisher(get)}` + m
  );

  // 2. publish table rows from the page-level renderer
  after = after.replace(
    RENDERER,
    (_m, values, rtk, widget, hook) =>
      `let ${values}=(0,${rtk}.d4)(e=>e.widget.values),` +
      `${widget}=(__g2pPub(e,${values}),${hook}({config:e,dataSourceRequestHandler:n,` +
      `schemaData:s,onValueChange:r}))`
  );

  // 3. resolve sibling-table sources ahead of the built-in branches
  after = after.replace(
    LOADER,
    (_m, src, statics) =>
      `if("sibling-table"===${src}.type)A=__g2pSib(${src});` +
      `else if("static"===${src}.type)A=${statics}(${src});` +
      `else if("api"===${src}.type){`
  );

  // 4. every widget registers itself as an age-from-date listener, if its own
  // config declares one — cheap, idempotent, runs on every render. Spliced
  // AFTER `d` is assigned in this same `let` chain: the registration reads
  // `d`, and a `let` declarator cannot see a sibling declared later in the
  // same statement (temporal dead zone) — only earlier ones.
  after = after.replace(HOOK_ENTRY, HOOK_ENTRY + AGE_REGISTRATION);

  // 5. fire widget-autofill and age-from-date from the onChange tail, once
  // per widget's own value commit (see AUTOFILL and AGE FROM DATE in the
  // header for why these are spliced here rather than added as subscribers
  // like widget-cascade).
  after = after.replace(
    ON_CHANGE_TAIL,
    ON_CHANGE_TAIL.slice(0, -1) + AUTOFILL_CALL + AGE_FROM_DATE_CALL + "}"
  );

  if (after === before) continue;

  fs.writeFileSync(file, after);
  patched += 1;
  console.log("  patched " + file.replace(ROOT + "/", ""));

  // Same immutable-cache problem the other patches have: the base image already
  // published this content hash, so a returning browser would keep the
  // unpatched chunk unless the filename changes.
  const ext = path.extname(file);
  const next = file.slice(0, -ext.length) + ".sib" + ext;
  fs.renameSync(file, next);
  renamed.push({ from: path.basename(file), to: path.basename(next) });
  console.log("  renamed " + path.basename(file) + " -> " + path.basename(next));
}

if (patched !== 1) {
  console.error(
    `sibling-table patch matched ${patched} bundle(s), expected exactly 1 — ` +
      "the platform's widget runtime changed, so ear-tag dropdowns would be empty"
  );
  process.exit(1);
}

for (const { from, to } of renamed) {
  let refs = 0;
  for (const file of walk(ROOT)) {
    const before = fs.readFileSync(file, "utf8");
    if (!before.includes(from)) continue;
    fs.writeFileSync(file, before.split(from).join(to));
    refs += 1;
  }
  console.log(`  rewrote ${refs} reference(s) to ${from}`);
}

console.log("sibling-table data sources enabled");
