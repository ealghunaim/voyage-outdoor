// Expo's flat config, unmodified. The rules that matter here are the
// rules-of-hooks ones: a hook called after an early return is a different hook
// count between renders, and it fails as a crash rather than as a warning.
const expo = require('eslint-config-expo/flat');

module.exports = [
  ...expo,
  { ignores: ['dist/*', 'node_modules/*', '.expo/*'] },
];
