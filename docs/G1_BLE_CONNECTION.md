# Hepta Glasses — G1 双 BLE 连接、效果权威与协议实现

> English: [G1_BLE_CONNECTION.en.md](G1_BLE_CONNECTION.en.md)
>
> 状态：`2026-09-01-g8` 当前源码规范。硬件、固件、性能和兼容性结论仍需物理 G1 的 E5 证据。

## 1. 产品与权威边界

G1 左腿和右腿是两个独立 BLE 外设。手机端 Flutter 运行时负责业务编排、请求关联、重试语义、幂等域和不确定效果隔离；Android/iOS 原生层负责扫描、GATT 就绪、有界写队列、通知和 LC3 解码。

模型、Skill、MCP、Codex 和 UI 都不能直接取得设备写权限。最终 BLE 效果权威属于移动端执行边界。仓库不包含 G1 固件、Bootloader、Secure Boot 或签名 OTA 权限。

## 2. 分层

```text
Flutter UI / Assistant
        |
        v
Hepta Runtime / Tool Gateway / Policy
        |
        v
EvenG1Transport
  authority = pair + generation + side + caller key + payload digest
        |
        v
BleManager
  response owner = generation + side + command
  quarantine   = generation + side + command
        |
        v
MethodChannel("method.bluetooth")
        |
        +-- Android BleManager.kt / generation-captured GATT callback
        |
        +-- iOS BluetoothManager.swift
              immutable PeripheralAttemptToken + delegate proxy
        |
        v
G1 Left BLE + G1 Right BLE
```

下行使用 `method.bluetooth`；二进制上行使用 `eventBleReceive`；iOS 语音识别结果使用 `eventSpeechRecognize`。原生状态通过 `glassesConnecting`、`glassesConnected`、`glassesDisconnected` 和 `foundPairedGlasses` 回调 Flutter。

## 3. 广播、成对与 pair identity

设备名必须符合四段式名称，例如 `G1_45_L_xxx` 与 `G1_45_R_xxx`。同一 channel 同时出现左右腿后才形成 `Pair_<channel>`。

`pairIdentity` 是设备效果权威的一部分。它不是用户可见昵称，而是当前成对选择的最小稳定标识。源码中的 channel identity 仍需物理设备和供应商文档确认其跨恢复、换机和固件升级语义；生产设计可进一步升级为受设备证明约束的 pair identity。

左右腿保留独立连接、就绪、请求 owner、隔离和 receipt。单腿成功不是 pair 成功。

## 4. GATT 合同

| 角色 | UUID |
|---|---|
| UART Service | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` |
| 手机写入 | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` |
| 手机订阅通知 | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` |

机器可读协议位于 `contracts/g1-ble-protocol-v1.json`。该合同同时规定 callback owner、幂等身份、native pre-write assertion、重连 barrier 和 quarantine 释放条件。

## 5. Android 就绪与回调状态机

1. 校验蓝牙和运行时权限并扫描。
2. 对左右设备分别 `connectGatt(autoConnect=false)`。
3. 发现 UART service、读特征、写特征和 CCCD；缺失任一项即失败关闭。
4. CCCD 写成功后请求 MTU 251；实际 MTU 必须至少为 203。
5. 初始化写入 `[0xF4, 0x01]` 被原生 API 接受后，该腿才标记 ready。
6. 左右腿都 ready 后才上报 `glassesConnected`。

每个 GATT callback 实例捕获连接 generation，并验证自身仍是当前 pair 中的选中 GATT；旧回调会关闭旧 GATT，不得修改新会话。普通写入进入容量 128 的串行队列；队列满、GATT 未就绪、expected generation 不一致、expected pair 不一致或原生拒绝均在写前失败关闭。

解码后的回调再次验证 generation 和 pair identity，防止后台 LC3 工作跨会话发布。

## 6. iOS immutable connection-attempt 状态机

### 6.1 Attempt token

每一腿的每次连接都有不可变 token：

```text
PeripheralAttemptToken {
  peripheralID,
  side,
  generation,
  attemptNonce
}
```

`ConnectionAttemptAuthority` 对每个 peripheral identity 只保留一个 current token。service discovery、characteristic discovery、notification state、value update 和 write-ready 回调都由该 attempt 专属的 delegate proxy 转发；任何回调必须先同时满足：

```text
token is current
&& token.generation == current generation
&& token.peripheralID == callback peripheral
&& callback peripheral === selected peripheral for token.side
```

未识别 peripheral 没有 side，不允许使用“不是左腿即右腿”的 fallback。

### 6.2 Retired-peripheral barrier

`CBCentralManager` 的 connect/fail/disconnect callback 不携带调用方 generation。为防止同一个 `CBPeripheral` 对象的旧 terminal callback 清理新 attempt，取消中的 peripheral identity 会进入 `RetiredConnectionBarrier`。

同一 peripheral 不能分配给下一 generation，直到旧 attempt 的 `didFailToConnect` 或 `didDisconnectPeripheral` 被 barrier 消费。激活新 attempt 还会推迟到下一主队列 turn，使同一批次中的额外旧回调在没有 current token 的窗口内被拒绝。

### 6.3 就绪

1. 扫描并按 channel 形成左右 pair。
2. 为左右腿创建 token 与 delegate proxy，再连接外设。
3. 发现 UART service 和读写特征。
4. RX 通知确认启用后才将该腿加入 ready 集合。
5. 初始化写入 `[0x4D, 0x01]` 通过有界写路径。
6. 两腿 current token 都 ready 后才上报 pair ready。

两平台初始化字节不同，必须由供应商固件合同或物理 trace 最终确认，不能仅由源码推定。

## 7. 复合幂等身份

公开传输层的 receipt、in-flight coalescing 和 payload claim 使用以下完整身份：

```text
(pairIdentity,
 connectionGeneration,
 side,
 callerIdempotencyKey,
 SHA256(deviceBytes))
```

因此：

- 左腿使用 caller key `K` 不会抑制右腿的 `K`；
- generation N 的 `K` 不会抑制重连后 generation N+1 的 `K`；
- Pair_A 的 `K` 不会抑制 Pair_B 的 `K`；
- 同一完整 scope 中 `K` 对应不同 payload 会立即失败关闭；
- 同一完整 identity 的并发请求只共享同一个 in-flight owner；
- receipt 容量耗尽时拒绝新的 authority，而不是驱逐当前 generation 的旧 receipt 后冒险重复效果。

Flutter 在异步调用开始时捕获 pair/generation，调用 native 前重新检查，并把 `expectedPairIdentity`、`expectedGeneration` 传入 Android/iOS。原生层在真正接受字节前再次比较当前权威。

## 8. 请求关联与不确定效果隔离

ACK owner 与 late-response quarantine 的键为：

```text
(connectionGeneration, side L/R, commandByte)
```

同一键同时只能有一个 owner。原生接受写入后若 ACK 超时，结果为 `indeterminate/effectMayHaveOccurred`，键进入 quarantine；系统不能把超时当成确定失败并自动重放。

Quarantine 只能由以下事件释放：

1. 对应 generation/side/command 的迟到响应被观察；
2. 权威 reconciliation 确认该 exact leg/command 的状态；
3. 对应 connection generation 被明确退休并进入新的 authority namespace；
4. 进程终止性 dispose/test reset。

单腿断连只会失败或隔离该腿当前 pending owner。它不会清除另一腿已经存在的 quarantine。例如右腿写入 ACK 超时后，即使左腿断连，右腿同一命令仍保持不可重放。

## 9. 失败结果语义

| 结果 | 是否可能已产生效果 | 自动重试 |
|---|---:|---:|
| expected authority 不匹配 | 否 | 可在重新获取 authority 后重试 |
| side 未 ready / native 明确未接受 | 否 | 可按预算重试 |
| ACK 超时 | 是 | 禁止，必须 reconcile |
| native 调用异常且接受状态未知 | 是 | 禁止，必须 reconcile |
| negative ACK | 取决于协议；当前按源码结果处理 | 仅按命令合同 |
| success/continue ACK | 是，已接受 | 返回 receipt，不重复写 |

上层不得把这些状态压扁为一个无法区分“写前拒绝”和“效果未知”的普通布尔值。

## 10. 语音路径

- iOS：LC3 200 字节帧解码为 3200 字节 PCM，进入系统 on-device Speech；只有 framework-final transcript 才作为最终文本，超时 partial 会被丢弃。旧 attempt token 的语音帧不得进入当前识别会话。
- Android：LC3 解码路径存在，但生产 PCM-to-ASR adapter 尚未配置；`startEvenAI` 明确失败关闭，不能宣称 Android 语音助手可用。

## 11. 关键命令

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

成功状态为 `0xC9`；部分多包路径接受 `0xCB` 继续状态。字段、包长和值域以机器合同为准。

## 12. 敌对测试矩阵

| 测试 | 证明目标 |
|---|---|
| generation N token 在 N+1 后到达 | 不得拥有或修改 N+1 |
| 未选择 peripheral 回调 | 不得 fall through 为右腿 |
| 同 peripheral 快速重连 | 旧 terminal callback 消费前不得启动新 attempt |
| 同 caller key 跨左右腿 | 必须执行两次独立的 side-authorized 写入 |
| 同 caller key 跨 generation | 新 generation 必须拥有独立 authority |
| 同 caller key 跨 pair | 新 pair 必须拥有独立 authority |
| 同 scope key 改 payload | 必须失败关闭 |
| 右腿 uncertain、左腿断连 | 右腿 quarantine 必须保留 |

测试入口：

- `test/runtime/even_g1_transport_authority_test.dart`
- `test/runtime/ble_request_slot_test.dart`
- `test/runtime/ble_manager_authority_test.dart`
- `ios/RunnerTests/RunnerTests.swift`

## 13. 断开与资源释放

Android 调用 `disconnect()`、`close()`，清空对应写队列和特征引用。iOS 首先退休 token、解除 delegate、清理对应 side，再取消连接；取消中的 peripheral 保留 barrier，直到 terminal callback 被消费。

Flutter 停止 pair heartbeat，按 side 失败关闭 pending 请求，并发布左右腿快照。只有 generation retirement 才能清除该旧 generation 的 quarantine；普通单腿 disconnect 不清除 surviving side。

## 14. 尚未由源码关闭的结论

以下仍需要外部证据：真实 G1 丢包/重连、迟到 callback 分布、延迟、功耗、温度和 soak；固件版本兼容；初始化命令权威说明；pair identity 稳定性；Android ASR；iOS locale/设备覆盖；供应商固件、Bootloader、Secure Boot、OTA、恢复和回滚权限。

## 15. 源码索引

- `lib/adapters/even_g1/even_g1_transport.dart`
- `lib/ble_manager.dart`
- `lib/runtime/ble_request_slot.dart`
- `lib/runtime/device_hal.dart`
- `lib/services/ble.dart`
- `lib/services/proto.dart`
- `lib/services/evenai.dart`
- `android/app/src/main/kotlin/com/example/demo_ai_even/bluetooth/BleManager.kt`
- `android/app/src/main/kotlin/com/example/demo_ai_even/model/BleDevice.kt`
- `ios/Runner/BluetoothManager.swift`
- `ios/Runner/SpeechStreamRecognizer.swift`
- `contracts/g1-ble-protocol-v1.json`
- `docs/PLATFORM_CAPABILITIES.json`
