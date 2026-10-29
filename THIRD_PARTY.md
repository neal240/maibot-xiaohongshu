# 第三方依赖核对记录

本插件自身的许可证见 `LICENSE`。插件不打包下表的 Python 项目；以下记录来自隔离环境中实际安装版本的包元数据，用于辅助复核，不代表对所有传递依赖和二进制包完成了审查。

| 依赖 | 核对版本 | 包声明或许可证文件 |
| --- | --- | --- |
| xhshow | 0.2.0 | MIT |
| curl-cffi | 0.16.2 | MIT |
| pycryptodome | 4.2.0 | BSD-2-Clause AND Unlicense AND MIT |
| qrcode | 8.2 | BSD；包内 LICENSE 为三条款 BSD 文本。包元数据另含 Other/Proprietary 分类，需在分发前核对上游声明。 |
| Pillow | 12.3.0 | MIT-CMU |
| cryptography | 50.0.1 | Apache-2.0 OR BSD-3-Clause |
| maibot-plugin-sdk（宿主运行依赖） | 2.16.0 | LGPL-3.0-only |
| Playwright（可选浏览器登录助手） | 1.62.1 | Apache-2.0，需结合实际安装包复核 |

用户另行安装的依赖、传递依赖、浏览器及系统库都有各自的许可证；实际分发 wheel 或打包运行环境前，应检查所含原生库及许可证文本，并遵守相应的署名和分发要求。依赖版本范围可选取其他版本，表内信息不覆盖其他版本。
