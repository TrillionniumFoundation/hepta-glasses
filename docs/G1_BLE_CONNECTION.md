# Hepta Glasses — G1 双 BLE 连接与协议实现

> English: [G1_BLE_CONNECTION.en.md](G1_BLE_CONNECTION.en.md)
>
> 状态：当前源码说明。硬件、固件和性能结论仍需物理 G1 的 E5 证据。

## 1. 产品边界

G1 左腿和右腿是两个独立 BLE 外设。手机端 Flutter 运行时负责状态机、请求关联、重试语义和业务编排；Android/iOS 原生层负责扫描、GATT 就绪、写队列、通知和 LC3 解码。仓库不包含 G1 固件、Bootloader 或签名 OTA 权限。

## 2. 分层

```text
Flutter UI / Assistant
        |
        v
BleManager + Hepta Runtime
  generation / request owner / quarantine / receipt
        |
        v
MethodChannel("method.bluetooth")
        |
        +-- Android BleManager.kt + BleDevice.kt
        |
        +-- iOS BluetoothManager.swift
        |
        v
G1 Left BLE + G1 Right BLE
```

下行使用 `method.bluetooth`；二进制上行使用 `eventBleReceive`；iOS 语音识别结果使用 `eventSpeechRecognize`。原生状态通过 `glassesConnecting`、`glassesConnected`、`glassesDisconnected` 和 `foundPairedGlasses` 回调 Flutter。

## 3. 广播与成对

设备名必须符合四段式名称，例如 `G1_45_L_xxx` 与 `G1_45_R_xxx`。同一 channel 同时出现左右腿后才形成 `Pair_<channel>`。左右腿保留独立连接和就绪状态；单腿成功不是 pair 成功。

## 4. GATT 合同

| 角色 | UUID |
|---|---|
| UART Service | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` |
| 手机写入 | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` |
| 手机订阅通知 | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` |

机器可读协议位于 `contracts/g1-ble-protocol-v1.json`。

## 5. Android 就绪状态机

1. 校验蓝牙和运行时权限并扫描。
2. 对左右设备分别 `connectGatt(autoConnect=false)`。
3. 发现 UART service、读特征、写特征和 CCCD；缺失任一项即失败关闭。
4. CCCD 写成功后请求 MTU 251；实际 MTU 必须至少为 203。
5. 初始化写入 `[0xF4, 0x01]` 被原生 API 接受后，该腿才标记 ready。
6. 左右腿都 ready 后才上报 `glassesConnected`。

每个连接捕获 generation。旧 GATT 回调会关闭而不会更新新会话。普通写入进入容量 128 的串行队列；队列满、GATT 未就绪或原生拒绝都返回失败。

## 6. iOS 就绪状态机

1. 扫描并按 channel 形成左右 pair。
2. 连接左右 `CBPeripheral`，发现 UART service 和读写特征。
3. RX 通知确认启用后才将该腿加入 ready 集合。
4. 初始化写入 `[0x4D, 0x01]` 进入有界写路径。
5. 左右腿都 ready 后才上报 `glassesConnected`。

主动断开不会自动重连；意外断开会清除该腿就绪与待写队列，并向 Flutter 报告降级状态。两平台初始化字节不同，必须由供应商固件合同或物理 trace 最终确认，不能仅由源码推定。

## 7. Flutter 请求关联

请求所有权键为：

```text
(connection generation, side L/R, command byte)
```

同一键同时只能有一个 owner。原生接受写入后若 ACK 超时，结果为 `indeterminate`，键进入 late-response quarantine；系统不会把超时当成确定失败并盲目重放。换代、断开或 dispose 会使待处理请求以“效果可能已发生”语义完成。

心跳采用单次定时器重新调度，防止周期任务重叠。pair 连接要求 `left_connected && right_connected`。

## 8. 语音路径

- iOS：LC3 200 字节帧解码为 3200 字节 PCM，进入系统 on-device Speech；只有 framework-final transcript 才作为最终文本，超时 partial 会被丢弃。
- Android：LC3 解码路径存在，但生产 PCM-to-ASR adapter 尚未配置；`startEvenAI` 明确失败关闭，不能宣称 Android 语音助手可用。

## 9. 关键命令

| 功能 | 命令 |
|---|---|
| 打开麦克风 | `0x0E` |
| 麦克风数据 | `0xF1` |
| TouchBar / Assistant 事件 | `0xF5` |
| AI 与文本显示 | `0x4E` |
| BMP 数据 / 结束 / CRC | `0x15` / `0x20` / `0x16` |
| 心跳 | `0x25` |
| 退出模式 | `0x18` |
| 通知 / 白名单 | `0x4B` / `0x04` |

成功状态为 `0xC9`；部分多包路径接受 `0xCB` 继续状态。字段、包长和显示状态以机器合同为准。

## 10. 断开与资源释放

Android 调用 `disconnect()`、`close()`，清空写队列和特征引用。iOS 取消 peripheral connection，清空 read/write characteristic、ready 集合和 pending writes。Flutter 同时停止心跳、失败关闭待处理请求并发布左右腿快照。

## 11. 尚未由源码关闭的结论

以下仍需要外部证据：真实 G1 丢包/重连、延迟、功耗、温度和 soak；固件版本兼容；初始化命令权威说明；Android ASR；iOS locale/设备覆盖；供应商固件、Bootloader、Secure Boot、OTA、恢复和回滚权限。

## 12. 源码索引

- `lib/ble_manager.dart`
- `lib/services/proto.dart`
- `lib/services/evenai.dart`
- `android/app/src/main/kotlin/com/example/demo_ai_even/bluetooth/BleManager.kt`
- `android/app/src/main/kotlin/com/example/demo_ai_even/model/BleDevice.kt`
- `ios/Runner/BluetoothManager.swift`
- `ios/Runner/SpeechStreamRecognizer.swift`
- `contracts/g1-ble-protocol-v1.json`
- `docs/PLATFORM_CAPABILITIES.json`
