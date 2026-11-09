# Tyranor Next Linux

Tyranor Next 的原生 Linux 桌面版本。项目使用 Python、PyQt6 和 SQLite，
通过 Linux 子进程直接启动游戏，不依赖 Android、Waydroid、Activity、JNI
或 APK 运行时。

## 主要功能

- 原生游戏库：目录扫描、深度控制、增量更新、搜索、排序、网格和列表视图。
- 引擎识别：KiriKiri、Tyrano、Ren'Py、RPG Maker MV/MZ、RPG Maker
  XP/VX/VX Ace、ONScripter、Artemis、Siglus、RealLive、AVG32、UK2、
  System35、System4、FVP、Ethornell、VN 和网页游戏。
- 启动管理：逐游戏参数、环境变量、启动前缀、运行状态保护和游玩时长记录。
- KiriKiri：使用原生 `krkrsdl3`，支持 XP3、Wayland、ALSA 和中央存档目录。
- Tyrano 与网页游戏：支持 3 GB 级 Electron ASAR 流式读取、HTTP Range、
  内嵌 Qt WebEngine、持久化浏览器存储和文件存档。
- Ren'Py：可调用系统运行时，也可使用随 RPM 安装的 Ren'Py 8.5.3。
- 存档管理：统一存档目录、旧存档迁移、ZIP 导入导出、内容版本、SHA-256
  校验、恢复和运行中写保护。
- RPG Maker 存档：MV/MZ 标准存档格式双向转换。
- 封面来源：本地图片、VNDB、NextMoe、Bangumi、Steam 和 Hikarinagi。
- WebDAV：双向、上传、下载、整库同步、内容版本和云端保留数量。
- 维护工具：XP3 查看、解包、重新封包、同名冲突保护、KSD 文本解码和补丁。
- 界面：首页、游戏库、引擎、设置、快捷启动、桌面快捷方式、主题和多语言。

没有可用 Linux 运行时的引擎不会显示在引擎页面。

## 系统要求

- Linux x86_64
- Python 3.11 或更高版本
- PyQt6 6.7 或更高版本
- PyQt6 WebEngine
- Pillow、requests、cryptography、lxml
- 桌面上需要可用的 Wayland 或 X11 会话

Fedora 45 的 RPM 包会声明全部运行时依赖。

## RPM 安装

完整离线包内包含主程序、KiriKiri 运行时和 Ren'Py 运行时。

```bash
tar -xzf Tyranor-Next-Linux-1.0.0-7-Fedora45-x86_64.tar.gz
cd Tyranor-Next-Linux-1.0.0-7-Fedora45-x86_64
sudo dnf install ./*.rpm
```

升级已安装版本：

```bash
sudo dnf upgrade \
  tyranor-next-linux-1.0.0-7.fc45.noarch.rpm \
  tyranor-next-krkr-runtime-0.0.6-4.gitbe6db96.fc45.x86_64.rpm \
  tyranor-next-renpy-runtime-8.5.3-1.fc45.x86_64.rpm
```

升级后请完全退出并重新打开启动器。

## 从源码运行

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e '.[test]'
./run.sh
```

安装到当前用户：

```bash
./install.sh
~/.local/bin/tyranor-next
```

运行测试：

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q tyranor
```

## 使用流程

1. 打开“游戏”页面并添加扫描目录。
2. 等待扫描完成，确认游戏引擎识别结果。
3. 如果运行时未安装，在“引擎”页面选择对应的 Linux 可执行文件。
4. 在游戏详情中设置启动文件、参数、环境变量或存档目录。
5. 点击启动。

参数模板支持：

```text
{path}         当前启动目标
{game_dir}     游戏目录
{target}       入口文件
{title}        游戏标题
{launch_file}  手动选择的启动文件
```

## 统一存档目录

所有由 Tyranor Next 管理的游戏默认把存档写入：

```text
~/.local/share/tyranor-next-linux/saves/game-<游戏哈希>/data
```

首次启动时会安全复制游戏目录中的旧存档，不覆盖已经存在的中央存档。

- KiriKiri 通过 `TYRANOR_SAVE_DIR` 重定向。
- Ren'Py 使用 `--savedir`。
- Tyrano 使用本地 HTTP 存档桥接。
- 网页游戏使用每游戏独立的 WebEngine 持久化存储路径。

也可以在单个游戏的设置中指定自定义存档目录。

## 数据目录

```text
~/.local/share/tyranor-next-linux/library.db
~/.local/share/tyranor-next-linux/covers/
~/.local/share/tyranor-next-linux/saves/
~/.local/share/tyranor-next-linux/logs/
~/.config/tyranor-next-linux/settings.json
~/.config/tyranor-next-linux/secrets.json
```

凭据文件权限会设置为 `0600`。

## 构建 RPM

构建主程序：

```bash
./packaging/build-rpm.sh
```

构建 Ren'Py 运行时：

```bash
./packaging/build-renpy-rpm.sh
```

构建 KiriKiri 运行时需要预先编译好的 `krkrsdl3`：

```bash
KRKR_PREBUILT_DIR=/path/to/krkrsdl3-release \
  ./packaging/build-krkr-rpm.sh
```

输出文件位于 `dist/`。

## GitHub Actions

工作流会在以下情况运行：

- 向 `main` 分支推送代码
- 提交拉取请求
- 手动触发

任务包括：

- Python 编译检查和单元测试
- Fedora 容器中的主程序 RPM 构建
- Ren'Py 运行时 RPM 构建
- 构建产物上传

主程序和 Ren'Py 运行时可从 Actions 的 Artifacts 下载。KiriKiri 原生二进制
体积较大，建议以 Release 附件分发。

## 运行时说明

- 原 Android 工程中的 ARM64 `.so` 不能直接加载到 x86_64 Linux。
- KiriKiri 使用为 Wayland、X11、ALSA 和软件渲染构建的 `krkrsdl3`。
- Tyrano 的 Electron 文件存档由本地 HTTP 桥接替代。
- Ren'Py 分发包中存在可执行启动脚本时优先使用游戏自带启动器。
- 本项目不包含商业游戏资源。
- 引擎识别成功不代表该作品的每个版本都已经逐作品验证。

## 故障排查

启动器的总日志：

```text
~/.local/share/tyranor-next-linux/launcher.log
```

单个游戏的日志：

```text
~/.local/share/tyranor-next-linux/logs/game-<游戏哈希>.log
```

也可以在游戏详情页直接打开对应日志。

如果 RPM 升级后图标没有立即刷新，请重新登录桌面会话。如果游戏没有声音，
确认 PipeWire、WirePlumber 和 `alsa-lib` 正常工作。

## 许可证

本项目使用 GPL-2.0-only。第三方运行时分别遵循其上游许可证。
