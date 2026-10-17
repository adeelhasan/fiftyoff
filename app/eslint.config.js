// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');

module.exports = defineConfig([
  expoConfig,
  {
    ignores: ['dist/*'],
  },
  // React Native <Text> renders quotes as text; the HTML entity rule doesn't apply.
  { rules: { 'react/no-unescaped-entities': 'off' } },
]);
