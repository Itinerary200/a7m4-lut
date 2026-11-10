# vendored from Erlla/sony-a7m4-custom-firmware (main)
- training/source/look_v2.py   -> vendor/m4/look_v2.py
- training/source/native_codec.py -> vendor/m4/native_codec.py

用途:按官方 camera-look v2 规范校验/封签/编码;不修改原文件语义。
来源:https://github.com/Erlla/sony-a7m4-custom-firmware
## 追加 vendor(供 m4fit 的冻结模型前向使用)
- training/source/response_network.py
- training/source/pixel_bridge.py
- training/source/host_grid.py
- training/source/grid_base.py
- training/source/grid_math.py
