# Tauri 图标生成指南

> **文件定位**:`packages/desktop/tauri/icons/` 下那堆图标怎么生成 / 替换 / 引用。
> **面向**:换 logo 时 / 第一次打包发 release 前。
> **前置**:`packages/desktop/` 已 `bun install`(用 `@tauri-apps/cli` 提供的 `tauri icon` 子命令)。

---

## 一图流

| 产物 | 作用 | 必填? |
|---|---|---|
| `icon.ico` | Windows exe 图标 · 任务栏 · 资源管理器 · 安装包 | ✅ 桌面必须 |
| `icon.icns` | macOS 应用图标 | macOS 打包时 |
| `icon.png` | Linux / 兜底 | Linux 打包时 |
| `32x32.png` / `128x128.png` / `128x128@2x.png` | 多尺寸 PNG,窗口顶栏 / 系统托盘 | ✅ Tauri runtime 要 |
| `Square*Logo.png` × 9 + `StoreLogo.png` | Windows Store / MSIX 专用尺寸 | 走 MSIX 才用 |
| `android/` + `ios/` | 移动端启动图(mobile build) | v0.1 不用 |

v0.1 桌面场景,**`tauri.conf.json` 的 `bundle.icon` 只需 5 条**(32/128/256/icns/ico);其余文件生成出来留着,占不了多少空间。

---

## 一、源 PNG 要求

| 属性 | 要求 | 说明 |
|---|---|---|
| 尺寸 | **1024×1024**(推荐),最小 512×512 | 小于 256 会糊,Tauri CLI 仍会生成但大图标拉伸明显 |
| 比例 | **方形 1:1** | 非方形会被拒 / 强裁 |
| 背景 | 透明 PNG | macOS / iOS 会自动加圆角,源图别自己加 |
| 格式 | `.png` | CLI 官方支持;其它格式先转 PNG |

**放哪**:本项目素材源文件放 `assets/`(用户自己维护的目录)。示例:`assets/logo-icon.png`。

---

## 二、生成命令

在 repo 根跑:

```bash
bun --filter=@rosetta/desktop tauri icon ../../assets/logo-icon.png --output tauri/icons
```

说明:
- `--filter=@rosetta/desktop` 定位到 desktop workspace
- `tauri icon` 是 `@tauri-apps/cli` 的子命令
- 源路径 `../../assets/logo-icon.png` 是**相对 `packages/desktop/` 的路径**(filter 后 cwd 切到 desktop workspace)
- `--output tauri/icons` 输出目录(相对 desktop workspace)

跑完会刷出一长串 "iOS Creating ..." / "Android Creating ..." / "Desktop Creating ...",最后 `Exited with code 0` 就是成功。

### 替代:只替换 `icon.ico`(紧急用)

手头只有现成的 .ico,不想跑 CLI,就**直接覆盖**:

```
packages/desktop/tauri/icons/icon.ico
```

前提是这个 .ico **内嵌多尺寸**(至少 256/48/32/16),否则 Windows 大图标处会糊。

---

## 三、引用:更新 `tauri.conf.json`

```json
"bundle": {
  "icon": [
    "icons/32x32.png",
    "icons/128x128.png",
    "icons/128x128@2x.png",
    "icons/icon.icns",
    "icons/icon.ico"
  ]
}
```

路径相对 `tauri.conf.json` 所在目录(即 `packages/desktop/tauri/`)。

桌面场景就这 5 条;MSIX / mobile 要再加对应文件。

---

## 四、验证

换完图标后:

```bash
# 1. cargo check 确认 tauri-build 能识别 icon
export PATH="$HOME/.cargo/bin:$PATH"  # (如果当前 shell 没 cargo)
cd packages/desktop/tauri && cargo check

# 2. dev 起窗口看效果
bun --filter=@rosetta/desktop dev
```

窗口顶栏图标 + 任务栏图标 + exe 属性里的图标都应该变成新 logo。

---

## 五、常见坑

| 症状 | 原因 | 解决 |
|---|---|---|
| `icons/icon.ico not found` | tauri-build 找不到 .ico,生成不了 Windows PE Resource | `tauri icon` 跑完,或手放一个 .ico 到 `packages/desktop/tauri/icons/icon.ico` |
| `Image must be square` | 源 PNG 非 1:1 | 裁剪或加透明 padding 成方形 |
| 生成后大图标糊 | 源 PNG 太小(< 256)被升采样 | 用 512 或 1024 的源 |
| `tauri.conf.json` 里 bundle.icon 路径错 | 路径相对 `tauri.conf.json` 所在目录 | 用 `icons/xxx.png`,不要写 `tauri/icons/xxx.png` |
| Tauri dev 窗口图标没变 | 改了 conf 但 tauri dev 没重启 | `Ctrl+C` 停,再 `bun run dev` |

---

## 六、目录清单(生成后)

```
packages/desktop/tauri/icons/
├── icon.ico              # Windows · 多尺寸嵌入
├── icon.icns             # macOS
├── icon.png              # 1024 · 兜底
├── 32x32.png
├── 64x64.png
├── 128x128.png
├── 128x128@2x.png        # 256
├── Square30x30Logo.png   # Windows Store / MSIX
├── Square44x44Logo.png
├── Square71x71Logo.png
├── Square89x89Logo.png
├── Square107x107Logo.png
├── Square142x142Logo.png
├── Square150x150Logo.png
├── Square284x284Logo.png
├── Square310x310Logo.png
├── StoreLogo.png
├── android/              # mipmap-hdpi/mdpi/xhdpi/xxhdpi/xxxhdpi 下的 ic_launcher*.png
└── ios/                  # AppIcon 各种尺寸
```

全部 **commit**(icons 是代码产物,需要入版本库);`.gitignore` 没排除 icons/。

---

## 七、最小可用检查清单

```bash
# 1. 生成
bun --filter=@rosetta/desktop tauri icon ../../assets/logo-icon.png --output tauri/icons

# 2. 确认至少这 5 个存在
ls packages/desktop/tauri/icons/{32x32,128x128,128x128@2x}.png \
   packages/desktop/tauri/icons/icon.{ico,icns}

# 3. tauri.conf.json 的 bundle.icon 含这 5 条

# 4. cargo check 过
(cd packages/desktop/tauri && cargo check)
```

四条都对,打包 / dev 就都能正常显示 logo。

---

## 参考

- Tauri 2 icon 命令:<https://v2.tauri.app/reference/cli/#icon>
- 推荐源尺寸 / 设计规范:<https://v2.tauri.app/distribute/icons/>
