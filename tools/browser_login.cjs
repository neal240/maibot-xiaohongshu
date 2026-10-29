// One-time interactive browser login. Never prints or saves cookies locally.
// Requires a locally installed Playwright and an existing Chrome/Chromium.
const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const readline = require('node:readline');

function readOptions(args) {
  const options = {};
  for (let i = 0; i < args.length; i += 2) {
    if (!args[i].startsWith('--') || !args[i + 1]) throw Error('invalid option');
    options[args[i].slice(2)] = args[i + 1];
  }
  for (const key of ['host', 'identity', 'known-hosts', 'plugin-dir', 'data-dir', 'python', 'browser']) {
    if (!options[key]) throw Error('missing option: ' + key);
  }
  if (!/^[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+$/.test(options.host)) throw Error('invalid SSH target');
  for (const key of ['plugin-dir', 'data-dir', 'python']) {
    if (!/^\/[a-zA-Z0-9_./-]+$/.test(options[key]) || options[key].includes('..'))
      throw Error('invalid remote path: ' + key);
  }
  if (options.port && !/^\d{1,5}$/.test(options.port)) throw Error('invalid port');
  return options;
}

async function main() {
  const options = readOptions(process.argv.slice(2));
  const browser = await chromium.launch({executablePath: options.browser, headless: false});
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await page.goto('https://www.xiaohongshu.com/explore', {waitUntil: 'domcontentloaded', timeout: 30000});
    console.log('请在新窗口登录小红书账号并完成网页要求的验证，完成后在此终端按回车。');
    const input = readline.createInterface({input: process.stdin, output: process.stdout});
    await new Promise(resolve => input.question('', resolve));
    input.close();
    const cookies = (await context.cookies()).filter(c => c.domain === 'xiaohongshu.com' || c.domain.endsWith('.xiaohongshu.com'));
    const shared = {}, hosts = {};
    for (const c of cookies) {
      if (c.domain === '.xiaohongshu.com' || c.domain === 'xiaohongshu.com') shared[c.name] = c.value;
      else (hosts[c.domain.replace(/^\./, '')] ||= {})[c.name] = c.value;
    }
    if (!shared.a1 || !shared.web_session) throw Error('no authenticated browser session found');
    const remote = `cd ${options['plugin-dir']} && ${options.python} tools/import_session.py ${options['data-dir']}`;
    const ssh = spawn('ssh', ['-i', options.identity, '-o', `UserKnownHostsFile=${options['known-hosts']}`,
      '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
      '-o', 'ConnectTimeout=15', '-p', options.port || '22', options.host, remote],
      {stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true});
    let output = '';
    ssh.stdout.on('data', chunk => { output += chunk.toString(); });
    ssh.stderr.on('data', () => {});
    ssh.stdin.on('error', () => {});
    ssh.stdin.end(JSON.stringify({version: 1, shared_cookies: shared, host_cookies: hosts}));
    const code = await new Promise(resolve => { ssh.on('error', () => resolve(-1)); ssh.on('close', resolve); });
    if (code !== 0 || !output.includes('SESSION_VERIFIED_AND_SAVED')) throw Error('session import failed');
    console.log('会话已在服务器通过验证并安全保存。');
  } finally { await browser.close(); }
}

main().catch(error => { console.error('登录助手失败：', error.message); process.exitCode = 1; });
