# JPG + MP4 → 鸿蒙实况照片（HarmonyOS Live Photo）

把一对「同名 `.jpg` + `.mp4`」合成为 HarmonyOS NEXT 图库能识别的实况照片（Moving Photo）。**元数据零丢失、零重编码**：图像与视频均为原始字节搬运，EXIF / GPS / 视频码流原样保留。

- 纯 Python 标准库实现（仅校验阶段用到 Pillow），无需 ffmpeg 或其他外部依赖
- 支持批量转换、单组转换、产物校验
- 格式依据全部来自 OpenHarmony 官方源码，并用官方样本做了逐字节反向验证

## 原理

鸿蒙媒体库判定「实况照片」的唯一依据是 `MovingPhotoFileUtils::IsLivePhoto()`：**读文件最后 20 字节，检查是否以 `LIVE_` 开头**。缺少这 60 字节尾标记的 JPG+MP4 拼接文件，图库只会当成普通静态照片。

本工具的产物结构：

```
┌──────────────────────┬──────────────────────┬───────────────┐
│  原 JPG 全部字节       │  原 MP4 全部字节       │  60 字节尾标记  │
│  （含全部 EXIF/GPS）   │  （原码流，未转码）     │   (3 × 20)    │
└──────────────────────┴──────────────────────┴───────────────┘
```

尾标记三段各 20 字节、不足用空格补齐，规则与 OpenHarmony 源码中 `WriteExtraData()` 的定义一致：

| 段 | 生成函数 | 内容规则 |
|---|---|---|
| 版本/帧号 | `GetVersionPositionTag()` | `v3_f<frame>`（非相机拍摄）/ `v6_f<frame>`（相机拍摄），含 cinemagraph 追加 `_c` |
| 播放信息 | `GetDurationTag()` | `frame = coverPosition / 1000`；`frame < 600` 时 `0:<frame>`，否则 `<frame-600>:<frame>` |
| 视频信息 | `GetVideoInfoTag()` | `LIVE_` + (视频字节数 + 20) |

读取侧用同一套公式（`GetMovingPhotoDetailedSize()`）从文件总大小和 `LIVE_` 后的数字反算出图像区 / 视频区边界，因此拼接后鸿蒙可以准确定位视频起点（`ftyp`）正常解码。

## 快速开始

环境要求：Python 3（Windows 推荐；校验功能需要 `pip install pillow`）。

### 方式一：双击运行（Windows）

把素材放进 `input/` 目录（支持一次放多组同名 JPG+MP4），双击 **`转换实况照片.bat`** 即可，产物输出到 `out/`。

```
input/
  IMG_001.jpg  IMG_001.mp4     ← 第 1 组
  IMG_002.jpg  IMG_002.mp4     ← 第 2 组
  IMG_003.JPEG IMG_003.MP4     ← 扩展名大小写不敏感，也算一组
  IMG_004.jpg                  ← 缺视频，会被跳过并提示
```

配对规则：按「去掉扩展名后的文件名」严格匹配；同一基名出现多张图时只取第一张，其余在汇总里提示。

### 方式二：命令行

```powershell
# 批量：转换 input/ 下所有同名 JPG+MP4，逐组打印校验结果
python main.py

# 批量，只在失败时展开校验详情
python main.py --quiet

# 单组：输出到 out/图.jpg
python main.py 图.jpg 视频.mp4

# 单组：指定输出路径
python main.py 图.jpg 视频.mp4 出.jpg

# 校验一个已有的实况照片文件（不生成），判断鸿蒙是否会识别
python main.py --check 出.jpg
```

**`--check` 很实用**：拿到一个来路不明的 `.jpg`，想知道鸿蒙会不会认成实况照片，直接校验即可。它会按 `GetMovingPhotoDetailedSize` 公式反解，打印 imageSize / videoSize / extraDataSize，并检查视频区起点是不是 `ftyp`、图像区能否解码。

退出码：`0` 全部成功；`1` 有产物校验失败（对应产物不可用）；`2` 输入有误（未写任何文件）。

## 产物校验

写完文件后自动执行全套校验，任一项失败即以退出码 1 结束并提示请勿使用：

- 容器结构：输出长度 = JPG + MP4 + 60，各段字节逐字节一致
- 实况判定：末尾 20 字节以 `LIVE_` 开头
- 边界反算：按鸿蒙公式反算出的 imageSize / videoSize 与原文件完全一致
- 解析器判据：视频区起点恰好是 `ftyp`
- 元数据完整性：JPEG 段序列、EXIF 段字节、EOI 后调试块均保留
- 可解码性：图像可被 PIL 完整解码

## 目录结构

```
├─ 转换实况照片.bat            双击入口（薄包装，调用 main.py）
├─ main.py                    命令行入口：参数解析 / 结果展示 / 退出码
├─ input/                     原始素材（只读，不做任何修改）
├─ out/                       产物目录（与 input/ 同名的 .jpg）
├─ tools/
│  ├─ make_live.py            核心：60 字节尾标记 + 字节拼接 + 校验项
│  ├─ repro_official.py       格式自证：用官方样本反向验证
│  ├─ check_mp4.py            MP4 盒完整性 + 样本表校验（诊断）
│  ├─ dump_exif.py            JPEG 段 / EXIF 全字段导出（诊断）
│  └─ dump_boxes.py           MP4 盒树 / 编码参数导出（诊断）
└─ ref/openharmony/           OpenHarmony 权威源码留档
```

`main.py` 管「怎么用」（参数、展示、退出码），`tools/make_live.py` 管「怎么转」（尾标记格式、字节拼接、校验项）。想改格式只动 `make_live.py`，想改交互只动 `main.py`。

## 上机注意

1. 把 `out/` 下的产物传到手机 `DCIM/Camera/` 或 `Pictures/`；落到「下载」目录也可以，文件管理扫描器同样会识别。
2. **保持 `.jpg` 扩展名**。
3. **不要走会重新编码的通道**：微信 / QQ 发原图、图片编辑器另存、网盘预览转存都可能剥掉尾部 60 字节或整个视频段。华为分享、蓝牙、USB 拷贝、压缩包都安全。
4. 图库不刷新就杀掉图库进程重开，或清除图库缓存后重新扫描。

## 格式依据

全部结论来自 OpenHarmony 官方仓库 [`openharmony/multimedia_media_library`](https://github.com/openharmony/multimedia_media_library)（master），源码留档在 `ref/openharmony/`：

- `moving_photo_file_utils.h` —— `LIVE_TAG`、`LIVE_TAG_LEN=20`、`PLAY_INFO_LEN=20`、`VERSION_TAG_LEN=20`、`MIN_STANDARD_SIZE=60`
- `moving_photo_file_utils.cpp` —— `IsLivePhoto()`、`MergeFile()`、`WriteExtraData()`、`GetVersionPositionTag()`、`GetDurationTag()`、`GetVideoInfoTag()`、`GetMovingPhotoDetailedSize()`、`GetExtraDataSize()`
- `metadata_extractor.cpp` —— 媒体扫描器的实况照片元数据提取
- `media_fileinterwork_scanner.cpp` —— 文件管理扫描器同样以 `IsLivePhoto()` 判定
