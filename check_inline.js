// 提取 static/index.html 的内联 JS 并逐个 node --check
const fs = require('fs');
const { execFileSync } = require('child_process');

const html = fs.readFileSync('static/index.html', 'utf8');
const scripts = [...html.matchAll(/<script(?![^>]*src=)[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
console.log('found ' + scripts.length + ' inline script block(s)');

let ok = true;
scripts.forEach((s, i) => {
  const tmp = '/tmp/inline_' + i + '.js';
  fs.writeFileSync(tmp, s);
  try {
    execFileSync('node', ['--check', tmp], { stdio: 'pipe' });
    console.log('block ' + i + ': syntax OK (' + s.length + ' chars)');
  } catch (e) {
    ok = false;
    console.log('block ' + i + ': SYNTAX ERROR');
    console.log(String(e.stderr || e.message));
  }
});
process.exit(ok ? 0 : 1);
