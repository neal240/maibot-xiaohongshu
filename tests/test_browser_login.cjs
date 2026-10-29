// Offline test of browser-helper control flow; synthetic credentials only.
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const Module = require('node:module');
const originalLoad = Module._load;
let sshArgs, sent, closed = false;
const lines = [];
console.log = (...args) => lines.push(args.join(' '));
process.argv = ['node', 'browser_login.cjs', '--host', 'user@server.example',
  '--identity', 'key path', '--known-hosts', 'known hosts path', '--plugin-dir', '/tmp/plugin',
  '--data-dir', '/tmp/data', '--python', '/usr/bin/python3', '--browser', '/browser'];
Module._load = function(name, parent, isMain) {
  if (name === 'playwright') return {chromium: {launch: async () => ({
    newContext: async () => ({
      newPage: async () => ({goto: async () => {}}),
      cookies: async () => [
        {domain: '.xiaohongshu.com', name: 'a1', value: 'SYNTHETIC_A1'},
        {domain: '.xiaohongshu.com', name: 'web_session', value: 'SYNTHETIC_TOKEN'},
        {domain: '.other.example', name: 'secret', value: 'IGNORE_ME'},
      ],
    }),
    close: async () => {closed = true;},
  })}};
  if (name === 'node:readline') return {createInterface: () => ({question: (_, done) => done(''), close: () => {}})};
  if (name === 'node:child_process') return {spawn: (name, args) => {
    assert.equal(name, 'ssh'); sshArgs = args;
    const child = new EventEmitter();
    child.stdout = new EventEmitter(); child.stderr = new EventEmitter();
    child.stdin = {on: () => {}, end: data => {
      sent = JSON.parse(data);
      setImmediate(() => {child.stdout.emit('data', Buffer.from('SESSION_VERIFIED_AND_SAVED')); child.emit('close', 0);});
    }};
    return child;
  }};
  return originalLoad.apply(this, arguments);
};
require('../tools/browser_login.cjs');
setTimeout(() => {
  assert(closed);
  assert(sshArgs.includes('StrictHostKeyChecking=yes'));
  assert(sshArgs.includes('UserKnownHostsFile=known hosts path'));
  assert.equal(sent.shared_cookies.web_session, 'SYNTHETIC_TOKEN');
  assert.equal(sent.shared_cookies.secret, undefined);
  assert(!lines.join('\n').includes('SYNTHETIC_TOKEN'));
  process.stdout.write('BROWSER_HELPER_OFFLINE_TEST: PASS\n');
}, 20);
