---
name: add-template
description: 在 NovelBot 新增或修改 jinja2 prompt 模板时使用，保证 loader 约定、render 调用点、变量占位与"无死常量"都对齐。当用户说"加一个 prompt 模板"、"改某个 agent 的提示词"、"新增 xxx 的 prompt"时使用。
---

# 新增 / 修改 prompt 模板

prompt 的**唯一真实源是 `backend/app/prompts/templates/*.jinja2`**。代码通过 `loader.render()` 读取，绝不在 .py 里写 prompt 字符串常量。

## 关键约定

- 模板目录：`backend/app/prompts/templates/`
- 加载器：`backend/app/prompts/loader.py`
  - `render(template_name, **kwargs)` 用 Jinja2 FileSystemLoader
  - `template_name` 必须带 `.jinja2` 后缀
- 模板里的变量用 `{{ var }}`；调用方 `render("xxx.jinja2", var=...)` 必须传齐

## 新增模板的步骤

1. 在 `templates/` 下建 `<name>.jinja2`，列出它需要的 `{{ 变量 }}`。
2. 找到调用点（通常在 `backend/app/agents/` 或 `backend/app/services/`），用 `render("<name>.jinja2", 变量=值)` 接入。
3. 核对：模板里每个 `{{ var }}` 在 render 调用处都有对应 kwarg；render 传的 kwarg 模板里都用到了。
4. **死常量检查**（这个项目踩过坑）：确认没有在 .py 里同时留一份同义的 prompt 字符串常量。新增后 grep 一遍，例如：
   `grep -n "PROMPT_PREFIX\|PROMPT_SUFFIX\|<NAME>_PROMPT" backend/app/services backend/app/agents`
   若发现某常量只在定义行出现、无人引用 → 是死代码，提示用户删除。
5. `python -m py_compile` 改动过的 .py 文件，确认语法。

## 修改现有模板的步骤

1. 直接改 `templates/<name>.jinja2`。
2. 确认运行时确实 render 这个模板（grep `render("<name>.jinja2"`），别误改了一个没人用的死常量。
3. 若改动了变量名，同步所有 render 调用点。

## 纪律

- 不要在 .py 里新增 prompt 字符串常量——一律进模板。
- 改完只做静态检查，**不要对真实章节数据跑生成验证**。
