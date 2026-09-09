// Errors only, and deliberately few of them.
//
// Vite compiles JSX without resolving identifiers, so a name that was never
// declared builds clean and throws the moment the screen opens. That nearly
// shipped a crash on the purchase screen. `no-undef` is the rule that catches
// it and it is most of why this file exists.
//
// `no-unused-vars` is off: without the React plugin the base parser cannot see
// that a component named in JSX is used, so it reported 146 imports as dead. A
// linter that cries wolf gets switched off, and a switched-off linter catches
// nothing.
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { "react-hooks": reactHooks },
    linterOptions: { reportUnusedDisableDirectives: false },
    rules: {
      ...js.configs.recommended.rules,
      "no-undef": "error",
      "no-unused-vars": "off",
      // The two that catch real React bugs: a hook called conditionally, and a
      // dependency array that lies about what the effect reads.
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
];
