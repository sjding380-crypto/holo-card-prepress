# holo-card-prepress · 实体闪卡制作 Skill

将现有图片规划为局部镭射闪卡设计：先标记发闪元素，逐版确认，再制作精细蒙版、完整彩色图与白墨母版，最后按印刷厂家模板适配。

适用于实体闪卡、闪吧唧和局部白墨印刷；不用于单词记忆卡或网页 3D 闪卡效果。

## 工作流程

1. **元素方案**：查看原图，标记 F01… 发闪候选和 P01… 保护区，展示实际标记图并等待确认。
2. **分层制作**：确认后制作同尺寸、同坐标的精细蒙版；彩色图保留原图像素，输出白墨版、透明素材及边缘对照图，再次等待确认。
3. **厂家适配**：核对尺寸、出血、白墨极性、专色格式与色彩配置，展示交付稿并等待定稿确认。

每次修改保留版本；上一阶段的批准不能代替下一阶段的批准。

## 三层的含义

| 层 | 内容 | 用途 |
| --- | --- | --- |
| 彩色图层 | 完整原图 | 人物、背景、文字和颜色 |
| 白墨图层 | 不闪处铺白墨，发闪处留空 | 控制底材透出的区域 |
| 镭射底材 | 厂家实际采用的镭射材料 | 随角度变化的反光 |

主要生产文件是**完整彩色图＋白墨版**。单元素透明 PNG 用于编辑和核对；镭射底材是实物。设计母版未适配厂家规格前，不标为可直接上机印刷。

## 安装与调用

下载本仓库，将整个目录放入 Codex 的 skills 目录，目录名保持为 `holo-card-prepress`。常见位置：

- Windows：`%USERPROFILE%\.codex\skills\holo-card-prepress`
- macOS / Linux：`~/.codex/skills/holo-card-prepress`

如果设置了 `CODEX_HOME`，使用其 `skills` 子目录。新会话中提供原图并调用：

```text
$holo-card-prepress 请分析这张图适合哪些位置发闪，先给我编号标记图，确认后再抠图。
```

## 脚本依赖与检查

Python 3.10+，Pillow 10.1+。在本仓库根目录运行：

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/prepress.py --help
```

脚本负责标记、确认记录、已有蒙版的组合与导出，**不自带图像识别或自动分割模型**。精细蒙版需要通过可用的图像编辑、分割或路径工具制作，并检查边缘。

## 内容导航

- [Skill 入口](SKILL.md)
- [分层依据与设计建议](references/layer-design-research.md)
- [厂家交付说明](references/manufacturer-handoff.md)
- [命令与文件格式](references/tool-workflow.md)
- [图像处理脚本](scripts/prepress.py)

默认直接印刷工艺保留完整彩色图，只在批准区域撤去白墨。实物反光还受油墨、底材和覆膜影响；检查图不代表实际镭射效果。不同印刷商的灰阶白墨、缩边和专色要求应分别核实。
