import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

// Tailwind 自带的色板，比如 bg-red-500。
const paletteClass =
  "/\\b(bg|text|border|ring|fill|stroke|from|via|to)-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-[0-9]{2,3}\\b/";

export default tseslint.config(
  {
    ignores: [
      "dist",
      "src/routeTree.gen.ts",
      "src/api/schema.d.ts",
      "src/components/ui",
      "src/components/assistant-ui",
      "src/hooks/use-mobile.ts",
      "playwright-report",
      "test-results",
    ],
  },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: { ...reactHooks.configs.recommended.rules },
  },
  {
    files: ["src/**/*.tsx"],
    ignores: ["src/**/*.test.tsx"],
    rules: {
      "no-restricted-properties": [
        "error",
        { object: "window", property: "confirm", message: "用 askConfirm，见 docs/frontend.md。" },
      ],
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXOpeningElement[name.name=/^(button|input|select|textarea)$/]",
          message: "用 src/components/ui 或 src/components/common 里的组件，见 docs/frontend.md。",
        },
        {
          selector: `Literal[value=${paletteClass}]`,
          message: "颜色用 src/index.css 的语义 token，见 docs/frontend.md。",
        },
        {
          selector: `TemplateElement[value.raw=${paletteClass}]`,
          message: "颜色用 src/index.css 的语义 token，见 docs/frontend.md。",
        },
        {
          selector: "CallExpression[callee.property.name=/^toLocale(Date|Time)?String$/]",
          message: "时间和数字用 src/lib/format.ts，见 docs/frontend.md。",
        },
      ],
    },
  },
);
