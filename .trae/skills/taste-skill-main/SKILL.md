---
name: taste-skill-main
description: Each skill does one job; you do not need all of them at once. Implementation skills output code. Image-generation skills output reference images only.
每项技能负责一项任务，你无需同时使用全部技能。实现技能用于生成代码，图像生成技能仅用于生成参考图像。

The Install name column is the exact value you pass to --skill.
安装名称列是您传递给 --skill 的确切值。

Skill (folder) 技能（文件夹）	Install name 安装名称	Description 描述
taste-skill	design-taste-frontend	🆕 v2 (experimental) - substantial rewrite of the default skill. Reads the brief, infers the design language, tunes three dials (VARIANCE / MOTION / DENSITY). Brief inference, design-system map, hard em-dash ban, canonical GSAP code skeletons, redesign-audit protocol, strict pre-flight check. Actively iterating toward v2.0.0 stable.
v2（实验性）——对默认技能进行了大幅重写。读取简要说明，推断设计语言，调整三个旋钮（方差/运动/密度）。简短推理、设计系统映射、严格禁止破折号使用、采用标准GSAP代码骨架、重新设计审计流程、严格的飞行前检查。正积极迭代，朝向v2.0.0稳定版本迈进。
taste-skill-v1	design-taste-frontend-v1	The original v1 of taste-skill, preserved for projects depending on its exact behavior. Use only if the v2 default breaks something specific in your workflow.
原始的 v1 版本 taste-skill，因其确切行为而被保留用于特定项目。仅在 v2 默认版本破坏了您工作流程中的某些具体功能时使用。
gpt-tasteskill	gpt-taste	Stricter variant for GPT/Codex: higher layout variance, stronger GSAP direction, aggressive anti-slop.
GPT/Codex的更严格变体：更高的布局变化、更强的GSAP方向性，以及更积极的防滑设计。
image-to-code-skill	image-to-code	Image-first pipeline: generate site references, analyze them, then implement the frontend to match.
图像优先流程：生成网站参考，进行分析，然后实现前端以匹配。
redesign-skill	redesign-existing-projects	Existing projects: audit the UI first, then fix layout, spacing, hierarchy, styling.
现有项目：先审计用户界面，再修复布局、间距、层级和样式。
soft-skill	high-end-visual-design	Polished, calm, expensive UI with softer contrast, whitespace, premium fonts, spring motion.
光滑、沉稳、高端的用户界面，对比度更柔和，留白更自然，字体更显高级，搭配弹簧式动态效果。
output-skill	full-output-enforcement	When the model ships half-finished work: full output, no placeholder comments.
当模型提交半成品时：完整输出，无占位符注释。
minimalist-skill	minimalist-ui	Editorial product UI (Notion/Linear vibes), restrained palette, crisp structure.
编辑产品界面（Notion/Linear vibes），色调克制，结构清晰。
brutalist-skill	industrial-brutalist-ui	Hard mechanical language: Swiss type, sharp contrast, experimental layout.
硬朗的机械语言：瑞士风格，鲜明对比，实验性布局。
stitch-skill	stitch-design-taste	Google Stitch-compatible rules, including optional DESIGN.md export format.
支持 Google Stitch 的规则，包括可选的 DESIGN.md 导出格式。
Image generation skills 图像生成技能
These produce design images only (no code). Use with ChatGPT Images, Codex image mode, or any agent that generates images.
仅生成设计图像（不包含代码）。可与 ChatGPT 图像、Codex 图像模式或任何生成图像的代理一起使用。

Skill (folder) 技能（文件夹）	Install name 安装名称	Description 描述
imagegen-frontend-web	imagegen-frontend-web	Website comps: hero, landing, multi-section with strong typography, spacing, anti-slop art direction.
网站组件：英雄页、落地页、多模块设计，具备出色的字体排版、间距设置和抗滑视觉设计。
imagegen-frontend-mobile	imagegen-frontend-mobile	Mobile screens and flows: iOS/Android/cross-platform, mockups, readable type, coherent sets.
移动屏幕与流程：iOS/Android/跨平台，原型设计，可读的排版，连贯的组合。
brandkit	brandkit	Brand-kit boards: logo directions, palettes, type, identity applications across categories.
品牌套件板：标志方向、配色方案、字体及各品类的标识应用。
Which one should I use?
我该用哪一个？
Start with taste-skill for the safest general default. (Now v2 experimental - see what changed in the CHANGELOG.)
从味觉技能开始，以最安全的通用默认设置。（目前为 v2 实验版本——请参阅 CHANGELOG 查看变更内容。）
If you depend on the exact behavior of the original taste-skill, install taste-skill-v1 instead.
如果依赖原始口味技能的精确行为，请安装 taste-skill-v1。
Use gpt-taste when you want the stricter GPT/Codex-oriented rules and motion/layout enforcement.
当您需要更严格的GPT/Codex规则以及动作/布局执行时，请使用gpt-taste。
Use image-to-code-skill for image → analyze → code website workflows.
使用图像到代码技能，将图像 → 分析 → 生成网站工作流程。
Use redesign-skill to improve an existing codebase instead of greenfield styling.
使用重构技能来改进现有的代码库，而不是从零开始设计。
Add soft-skill, minimalist-skill, or brutalist-skill when the visual direction is already chosen.
当视觉方向已经确定时，再添加软技能、极简技能或粗犷技能。
Add output-skill if the agent keeps truncating output.
如果代理持续截断输出，则添加输出技能。
Use imagegen-frontend-web, imagegen-frontend-mobile, or brandkit when the deliverable is images (comps, flows, identity boards), then pass results to your coding agent.
当交付内容为图像（如组件、流程图、标识板）时，请使用 imagegen-frontend-web、imagegen-frontend-mobile 或 brandkit，然后将结果传递给您的编码代理。
Image-first tip 图像优先提示
For image-to-code-skill, state the pipeline in the prompt, e.g.: follow the skill: generate images, then analyze, then code.
对于图像到代码的技能，请在提示中说明流程，例如：先生成图像，然后进行分析，最后编写代码。

ChatGPT Images and Codex ChatGPT 图像与 Codex
Attach or paste imagegen-frontend-web, imagegen-frontend-mobile, or brandkit and ask for the frames you need, then feed the renders to Codex, Cursor, or Claude Code. Use image-to-code-skill when you want one workflow that both generates references and implements the site in code.
将 imagegen-frontend-web、imagegen-frontend-mobile 或 brandkit 附加或粘贴进来，然后提出所需的框架，再将生成的渲染结果传入 Codex、Cursor 或 Claude Code。当您希望使用一个流程同时生成参考内容并实现网站代码时，请使用 image-to-code-skill。
---

<p align="center">
  <img src="assets/readme-banner.webp" alt="Taste Skill - Anti-slop Agent Skills for premium frontends" width="100%" />
</p>

# Taste Skill

<p align="center">
  <em>The Anti-Slop Frontend Framework for AI Agents</em>
</p>

<p align="center" style="margin-bottom: 8px;">
  <a href="https://tasteskill.dev" title="Visit tasteskill.dev"><img src="assets/readme-buttons/btn-site.webp" alt="Visit tasteskill.dev" height="56" /></a>
</p>

<h3 align="center">Sponsors</h3>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://kimi-file.moonshot.cn/prod-chat-kimi/kfs/4/1/2026-06-05/1d8h69mt3v89kkekg24gg" />
    <img alt="Kimi Open Source Friends" src="https://kimi-file.moonshot.cn/prod-chat-kimi/kfs/4/1/2026-06-05/1d8h69fudcmosb3pipls0" width="420" />
  </picture>
</p>

<table align="center">
  <tr>
    <td align="center" width="76"><a href="https://img.ly/"><img src="assets/sponsors/imgly-logo.svg" alt="IMG.LY" width="62" height="62" /></a></td>
    <td><sub><a href="https://img.ly/"><strong>IMG.LY</strong></a> · CreativeEditor SDK</sub></td>
  </tr>
  <tr>
    <td align="center" width="76"><a href="https://animations.dev"><img src="assets/sponsors/animations-dev.webp" alt="animations.dev" width="62" height="62" /></a></td>
    <td><sub><a href="https://github.com/emilkowalski"><strong>Emil Kowalski</strong></a> · <a href="https://animations.dev">animations.dev</a></sub></td>
  </tr>
  <tr>
    <td align="center" width="76"><a href="https://www.sent.dm"><img src="assets/sponsors/sentdm.png" alt="Sent.dm" width="62" height="62" /></a></td>
    <td><sub><a href="https://www.sent.dm"><strong>Sent.dm</strong></a> · messaging APIs for SMS, WhatsApp, and RCS</sub></td>
  </tr>
  <tr>
    <td align="center" width="76"><a href="https://vercel.com/open-source-program"><img src="assets/sponsors/vercel-logo.svg" alt="Vercel" width="62" height="62" /></a></td>
    <td><a href="https://vercel.com/open-source-program"><img src="assets/vercel-oss-program-badge.svg" alt="Vercel Open Source Program" height="32" /></a></td>
  </tr>
</table>

<p align="center"><sub><a href="https://github.com/sponsors/Leonxlnx">Become a sponsor</a></sub></p>

Portable **Agent Skills** that upgrade AI-built interfaces: stronger layout, typography, motion, and spacing instead of boilerplate-looking UIs. This repo also includes **image-generation skills** for reference boards (web, mobile, brand kits). Pair them with **ChatGPT Images** or similar generators, then hand the frames to Codex, Cursor, or Claude Code for implementation.

<p align="center">
  <a href="LICENSE"><img src="assets/readme-buttons/btn-mit.webp" alt="MIT License" height="45" valign="middle" /></a>
  &nbsp;
  <a href="https://github.com/vercel-labs/agent-skills"><img src="assets/readme-buttons/btn-agent-skills.webp" alt="Agent Skills compatible" height="45" valign="middle" /></a>
  &nbsp;
  <a href="#installing"><img src="assets/readme-buttons/btn-tools.webp" alt="Codex, Cursor, Claude" height="45" valign="middle" /></a>
  &nbsp;
  <a href="https://www.tasteskill.dev/changelog"><img src="assets/readme-buttons/btn-changelog.webp" alt="Changelog" height="45" valign="middle" /></a>
</p>

## Disclaimer

Taste Skill has no official token, coin, or crypto project. Any token using my name, image, or project is unaffiliated and not endorsed by me.

<p align="center"><sub><a href="#disclaimer">Disclaimer</a> · <a href="#installing">Install</a> · <a href="#skills">Skills</a> · <a href="#settings-taste-skill-only">Settings</a> · <a href="#examples">Examples</a> · <a href="#sponsors">Sponsors</a> · <a href="#research">Research</a> · <a href="#common-questions">FAQ</a> · <a href="#license">License</a></sub></p>

## Feedback & Contributions

We would love your feedback. Suggestions and bug reports:

- Open a Pull Request or Issue on GitHub  
- DM [@lexnlin](https://x.com/lexnlin) or [@blueemi99](https://x.com/blueemi99)  
- Email us at [hello@tasteskill.dev](mailto:hello@tasteskill.dev)

## Installing

The [`npx skills add`](https://github.com/vercel-labs/agent-skills) CLI scans the `skills/` folder in this repo, so **all skills below (code and image-generation) install the same way.**

```bash
npx skills add https://github.com/Leonxlnx/taste-skill
```

Install a single skill by its **install name** (the `name:` field inside the SKILL frontmatter, not the folder name):

```bash
npx skills add https://github.com/Leonxlnx/taste-skill --skill "design-taste-frontend"
```

You can also copy any `SKILL.md` into your project or paste it into ChatGPT / Codex conversations.

### Updating from the previous version

The default `taste-skill` (install name `design-taste-frontend`) is now **v2 (experimental)**, a substantial rewrite of the original v1. If you already have v1 installed, just re-run the install command and you will be upgraded:

```bash
npx skills add https://github.com/Leonxlnx/taste-skill --skill "design-taste-frontend"
```

The install name did not change, so no script updates are needed. The newer SKILL.md replaces the older one in place.

If you depend on the exact behavior of v1 and want to pin to it explicitly:

```bash
npx skills add https://github.com/Leonxlnx/taste-skill --skill "design-taste-frontend-v1"
```

See [CHANGELOG.md](CHANGELOG.md) for the full v1 to v2 diff and the rationale.

## Skills

Each skill does one job; you do not need all of them at once. **Implementation skills** output code. **Image-generation skills** output reference images only.

The `Install name` column is the exact value you pass to `--skill`.

| Skill (folder) | Install name | Description |
| --- | --- | --- |
| **taste-skill** | `design-taste-frontend` | 🆕 **v2 (experimental)** - substantial rewrite of the default skill. Reads the brief, infers the design language, tunes three dials (VARIANCE / MOTION / DENSITY). Brief inference, design-system map, hard em-dash ban, canonical GSAP code skeletons, redesign-audit protocol, strict pre-flight check. Actively iterating toward v2.0.0 stable. |
| **taste-skill-v1** | `design-taste-frontend-v1` | The original v1 of taste-skill, preserved for projects depending on its exact behavior. Use only if the v2 default breaks something specific in your workflow. |
| **gpt-tasteskill** | `gpt-taste` | Stricter variant for GPT/Codex: higher layout variance, stronger GSAP direction, aggressive anti-slop. |
| **image-to-code-skill** | `image-to-code` | Image-first pipeline: generate site references, analyze them, then implement the frontend to match. |
| **redesign-skill** | `redesign-existing-projects` | Existing projects: audit the UI first, then fix layout, spacing, hierarchy, styling. |
| **soft-skill** | `high-end-visual-design` | Polished, calm, expensive UI with softer contrast, whitespace, premium fonts, spring motion. |
| **output-skill** | `full-output-enforcement` | When the model ships half-finished work: full output, no placeholder comments. |
| **minimalist-skill** | `minimalist-ui` | Editorial product UI (Notion/Linear vibes), restrained palette, crisp structure. |
| **brutalist-skill** | `industrial-brutalist-ui` | Hard mechanical language: Swiss type, sharp contrast, experimental layout. |
| **stitch-skill** | `stitch-design-taste` | Google Stitch-compatible rules, including optional `DESIGN.md` export format. |

### Image generation skills

These produce design images only (no code). Use with ChatGPT Images, Codex image mode, or any agent that generates images.

| Skill (folder) | Install name | Description |
| --- | --- | --- |
| **imagegen-frontend-web** | `imagegen-frontend-web` | Website comps: hero, landing, multi-section with strong typography, spacing, anti-slop art direction. |
| **imagegen-frontend-mobile** | `imagegen-frontend-mobile` | Mobile screens and flows: iOS/Android/cross-platform, mockups, readable type, coherent sets. |
| **brandkit** | `brandkit` | Brand-kit boards: logo directions, palettes, type, identity applications across categories. |

### Which one should I use?

- Start with **taste-skill** for the safest general default. (Now v2 experimental - see what changed in the [CHANGELOG](CHANGELOG.md).)
- If you depend on the exact behavior of the original taste-skill, install **taste-skill-v1** instead. 
- Use **gpt-taste** when you want the stricter GPT/Codex-oriented rules and motion/layout enforcement. 
- Use **image-to-code-skill** for image → analyze → code website workflows. 
- Use **redesign-skill** to improve an existing codebase instead of greenfield styling. 
- Add **soft-skill**, **minimalist-skill**, or **brutalist-skill** when the visual direction is already chosen. 
- Add **output-skill** if the agent keeps truncating output. 
- Use **imagegen-frontend-web**, **imagegen-frontend-mobile**, or **brandkit** when the deliverable is **images** (comps, flows, identity boards), then pass results to your coding agent.

### Image-first tip

For **image-to-code-skill**, state the pipeline in the prompt, e.g.: `follow the skill: generate images, then analyze, then code`.

### ChatGPT Images and Codex

Attach or paste **`imagegen-frontend-web`**, **`imagegen-frontend-mobile`**, or **`brandkit`** and ask for the frames you need, then feed the renders to Codex, Cursor, or Claude Code. Use **image-to-code-skill** when you want one workflow that both generates references and implements the site in code.

## Settings (taste-skill only)

Numbers at the top of the file are 1-10 dials:

- **DESIGN_VARIANCE**: Layout experimentation (lower: centered/clean · higher: asymmetric/modern).
- **MOTION_INTENSITY**: Animation depth (lower: hover · higher: scroll/magnetic).
- **VISUAL_DENSITY**: Information per viewport (lower: spacious · higher: dense dashboards).

## Examples

Created with taste-skill:

<p>
  <img src="examples/floria-top.webp" width="400" />
  <img src="examples/floria-bottom.webp" width="400" />
</p>

## Support the project

If Taste Skill helps you, consider sponsoring:

[Sponsor on GitHub](https://github.com/sponsors/Leonxlnx)

### Community Sponsors

<a href="https://github.com/dnakov"><img src="https://github.com/dnakov.png" width="40" height="40" style="border-radius:50%" alt="dnakov" title="dnakov" /></a>
<a href="https://github.com/AkramReshad"><img src="https://github.com/AkramReshad.png" width="40" height="40" style="border-radius:50%" alt="AkramReshad" title="AkramReshad" /></a>
<a href="https://github.com/ajmalaksar25"><img src="https://github.com/ajmalaksar25.png" width="40" height="40" style="border-radius:50%" alt="ajmalaksar25" title="ajmalaksar25" /></a>
<a href="https://github.com/krikkkk"><img src="https://github.com/krikkkk.png" width="40" height="40" style="border-radius:50%" alt="krikkkk" title="krikkkk" /></a>
<a href="https://github.com/navanchauhan"><img src="https://github.com/navanchauhan.png" width="40" height="40" style="border-radius:50%" alt="navanchauhan" title="navanchauhan" /></a>
<a href="https://github.com/robinebers"><img src="https://github.com/robinebers.png" width="40" height="40" style="border-radius:50%" alt="robinebers" title="robinebers" /></a>
<a href="https://github.com/JKc66"><img src="https://github.com/JKc66.png" width="40" height="40" style="border-radius:50%" alt="JKc66" title="JKc66" /></a>
<a href="https://github.com/u2393696078-rgb"><img src="https://github.com/u2393696078-rgb.png" width="40" height="40" style="border-radius:50%" alt="u2393696078-rgb" title="u2393696078-rgb" /></a>
<a href="https://github.com/a-human-created-this"><img src="https://github.com/a-human-created-this.png" width="40" height="40" style="border-radius:50%" alt="a-human-created-this" title="a-human-created-this" /></a>
<a href="https://github.com/AtharvaJaiswal005"><img src="https://github.com/AtharvaJaiswal005.png" width="40" height="40" style="border-radius:50%" alt="AtharvaJaiswal005" title="AtharvaJaiswal005" /></a>
<a href="https://github.com/ghughes7"><img src="https://github.com/ghughes7.png" width="40" height="40" style="border-radius:50%" alt="ghughes7" title="ghughes7" /></a>
<a href="https://github.com/mccun934"><img src="https://github.com/mccun934.png" width="40" height="40" style="border-radius:50%" alt="mccun934" title="mccun934" /></a>
<a href="https://github.com/techmedic5"><img src="https://github.com/techmedic5.png" width="40" height="40" style="border-radius:50%" alt="techmedic5" title="techmedic5" /></a>
<a href="https://github.com/bytewerk-dev"><img src="https://github.com/bytewerk-dev.png" width="40" height="40" style="border-radius:50%" alt="bytewerk-dev" title="bytewerk-dev" /></a>
<a href="https://github.com/LuisGot"><img src="https://github.com/LuisGot.png" width="40" height="40" style="border-radius:50%" alt="LuisGot" title="LuisGot" /></a>
<a href="https://github.com/oskar-collab"><img src="https://github.com/oskar-collab.png" width="40" height="40" style="border-radius:50%" alt="oskar-collab" title="oskar-collab" /></a>

<p align="center">
 <a href="https://www.star-history.com/leonxlnx/taste-skill">
  <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/badge?repo=Leonxlnx/taste-skill&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/badge?repo=Leonxlnx/taste-skill" />
   <img alt="Star History Rank" src="https://api.star-history.com/badge?repo=Leonxlnx/taste-skill" />
  </picture>
 </a>
</p>

## Research

Background writing that shaped these skills lives in [`research/`](research/).

## Common Questions

**How is this different from other AI design skills?**  
Multiple specialized variants, adjustable dials in key skills, anti-repetition rules informed by dedicated research. All are framework agnostic across major coding agents.

**Does it work with React, Vue, Svelte?**  
Yes. Rules target design intent, not a single framework API.

**What is SKILL.md?**  
A portable instruction file agents can load automatically; install via `npx skills add` or by copying into a repo or conversation.

**Do image-generation skills install with `npx skills add`?**  
Yes. They live under `skills/` alongside the code skills so the same CLI discovers them.

## License

[MIT License](LICENSE) · Copyright (c) 2026 Leonxlnx