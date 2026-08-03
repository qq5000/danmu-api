# AListTVBox Python Spider 插件仓库

此目录按 [`har01d5/tvbox`](https://github.com/har01d5/tvbox/tree/master) 的 `py/`、`spiders.json`、`spiders_v2.json` 与校验报告结构整理，共包含 **38** 个 Python Spider。

## 与参考仓库的区别

参考仓库的 `.txt` 是 `secspider/1` 加密签名包，生成它需要仓库维护者未公开的主密钥和签名私钥。本目录采用公开源码 `.py` 分发，需要使用支持原始 Python 插件的 AListTVBox 版本。

## 上传 GitHub

1. 将本目录全部内容上传到你的 GitHub 仓库根目录。
2. 在电脑上进入仓库并生成自己的 Raw 地址：

```bash
python3 tools/build_manifests.py --repo 你的用户名/仓库名
```

3. 再提交更新后的 `spiders.json`、`spiders_v2.json`、`sites.json` 和 `config.json`。
4. GitHub Actions 会执行语法、Spider 接口和清单一致性校验。

## 在 AListTVBox 导入

进入 AListTVBox 的插件管理，选择“导入仓库”，填写 GitHub 仓库根地址：

```text
https://github.com/你的用户名/仓库名
```

AListTVBox 会自动读取仓库根目录的 `spiders_v2.json`。该文件采用兼容性更好的插件 URL 字符串数组格式；它是 AListTVBox 插件仓库索引，不是 TVBox App 的主配置地址。

本仓库对应的导入地址是：

```text
https://github.com/qq5000/danmu-api
```

## 本地校验

```bash
python3 tools/validate_spiders.py
```

## 依赖

运行时通常由电视端 Python Spider 环境提供 `base.spider`。脚本还可能使用 `requests`、`beautifulsoup4`、`lxml`、`pycryptodome`、`cryptography` 和 `cloudscraper`。

## 已做的兼容处理

- 为每个脚本添加稳定的 40 位 ID、名称、版本和源码格式元数据。
- 去掉文件名中的重复下载后缀 ` (1)`。
- 统一 `init` 与分页搜索入口的调用签名。
- 修正未继承 `base.spider.Spider` 的脚本。
- 补齐缺失的 `homeVideoContent` / `searchContent` 基础入口。
- 修正蛋挞脚本中空置的名称和视频格式判断。
- 原始脚本保持在上一级目录，不会被覆盖。

`unsupported/MissAV(自己填ck).js` 属于 Widget JavaScript 格式，不会加入 Python Spider 清单。

设备相关依赖与兼容提醒见 [`PORTABILITY.md`](PORTABILITY.md)。
